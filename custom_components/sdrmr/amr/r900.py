"""
Neptune R900 decoder.

Ported from github.com/bemasher/rtlamr r900/r900.go (AGPL-3.0).

Protocol parameters:
  Center frequency : 912,380,000 Hz
  Data rate        : 32,768 symbols/s
  Preamble         : "00000000000000001110010101100100"  (32 bits)
  Packet symbols   : 116

The R900 uses 6-symbol modulation (three base 4-chip patterns plus their
inverses), demodulated via a cumulative-sum matched filter.  Payload symbols
are read at every 4th chip.  Pairs of base-6 digits are decoded to 5-bit
values (GF32 symbols), validated by a Reed-Solomon syndrome check, then
fields are extracted from the resulting bit string.

Field layout (from r900.go NewSCM, in the 105-bit payload):
  bits  0-31  : ID (32 bits)
  bits 32-39  : Unkn1 (8 bits)
  bits 40-45  : NoUse (6 bits)
  bits 46-47  : BackFlow (2 bits)
  bits 48-71  : Consumption (24 bits)
  bits 72-73  : Unkn3 (2 bits)
  bits 74-77  : Leak (4 bits)
  bits 78-79  : LeakNow (2 bits)
  bits 80-104 : Reed-Solomon check symbols (5 × 5-bit GF32 symbols)
"""

from __future__ import annotations

import numpy as np

from .demod import bits_to_int, filter_manchester, magnitude, search  # noqa: F401

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

R900_CENTER_FREQ = 912_380_000
R900_DATA_RATE = 32_768

_PREAMBLE_STR = "00000000000000001110010101100100"
_PREAMBLE = np.array([int(b) for b in _PREAMBLE_STR], dtype=np.uint8)
_PREAMBLE_LEN = len(_PREAMBLE)   # 32
_PACKET_SYMBOLS = 116
_PAYLOAD_SYMBOLS = 42            # number of 6-ary symbols after preamble


# ---------------------------------------------------------------------------
# GF(2^5) arithmetic for Reed-Solomon syndrome check
# Primitive polynomial: x^5 + x^2 + 1 = 37 (decimal)
# Generator element: α = 2
# ---------------------------------------------------------------------------

_GF_ORDER = 32
_GF_POLY = 37  # x^5 + x^2 + 1


def _build_gf_tables(order: int, poly: int) -> tuple[list[int], list[int]]:
    size = order
    exp_table = [0] * (size * 2)
    log_table = [0] * size
    x = 1
    for i in range(size - 1):
        exp_table[i] = x
        log_table[x] = i
        x <<= 1
        if x >= size:
            x ^= poly
    for i in range(size - 1, size * 2):
        exp_table[i] = exp_table[i - (size - 1)]
    return exp_table, log_table


_EXP, _LOG = _build_gf_tables(_GF_ORDER, _GF_POLY)


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[(_LOG[a] + _LOG[b]) % (_GF_ORDER - 1)]


def _rs_syndrome_ok(symbols: list[int]) -> bool:
    """Evaluate the received polynomial at roots α^1 through α^5.

    Mirrors rtlamr's gf.Field.Syndrome(rsBuf, 5, 29) call where rsBuf has
    symbols[:16] in positions 0-15 and symbols[16:21] in positions 26-30
    (a shortened RS code).  Returns True if all syndromes are zero.
    """
    rs_buf = [0] * 31
    for i, s in enumerate(symbols[:16]):
        rs_buf[i] = s
    for i, s in enumerate(symbols[16:21]):
        rs_buf[26 + i] = s

    # Evaluate polynomial at α^i for i in 1..5 using Horner's method
    for root_exp in range(1, 6):
        alpha = _EXP[root_exp]
        result = 0
        for sym in rs_buf:
            result = _gf_mul(result, alpha) ^ sym
        if result != 0:
            return False
    return True


# ---------------------------------------------------------------------------
# R900 6-symbol matched filter  (r900.go Parser.filter + Parser.quantize)
#
# Three orthogonal 4-chip patterns (and their bitwise inverses = 6 symbols):
#   3 = 1100 (+1, +1, -1, -1)
#   4 = 1010 (+1, -1, +1, -1)
#   5 = 1001 (+1, -1, -1, +1)
#   0 = 0011  (inverse of 3)
#   1 = 0101  (inverse of 4)
#   2 = 0110  (inverse of 5)
# ---------------------------------------------------------------------------

