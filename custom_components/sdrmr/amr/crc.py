"""
CRC helpers ported from github.com/bemasher/rtlamr (AGPL-3.0).

SCM  uses BCH  CRC-16: init=0x0000, poly=0x6F63, residue=0x0000
SCM+ uses CCITT CRC-16: init=0xFFFF, poly=0x1021, residue=0x1D0F

In both cases rtlamr runs the CRC over the data INCLUDING the stored checksum
bytes at the end.  A valid packet produces the stated residue value.
"""

from __future__ import annotations


def _build_table(poly: int) -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
        table.append(crc)
    return table


_BCH_TABLE = _build_table(0x6F63)
_CCITT_TABLE = _build_table(0x1021)


def crc16_bcch(data: bytes, init: int = 0) -> int:
    """CRC-16 with polynomial 0x6F63 (used by SCM)."""
    crc = init
    for byte in data:
        crc = ((crc << 8) ^ _BCH_TABLE[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
    return crc


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT with polynomial 0x1021 (used by SCM+)."""
    crc = init
    for byte in data:
        crc = ((crc << 8) ^ _CCITT_TABLE[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
    return crc
