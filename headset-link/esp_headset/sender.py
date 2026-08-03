"""Headset side: stream one stored segment over the link.

This is the reference implementation of what the ESP32 firmware does. The board
cannot hold a segment in RAM (222.7 KiB against ~100-160 KB of free heap once
WiFi and Bluetooth are up), so it never loads one: it opens the file on
LittleFS, reads a chunk, writes the chunk to the link, repeats. This module
does the same thing with the same chunk size, which keeps the Python simulator
and the firmware exercising one protocol.

A chunk is a whole number of samples, so a chunk boundary never splits a sample.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import numpy as np

from . import protocol
from .protocol import Header
from .transport import Transport

CHUNK_SAMPLES = 20  # 20 * 19 ch * 2 B = 760 B; drop to 6 for a 244-byte BLE MTU


def read_segment_file(path: str | Path) -> tuple[Header, np.ndarray]:
    """Read a ``.bin`` produced by ``export_segments.py``."""
    buf = Path(path).read_bytes()
    return protocol.decode_segment(buf)


def play(
    transport: Transport,
    header: Header,
    counts: np.ndarray,
    *,
    chunk_samples: int = CHUNK_SAMPLES,
    realtime: bool = True,
    on_frame: Callable[[np.ndarray], None] | None = None,
) -> None:
    """Send one segment, paced at the true sample rate when ``realtime``.

    Args:
        header: Segment header, sent first.
        counts: ``(n_ch, n_samples)`` int16 digital counts.
        chunk_samples: Samples per link write.
        realtime: Pace playback at ``header.sfreq``; ``False`` sends flat out.
        on_frame: Called with each chunk ``(n_ch, chunk_samples)``. The firmware
            uses this hook to push a decimated copy to the dashboard WebSocket --
            never the full 200 Hz stream, which no browser needs.
    """
    transport.send(protocol.encode_header(header))

    period = chunk_samples / header.sfreq
    start = time.monotonic()
    for i, s in enumerate(range(0, header.n_samples, chunk_samples)):
        chunk = counts[:, s:s + chunk_samples]
        transport.send(protocol.encode_samples(chunk))
        if on_frame is not None:
            on_frame(chunk)
        if realtime:
            target = start + (i + 1) * period
            slack = target - time.monotonic()
            if slack > 0:
                time.sleep(slack)


def play_file(transport: Transport, path: str | Path, **kwargs) -> Header:
    """Convenience: read a segment file and play it."""
    header, counts = read_segment_file(path)
    play(transport, header, counts, **kwargs)
    return header


def _main(argv=None) -> int:
    """Stand in for the ESP32 while the board is on the bench."""
    import argparse

    from .transport import tcp_connect

    ap = argparse.ArgumentParser(
        prog="python -m esp_headset.sender",
        description="Play one stored segment to the classifier (simulated ESP32).")
    ap.add_argument("segment", help="path to seg<N>.bin")
    ap.add_argument("--host", default="127.0.0.1", help="classifier host (the Pi)")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--chunk", type=int, default=CHUNK_SAMPLES, help="samples per write")
    ap.add_argument("--fast", action="store_true", help="skip real-time pacing")
    args = ap.parse_args(argv)

    with tcp_connect(args.host, args.port) as link:
        h = play_file(link, args.segment, chunk_samples=args.chunk, realtime=not args.fast)
    print(f"[tx] sent class_id={h.class_id} {h.seconds:.1f}s "
          f"({h.payload_nbytes:,} B) to {args.host}:{args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