def _r900_filter_quantize(mag: np.ndarray, chip_length: int) -> np.ndarray:
    """Return a per-sample array of 6-symbol values (0-5).

    Computes cumulative-sum correlations with the three base patterns.
    """
    n = len(mag)
    csum = np.empty(n + 1, dtype=np.float64)
    csum[0] = 0.0
    np.cumsum(mag, out=csum[1:])

    cl = chip_length
    out_len = n - cl * 4
    if out_len <= 0:
        return np.empty(0, dtype=np.uint8)

    i = np.arange(out_len)
    c0 = csum[i]
    c1 = csum[i + cl] * 2
    c2 = csum[i + cl * 2] * 2
    c3 = csum[i + cl * 3] * 2
    c4 = csum[i + cl * 4]

    # Correlations with the three base 4-chip symbols
    v0 = c2 - c4 - c0            # 1100
    v1 = c1 - c2 + c3 - c4 - c0  # 1010
    v2 = c1 - c3 + c4 - c0       # 1001

    abs_v0 = np.abs(v0)
    abs_v1 = np.abs(v1)
    abs_v2 = np.abs(v2)

    # argmax of |v0|, |v1|, |v2|
    argmax = np.where(abs_v2 > np.maximum(abs_v0, abs_v1), 2,
             np.where(abs_v1 > abs_v0, 1, 0)).astype(np.uint8)

    # Pick the actual value at argmax position
    vals = np.stack([v0, v1, v2], axis=1)
    selected = vals[np.arange(out_len), argmax.astype(int)]

    # Positive → base symbol (+3); negative → inverse symbol
    quantized = argmax.copy()
    quantized[selected > 0] += 3
    return quantized


# ---------------------------------------------------------------------------
# Payload extraction and parsing
# ---------------------------------------------------------------------------

def _decode_r900_payload(quantized: np.ndarray, payload_start: int, chip_length: int) -> dict | None:
    """Extract and decode an R900 payload from the quantized 6-symbol array.

    Reads 42 symbols at every 4th chip, interprets pairs as base-6 digits to
    produce 21 GF(32) symbols (5 bits each), validates RS, then parses fields.
    """
    step = chip_length * 4
    positions = payload_start + np.arange(_PAYLOAD_SYMBOLS) * step
    if positions[-1] >= len(quantized):
        return None

    digits = quantized[positions]

    symbols: list[int] = []
    bit_str = ""
    for i in range(0, len(digits), 2):
        d1, d2 = int(digits[i]), int(digits[i + 1])
        sym = d1 * 6 + d2
        if sym > 31:
            return None  # invalid base-6 pair
        symbols.append(sym)
        bit_str += format(sym, "05b")

    if len(bit_str) < 80:
        return None

    # Reed-Solomon syndrome check
    if not _rs_syndrome_ok(symbols):
        return None

    # Extract fields from the 105-bit string
    meter_id = int(bit_str[0:32], 2)
    if meter_id == 0:
        return None
    unkn1 = int(bit_str[32:40], 2)
    no_use = int(bit_str[40:46], 2)
    backflow = int(bit_str[46:48], 2)
    consumption = int(bit_str[48:72], 2)
    unkn3 = int(bit_str[72:74], 2)
    leak = int(bit_str[74:78], 2)
    leak_now = int(bit_str[78:80], 2)

    return {
        "msg_type": "R900",
        "meter_id": meter_id,
        "endpoint_type": None,  # R900 is always water
        "consumption": consumption,
        "unkn1": unkn1,
        "no_use": no_use,
        "backflow": backflow,
        "unkn3": unkn3,
        "leak": leak,
        "leak_now": leak_now,
    }


# ---------------------------------------------------------------------------
# Public decode function
# ---------------------------------------------------------------------------

def decode_block(raw: bytes, sample_rate: int) -> list[dict]:
    """Decode one block of raw RTL-SDR IQ bytes, returning R900 readings.

    The preamble is searched in the Manchester-filtered binary signal (same
    infrastructure as SCM), then the R900-specific 6-symbol filter is applied
    to the raw magnitude for payload demodulation.

    Parameters
    ----------
    raw:
        Interleaved uint8 IQ bytes from rtl_tcp.
    sample_rate:
        SDR sample rate in Hz.
    """
    chip_length = sample_rate // R900_DATA_RATE
    symbol_length = chip_length * 2

    mag = magnitude(raw)

    # Preamble search uses the same Manchester binary stream as SCM
    binary_bits = filter_manchester(mag, chip_length)
    preamble_offsets = search(binary_bits, _PREAMBLE, symbol_length)

    if not preamble_offsets:
        return []

    # R900 payload uses 6-symbol filter on the raw magnitude
    quantized = _r900_filter_quantize(mag, chip_length)

    preamble_samples = _PREAMBLE_LEN * symbol_length
    results: list[dict] = []
    seen: set[tuple] = set()

    for bit_offset in preamble_offsets:
        # Convert preamble bit-offset to sample-offset, then find payload start
        sample_offset = bit_offset
        payload_start = sample_offset + preamble_samples - symbol_length

        reading = _decode_r900_payload(quantized, payload_start, chip_length)
        if reading is None:
            continue

        key = (reading["meter_id"], reading["consumption"])
        if key in seen:
            continue
        seen.add(key)
        results.append(reading)

    return results


