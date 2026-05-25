"""
SCM (Standard Consumption Message) decoder.

Ported from github.com/bemasher/rtlamr scm/scm.go (AGPL-3.0).

Protocol parameters:
  Center frequency : 912,600,155 Hz
  Data rate        : 32,768 symbols/s
  Chip length      : sample_rate // data_rate  (e.g. 4 at 131,072 sps)
  Preamble         : "111110010101001100000"  (21 bits)
  Packet symbols   : 96

Bit field layout of the 96-bit packet (bit 0 = start of preamble):
  [0:21]   preamble "111110010101001100000"
  [21:23]  ERT ID high 2 bits
  [23:24]  reserved
  [24:26]  TamperPhy (2 bits)
  [26:30]  ERTType   (4 bits)
  [30:32]  TamperEnc (2 bits)
  [32:56]  Consumption (24 bits)
  [56:80]  ERT ID low 24 bits
  [80:96]  CRC-16/BCH (poly=0x6F63)

ERT ID = bits[21:23] || bits[56:80]  (concatenated = 26-bit value)

CRC check: crc16_bcch(packet_bytes[2:12]) == 0
  (the CRC covers bytes 2-11 inclusive, which is bits 16-95)
"""

from __future__ import annotations

import numpy as np

from .crc import crc16_bcch
from .demod import (
    bits_to_int,
    filter_manchester,
    magnitude,
    pack_bits,
    search,
    slice_packet,
)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

SCM_CENTER_FREQ = 912_600_155
SCM_DATA_RATE = 32_768

_PREAMBLE = np.array([int(b) for b in "111110010101001100000"], dtype=np.uint8)
_PREAMBLE_LEN = len(_PREAMBLE)   # 21
_PACKET_SYMBOLS = 96             # includes preamble


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def _parse(symbols: np.ndarray) -> dict | None:
    """Parse a 96-symbol SCM packet and validate BCH checksum.

    *symbols* is a uint8 array of exactly 96 bits (0/1), starting from
    the first preamble bit.
    """
    if len(symbols) < _PACKET_SYMBOLS:
        return None

    # Pack into 12 bytes (96 bits)
    data = pack_bits(symbols[:_PACKET_SYMBOLS])
    if len(data) < 12:
        return None

    # CRC check: bytes 2..11 (bits 16-95, including the 2 stored CRC bytes)
    # A valid packet gives residue 0.
    if crc16_bcch(data[2:12]) != 0:
        return None

    b = symbols[:_PACKET_SYMBOLS]

    # ERT ID = bits[21:23] concatenated with bits[56:80]
    ert_id = (bits_to_int(b[21:23]) << 24) | bits_to_int(b[56:80])

    # Bail on meter ID 0 (same check as rtlamr)
    if ert_id == 0:
        return None

    ert_type = bits_to_int(b[26:30])
    tamper_phy = bits_to_int(b[24:26])
    tamper_enc = bits_to_int(b[30:32])
    consumption = bits_to_int(b[32:56])

    return {
        "msg_type": "SCM",
        "meter_id": ert_id,
        "endpoint_type": ert_type,
        "consumption": consumption,
        "tamper_phy": tamper_phy,
        "tamper_enc": tamper_enc,
    }


def decode_block(raw: bytes, sample_rate: int) -> list[dict]:
    """Decode one block of raw RTL-SDR IQ bytes, returning SCM readings.

    Parameters
    ----------
    raw:
        Interleaved uint8 IQ bytes from rtl_tcp.
    sample_rate:
        SDR sample rate in Hz (must be an integer multiple of SCM_DATA_RATE).
    """
    chip_length = sample_rate // SCM_DATA_RATE
    symbol_length = chip_length * 2

    mag = magnitude(raw)
    bits = filter_manchester(mag, chip_length)

    results: list[dict] = []
    seen: set[str] = set()

    for start in search(bits, _PREAMBLE, symbol_length):
        symbols = slice_packet(bits, start, _PACKET_SYMBOLS, symbol_length)
        if symbols is None:
            continue
        key = symbols.tobytes()
        if key in seen:
            continue
        seen.add(key)
        reading = _parse(symbols)
        if reading is not None:
            results.append(reading)

    return results
