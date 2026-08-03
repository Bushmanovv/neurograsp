#!/usr/bin/env python3
"""Receive .edf snippets from the headset and hand each to this Pi's classifier.

Standalone and stdlib-only: copy this one file next to your existing project. It
does not import the model, it does not preprocess anything. It reads a frame off
the link, writes the bytes to a .edf, and runs whatever command you give it. The
payload is a plain EDF, so your pipeline needs no changes.

    in :  "EDF1" | class_id u8 | length u32 little-endian | <length bytes of .edf>
    out:  "RES1" | length u32 | <length bytes of JSON>      (the verdict)

The sender is either the laptop dashboard over TCP, or the ESP32 over Bluetooth.

TCP — the laptop runs the dashboard and connects here:

    python pi_receive.py --tcp-listen 5005 \\
        --cmd 'python inference.py --file {edf}' --cwd ~/neurograsp/eeg-classifier

Bluetooth — pair the board once, then dial it:

    bluetoothctl            # scan on; pair <ESP_MAC>; trust <ESP_MAC>
    python pi_receive.py --mac AA:BB:CC:DD:EE:FF --no-reply \\
        --cmd 'python inference.py --file {edf}' --cwd ~/neurograsp/eeg-classifier

The reply carries the exit status and output of --cmd back to whoever sent the
snippet, which is how the dashboard shows what the model decided. The ESP32
firmware never reads it, so --no-reply keeps those bytes off the SPP link.
"""

from __future__ import annotations

import argparse
import json
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

RESULT_MAGIC = b"RES1"
_RESULT = struct.Struct("<4sI")         # 4 + 4 = 8 bytes
RESULT_HEADER_SIZE = _RESULT.size
MAX_OUTPUT = 8000                       # keep a runaway --cmd from flooding the link


def build_header(class_id: int, length: int) -> bytes:
    return _HEADER.pack(MAGIC, class_id, length)


def build_result(verdict: dict) -> bytes:
    """Length-prefixed JSON: the link is a stream, so the reply needs a frame too."""
    body = json.dumps(verdict).encode()
    return _RESULT.pack(RESULT_MAGIC, len(body)) + body


def parse_result_header(buf: bytes) -> int:
    """Return the JSON body length, or raise ``ValueError``."""
    if len(buf) < RESULT_HEADER_SIZE:
        raise ValueError(f"result header needs {RESULT_HEADER_SIZE} bytes, got {len(buf)}")
    magic, length = _RESULT.unpack(buf[:RESULT_HEADER_SIZE])
    if magic != RESULT_MAGIC:
        raise ValueError(f"bad result magic {magic!r}, expected {RESULT_MAGIC!r}")
    if length > MAX_SNIPPET:
        raise ValueError(f"implausible result length {length}")
    return length


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


def run_command(cmd: str, edf: Path, cwd: Path | None) -> dict:
    """Run the classifier on one snippet and collect what it said.

    The output is teed rather than captured: the Pi's own console keeps its live
    feed, and a copy goes back to the dashboard. Only the tail is kept -- a
    verbose model would otherwise push megabytes at a link sized for 43 KB.
    """
    shell_cmd = cmd.format(edf=str(edf))
    print(f"[rx] $ {shell_cmd}", flush=True)

    t0 = time.monotonic()
    proc = subprocess.Popen(shell_cmd, shell=True, cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    chunks: list[str] = []
    for line in proc.stdout:            # type: ignore[union-attr]
        print(line, end="", flush=True)
        chunks.append(line)
    returncode = proc.wait()
    elapsed = time.monotonic() - t0

    output = "".join(chunks)
    if len(output) > MAX_OUTPUT:
        output = "... (truncated)\n" + output[-MAX_OUTPUT:]
    print(f"[rx] exit {returncode} in {elapsed:.1f}s", flush=True)
    return {"cmd": shell_cmd, "returncode": returncode,
            "seconds": round(elapsed, 2), "output": output}


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
                     help="accept a TCP connection instead (bench testing)")
    ap.add_argument("--channel", type=int, default=1, help="RFCOMM channel (default 1)")
    ap.add_argument("--outdir", type=Path, default=Path("/tmp"),
                    help="where snippets are written (default /tmp)")
    ap.add_argument("--cmd", default=None,
                    help="shell command to run per snippet; {edf} is the file path")
    ap.add_argument("--cwd", type=Path, default=None, help="working directory for --cmd")
    ap.add_argument("--once", action="store_true", help="handle one snippet and exit")
    ap.add_argument("--no-reply", action="store_true",
                    help="do not send the verdict back (the ESP32 firmware never reads it)")
    args = ap.parse_args(argv)

    # Redirected to a file or a pipe (nohup, systemd, `| tee`), stdout is block-
    # buffered and the log stays empty for ages. This is a progress log; line-buffer it.
    sys.stdout.reconfigure(line_buffering=True)

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
                        verdict = run_command(args.cmd, path, args.cwd)
                    else:
                        verdict = {"cmd": None, "returncode": None,
                                   "seconds": 0.0, "output": ""}
                    verdict |= {"class_id": class_id, "bytes": length, "file": str(path)}

                    # The dashboard is waiting on this. Send it before looping back
                    # to read the next frame, or the page sits on a dead timeout.
                    # Best-effort: a sender that hangs up without reading its
                    # verdict (host_send.py, the firmware) is still a correct
                    # sender, and the snippet has already been handed to the model.
                    if not args.no_reply:
                        try:
                            sock.sendall(build_result(verdict))
                        except OSError as exc:
                            print(f"[rx] verdict not delivered ({exc}); snippet was "
                                  f"processed", file=sys.stderr)
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
