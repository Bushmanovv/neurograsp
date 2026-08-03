#!/usr/bin/env python3
"""Stand in for the ESP32: send a .edf snippet using the firmware's exact frame.

Lets you exercise the Pi end before the board is on the bench.

    python host_send.py firmware/esp32_headset/data/s2.edf --port 5005
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

from pi_receive import build_header

CHUNK = 1024  # the firmware's LittleFS read size


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("edf", type=Path, nargs="+", help="snippet(s) to send, one per press")
    ap.add_argument("--class-id", type=int, default=None,
                    help="defaults to the digit in s<N>.edf")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5005)
    args = ap.parse_args(argv)

    def class_of(path: Path) -> int:
        if args.class_id is not None:
            return args.class_id
        stem = path.stem
        if not (stem.startswith("s") and stem[1:].isdigit()):
            raise SystemExit(f"pass --class-id ({path.name} is not s<N>.edf)")
        return int(stem[1:])

    # One connection, many frames -- exactly how the firmware behaves across presses.
    with socket.create_connection((args.host, args.port), timeout=10) as sock:
        for path in args.edf:
            cid = class_of(path)
            payload = path.read_bytes()
            sock.sendall(build_header(cid, len(payload)))
            for i in range(0, len(payload), CHUNK):
                sock.sendall(payload[i:i + CHUNK])
            print(f"[tx] class {cid}: {len(payload):,} B of {path.name} "
                  f"-> {args.host}:{args.port}")
        input("[tx] press Enter to hang up ") if sys.stdin.isatty() else None
    return 0


if __name__ == "__main__":
    sys.exit(main())
