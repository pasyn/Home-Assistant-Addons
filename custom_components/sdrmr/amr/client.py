"""
Asyncio client for rtl_tcp.

rtl_tcp protocol:
  1. Client connects via TCP.
  2. Server sends a 12-byte "dongle info" header:
       b"RTL0" + tuner_type (uint32 BE) + tuner_gains (uint32 BE)
  3. Client sends 5-byte commands:
       [cmd_byte, param_b3, param_b2, param_b1, param_b0]
     Commands used:
       0x01  SET_FREQ       (Hz)
       0x02  SET_SAMPLE_RATE (Hz)
       0x08  SET_AGC_MODE   (1 = enabled)
  4. Server streams raw IQ bytes continuously (uint8 interleaved I/Q pairs).

The client tunes to the frequency required by the chosen protocol(s), reads
IQ data in fixed-size blocks, and dispatches each block to the appropriate
protocol decoder.  Decoded readings are yielded as dicts.
"""

from __future__ import annotations

import asyncio
import struct
from typing import AsyncGenerator

from . import scm, scmplus, r900

# Block size: must be an even number of bytes (each IQ pair = 2 bytes).
# 16384 IQ pairs = 32768 bytes.  At 262144 sps this is ~62 ms per block.
_BLOCK_BYTES = 32_768
_SAMPLE_RATE = 4 * 32_768   # 131,072 Hz — minimum that gives chip_length = 4

# SCM/SCM+ center frequency (R900 is slightly different; we handle both by
# scanning one frequency at a time when the user picks a specific msg_type).
_FREQ_SCM = scm.SCM_CENTER_FREQ
_FREQ_R900 = r900.R900_CENTER_FREQ


def _build_command(cmd: int, param: int) -> bytes:
    return struct.pack(">BI", cmd, param)


class SdrClient:
    """Manages a single rtl_tcp connection and streams decoded meter readings."""

    def __init__(self, host: str, port: int, msg_type: str = "scm") -> None:
        self.host = host
        self.port = port
        self.msg_type = msg_type.lower()

    # ------------------------------------------------------------------
    # Determine which decoders to run and which frequency to tune to
    # ------------------------------------------------------------------

    def _decoders(self):
        """Return list of (decode_fn, sample_rate) pairs for the configured msg_type."""
        mt = self.msg_type
        if mt == "scm":
            return [(scm.decode_block, _SAMPLE_RATE)]
        if mt in ("scm+", "scmplus"):
            return [(scmplus.decode_block, _SAMPLE_RATE)]
        if mt == "r900":
            return [(r900.decode_block, _SAMPLE_RATE)]
        if mt == "r900bcd":
            # R900BCD uses the same demodulation as R900
            return [(r900.decode_block, _SAMPLE_RATE)]
        if mt == "all":
            return [
                (scm.decode_block, _SAMPLE_RATE),
                (scmplus.decode_block, _SAMPLE_RATE),
                (r900.decode_block, _SAMPLE_RATE),
            ]
        # Default: SCM
        return [(scm.decode_block, _SAMPLE_RATE)]

    def _center_freq(self) -> int:
        mt = self.msg_type
        if mt in ("r900", "r900bcd"):
            return _FREQ_R900
        return _FREQ_SCM

    # ------------------------------------------------------------------
    # Async stream
    # ------------------------------------------------------------------

    async def stream(self, stop_event: asyncio.Event) -> AsyncGenerator[dict, None]:
        """Connect to rtl_tcp and yield decoded meter readings until stopped."""
        reader, writer = await asyncio.open_connection(self.host, self.port)

        try:
            # Read dongle info header (12 bytes)
            header = await asyncio.wait_for(reader.readexactly(12), timeout=5.0)
            if not header.startswith(b"RTL0"):
                raise ConnectionError(f"Unexpected rtl_tcp header: {header!r}")

            # Configure the dongle
            freq = self._center_freq()
            writer.write(_build_command(0x01, freq))           # SET_FREQ
            writer.write(_build_command(0x02, _SAMPLE_RATE))   # SET_SAMPLE_RATE
            writer.write(_build_command(0x08, 1))              # SET_AGC_MODE on
            await writer.drain()

            decoders = self._decoders()

            while not stop_event.is_set():
                raw = await asyncio.wait_for(
                    reader.readexactly(_BLOCK_BYTES), timeout=10.0
                )
                for decode_fn, sample_rate in decoders:
                    for reading in decode_fn(raw, sample_rate):
                        yield reading

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
