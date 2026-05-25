"""
Core signal processing for ERT/AMR meter signals.

Ported from github.com/bemasher/rtlamr protocol/decode.go (AGPL-3.0).

Pipeline for SCM / SCM+ (Manchester FSK):
  1. Compute squared magnitude from IQ bytes using a lookup table.
  2. Apply Manchester matched filter via cumulative-sum differences.
  3. Quantize: threshold at zero → binary bit per sample.
  4. Search for preamble bits, sampled once per symbol_length positions.
  5. Slice out n_symbols bits at symbol_length intervals.

R900 uses a separate 6-symbol filter; see r900.py.
"""

from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Magnitude lookup table — matches rtlamr's NewMagLUT exactly:
#   lut[i] = ((127.5 - i) / 127.5)^2
# The Execute function sums lut[I] + lut[Q] (squared magnitude, no sqrt).
# ---------------------------------------------------------------------------
_lut = np.array(
    [((127.5 - i) / 127.5) ** 2 for i in range(256)], dtype=np.float64
)


def magnitude(raw: bytes | np.ndarray) -> np.ndarray:
    """Convert raw RTL-SDR IQ bytes to squared-magnitude array.

    Parameters
    ----------
    raw:
        Interleaved uint8 IQ bytes [I0, Q0, I1, Q1, ...].  Length must be even.

    Returns
    -------
    float64 array, length = len(raw) // 2.
    """
    samples = np.frombuffer(raw, dtype=np.uint8) if not isinstance(raw, np.ndarray) else raw
    return _lut[samples[0::2]] + _lut[samples[1::2]]


# ---------------------------------------------------------------------------
# Manchester matched filter  (rtlamr Decoder.Filter)
#
# For each position i, computes:
#   f[i] = sum(mag[i : i+chip]) - sum(mag[i+chip : i+symbol])
#
# This equals the difference of the two half-chips: positive means the first
# chip was higher (bit = 1), negative means the second chip was higher (bit = 0).
# Implemented via cumulative sum for O(n) complexity.
# ---------------------------------------------------------------------------

def filter_manchester(mag: np.ndarray, chip_length: int) -> np.ndarray:
    """Apply Manchester matched filter, returning a binary (0/1) array.

    Output length = len(mag) - 2*chip_length + 1.
    """
    symbol_length = chip_length * 2
    csum = np.empty(len(mag) + 1, dtype=np.float64)
    csum[0] = 0.0
    np.cumsum(mag, out=csum[1:])

    n = len(mag) - symbol_length + 1
    i = np.arange(n)
    # f[i] = (csum[i+chip] - csum[i]) - (csum[i+symbol] - csum[i+chip])
    f = (csum[i + chip_length] - csum[i]) - (csum[i + symbol_length] - csum[i + chip_length])
    return (f >= 0).astype(np.uint8)


# ---------------------------------------------------------------------------
# Preamble search  (rtlamr Decoder.Search, simplified)
#
# The preamble pattern is compared against bits[start + i*symbol_length]
# for i in 0 .. len(preamble)-1.  Returns all starting positions.
# ---------------------------------------------------------------------------

def search(bits: np.ndarray, preamble: np.ndarray, symbol_length: int) -> list[int]:
    """Find all offsets where *preamble* matches *bits* at symbol_length steps."""
    plen = len(preamble)
    n = len(bits)
    required = plen * symbol_length
    if n < required:
        return []

    offsets: list[int] = []
    steps = np.arange(plen) * symbol_length

    for start in range(n - required + 1):
        if np.all(bits[start + steps] == preamble):
            offsets.append(start)
    return offsets


# ---------------------------------------------------------------------------
# Packet slicer  (rtlamr Decoder.Slice)
#
# Extracts n_symbols bits from the quantized array, one per symbol_length
# samples, starting at preamble_start.  Includes the preamble bits.
# ---------------------------------------------------------------------------

def slice_packet(
    bits: np.ndarray,
    preamble_start: int,
    n_symbols: int,
    symbol_length: int,
) -> np.ndarray | None:
    """Extract n_symbols bits at symbol_length intervals starting at preamble_start.

    Returns None if there is not enough data.
    """
    indices = preamble_start + np.arange(n_symbols) * symbol_length
    if indices[-1] >= len(bits):
        return None
    return bits[indices]


# ---------------------------------------------------------------------------
# Bit packing helpers
# ---------------------------------------------------------------------------

def bits_to_int(bits: np.ndarray) -> int:
    """Convert uint8 bit array (MSB-first) to an integer."""
    result = 0
    for b in bits:
        result = (result << 1) | int(b)
    return result


def pack_bits(bits: np.ndarray) -> bytes:
    """Pack uint8 bit array (MSB-first) into bytes, padding with zeros."""
    pad = (8 - len(bits) % 8) % 8
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    return np.packbits(bits, bitorder="big").tobytes()
