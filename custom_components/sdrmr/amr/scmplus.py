"""
SCM+ (Standard Consumption Message Plus) decoder.

Ported from github.com/bemasher/rtlamr scmplus/scmplus.go (AGPL-3.0).

Protocol parameters:
  Center frequency : 912,600,155 Hz  (same as SCM)
  Data rate        : 32,768 symbols/s
  Preamble         : "0001011010100011"  (16 bits)
  Packet symbols   : 128  (16 × 8)

Byte layout of the 16-byte (128-bit) packet:
  bytes  0-1   FrameSync    uint16
  byte   2     ProtocolID   uint8   (must be 0x1E)
  byte   3     EndpointType uint8
  bytes  4-7   EndpointID   uint32  (must be non-zero)
  bytes  8-11  Consumption  uint32
  bytes 12-13  Tamper       uint16
  bytes 14-15  PacketCRC    uint16

CRC check: crc16_ccitt(packet_bytes[2:]) == 0x1D0F
  (CCITT residue check; input is 14 bytes including the 2 stored CRC bytes)
"""

from __future__ import annotations

import struct

import numpy as np

from .crc import crc16_ccitt
from .demod import (
    filter_manchester,
    magnitude,
    pack_bits,
    search,
    slice_packet,
)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

SCMPLUS_CENTER_FREQ = 912_600_155
SCMPLUS_DATA_RATE = 32_768
_CCITT_RESIDUE = 0x1D0F

_PREAMBLE = np.array([int(b) for b in "0001011010100011"], dtype=np.uint8)
_PREAMBLE_LEN = len(_PREAMBLE)   # 16
_PACKET_SYMBOLS = 128            # includes preamble


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def _parse(symbols: np.ndarray) -> dict | None:
    """Parse a 128-symbol SCM+ packet and validate CCITT checksum.

    *symbols* is a uint8 bit array of exactly 128 bits (0/1).
    """
    if len(symbols) < _PACKET_SYMBOLS:
        return None

    # Pack 128 bits → 16 bytes
    data = pack_bits(symbols[:_PACKET_SYMBOLS])
    if len(data) < 16:
        return None

    # CRC check: bytes 2..15 (14 bytes, including 2 stored CRC bytes).
    # A valid packet gives CCITT residue 0x1D0F.
    if crc16_ccitt(data[2:]) != _CCITT_RESIDUE:
        return None

    # Unpack the big-endian struct
    frame_sync, protocol_id, endpoint_type, endpoint_id, consumption, tamper, packet_crc = (
        struct.unpack(">HBBIIHI", data)
    )

    # Validate ProtocolID and EndpointID (same checks as rtlamr)
    if protocol_id != 0x1E or endpoint_id == 0:
        return None

    return {
        "msg_type": "SCM+",
        "meter_id": endpoint_id,
        "endpoint_type": endpoint_type,
        "consumption": consumption,
        "tamper": tamper,
        "frame_sync": frame_sync,
    }


def decode_block(raw: bytes, sample_rate: int) -> list[dict]:
    """Decode one block of raw RTL-SDR IQ bytes, returning SCM+ readings.

    Parameters
    ----------
    raw:
        Interleaved uint8 IQ bytes from rtl_tcp.
    sample_rate:
        SDR sample rate in Hz (must be an integer multiple of SCMPLUS_DATA_RATE).
    """
    chip_length = sample_rate // SCMPLUS_DATA_RATE
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
