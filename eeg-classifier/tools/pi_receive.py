#!/usr/bin/env python3
"""EDF1 link: receive .edf snippets from the headset (laptop simulator or ESP32).

VENDORED from the headset-link tree (neurograsp/headset-link/pi_receive.py) so the
classifier repo is self-contained on the Pi. headset-link/ is the SOURCE OF TRUTH
for the wire frame (pinned by its tests/test_edf_link.py) -- if the frame ever
changes there, re-copy this file. The frame is also spoken by the ESP32 firmware
(neurograsp/headset-link/firmware/esp32_headset/esp32_headset.ino) and the laptop simulator
(headset-link/host_send.py).

    "EDF1" | class_id u8 | length u32 little-endian | <length bytes of .edf>

This module is used two ways:
  * as a library -- headset_daemon.py imports its frame codec + transports so the
    wire format has ONE definition on the Pi side; and
  * standalone -- the original subprocess-per-snippet receiver (writes each
    snippet to a file and runs a --cmd). The persistent daemon is preferred
    (tools/headset_daemon.py) because it loads the model once; this standalone
    path re-spawns the classifier per press. Kept for parity with headset-link/.

Transports (both live here; the daemon reuses them):
  * TCP  -- the Pi LISTENS, the laptop simulator CONNECTS (current path).
  * RFCOMM/SPP -- the Pi CONNECTS to the ESP32's Bluetooth (future headset).

Standalone usage:
    # laptop simulator over TCP (Pi is the server):
    python tools/pi_receive.py --tcp-listen 5005 --cmd 'python inference.py --file {edf}'
    # future ESP32 over Bluetooth:
    python tools/pi_receive.py --mac AA:BB:CC:DD:EE:FF --cmd 'python inference.py --file {edf}'
"""

from __future__ import annotations

import argparse
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

MAGIC = b"EDF1"
_HEADER = struct.Struct("<4sBI")        # 4 + 1 + 4 = 9 bytes, no padding
HEADER_SIZE = _HEADER.size
MAX_SNIPPET = 8 << 20                   # refuse absurd lengths from a corrupt link


def build_header(class_id: int, length: int) -> bytes:
    return _HEADER.pack(MAGIC, class_id, length)


def parse_header(buf: bytes) -> tuple[int, int]:
    """Return ``(class_id, length)`` or raise ``ValueError``."""
    if len(buf) < HEADER_SIZE:
        raise ValueError(f"header needs {HEADER_SIZE} bytes, got {len(buf)}")
    magic, class_id, length = _HEADER.unpack(buf[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}, expected {MAGIC!r}")
    if not 0 < length <= MAX_SNIPPET:
        raise ValueError(f"implausible snippet length {length}")
    return class_id, length


def recv_exactly(sock: socket.socket, n: int) -> bytes:
    chunks, remaining = [], n
    while remaining:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise ConnectionError(f"headset closed after {n - remaining}/{n} bytes")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def open_rfcomm(mac: str, channel: int) -> socket.socket:
    """Dial the ESP32's SPP service. The board is the server; the Pi connects."""
    if not hasattr(socket, "AF_BLUETOOTH"):
        raise SystemExit("AF_BLUETOOTH is Linux-only. On a Mac, test with --tcp-listen.")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.connect((mac, channel))
    return sock


def open_tcp(port: int) -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    try:
        conn, addr = srv.accept()
    finally:
        srv.close()
    print(f"[rx] headset connected from {addr[0]}:{addr[1]}")
    return conn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--mac", help="ESP32 Bluetooth address (SPP)")
    src.add_argument("--tcp-listen", type=int, metavar="PORT",
                     help="accept a TCP connection instead (laptop simulator)")
    ap.add_argument("--channel", type=int, default=1, help="RFCOMM channel (default 1)")
    ap.add_argument("--outdir", type=Path, default=Path("/tmp"),
                    help="where snippets are written (default /tmp)")
    ap.add_argument("--cmd", default=None,
                    help="shell command to run per snippet; {edf} is the file path")
    ap.add_argument("--cwd", type=Path, default=None, help="working directory for --cmd")
    ap.add_argument("--once", action="store_true", help="handle one snippet and exit")
    args = ap.parse_args(argv)

    args.outdir.mkdir(parents=True, exist_ok=True)

    try:
        while True:                       # outer loop: survive a headset reboot
            sock = (open_tcp(args.tcp_listen) if args.tcp_listen
                    else open_rfcomm(args.mac, args.channel))
            if args.mac:
                print(f"[rx] connected to {args.mac} on RFCOMM channel {args.channel}")
            print("[rx] waiting for snippets ...")
            try:
                # The length prefix is what lets one open link carry many presses.
                while True:
                    class_id, length = parse_header(recv_exactly(sock, HEADER_SIZE))
                    data = recv_exactly(sock, length)

                    path = args.outdir / f"snippet{class_id}.edf"
                    tmp = path.with_suffix(".part")
                    tmp.write_bytes(data)
                    tmp.replace(path)      # never hand a half-written file to the model
                    print(f"[rx] class {class_id}: {length:,} B -> {path}")

                    if args.cmd:
                        cmd = args.cmd.format(edf=str(path))
                        print(f"[rx] $ {cmd}")
                        subprocess.run(cmd, shell=True, cwd=args.cwd)
                    if args.once:
                        return 0
            except ConnectionError as exc:
                print(f"[rx] link closed: {exc}")
            except ValueError as exc:
                print(f"[rx] bad frame, dropping link: {exc}", file=sys.stderr)
            finally:
                sock.close()
            if args.once:
                return 1
            print("[rx] reconnecting ...")
            if args.mac:
                time.sleep(2)   # the board may still be rebooting; don't spin
    except KeyboardInterrupt:
        print("\n[rx] stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
