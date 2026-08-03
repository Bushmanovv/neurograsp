#!/usr/bin/env python3
"""The headset dashboard, running on this laptop instead of on the ESP32.

The board is out of the loop. This process is the headset: five buttons, each one
sending a 5 s `.edf` snippet over TCP to the Raspberry Pi, which writes the bytes
to a file and runs its existing pipeline. The frame is the one the firmware
speaks, so *the Pi does not know the difference*:

    "EDF1" | class_id u8 | length u32 | <length bytes of .edf>       laptop -> Pi
    "RES1" | length u32   | <JSON: exit code, output>                Pi -> laptop

Nothing here classifies, and nothing here imports mne or the model. The Pi owns
the model; this page shows the snippet it sent and the verdict that came back.

    # on the Pi
    python pi_receive.py --tcp-listen 5005 \\
        --cmd 'python inference.py --file {edf}' --cwd ~/neurograsp/eeg-classifier

    # on this laptop
    python dashboard.py --host raspberrypi.local

Then open http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

import pi_receive
from edf import read_edf

HERE = Path(__file__).parent
PAGE = HERE / "dashboard" / "index.html"
DATA_DIR = HERE / "firmware" / "esp32_headset" / "data"

# 200 Hz -> 40 Hz for the browser; never plot 200 Hz.
DECIMATE = 5

# The four channels the Pi's activity gate reads (config.FRONTAL_CH + TEMPORAL_CH).
# Named here only so the plot can accent them; the gate itself runs on the Pi.
GATE_CHANNELS = ["Fp1", "Fp2", "T3", "T4"]

CHUNK = 1024              # the firmware's LittleFS read size; keep the pacing honest
CONNECT_TIMEOUT = 4.0
POLL_SECONDS = 2.0

_subs: list[queue.Queue] = []
_subs_lock = threading.Lock()
_busy = threading.Lock()  # one press at a time, exactly like the board

CLIPS: list[dict] = []    # manifest entries, each with a decoded + decimated trace


def publish(event: str, data: dict) -> None:
    payload = (event, json.dumps(data))
    with _subs_lock:
        for q in _subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


# --------------------------------------------------------------------------- #
# The link to the Pi
# --------------------------------------------------------------------------- #
class PiLink:
    """One TCP connection, held open across presses -- what the board did on RFCOMM.

    The length prefix is what lets a single link carry every button press, so
    reconnecting per press would be a lie about the protocol. It redials whenever
    the Pi restarts.
    """

    def __init__(self, host: str, port: int, verdict_timeout: float) -> None:
        self.host, self.port = host, port
        self.verdict_timeout = verdict_timeout
        self._sock: socket.socket | None = None
        self._lock = threading.RLock()
        self.error: str | None = None

    @property
    def target(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def up(self) -> bool:
        return self._sock is not None

    def state(self) -> dict:
        return {"up": self.up, "target": self.target, "error": self.error}

    def connect(self) -> socket.socket:
        with self._lock:
            if self._sock is not None:
                return self._sock
            try:
                sock = socket.create_connection((self.host, self.port),
                                                timeout=CONNECT_TIMEOUT)
            except OSError as exc:
                self.error = f"{exc.strerror or exc}"
                raise
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock, self.error = sock, None
            return sock

    def drop(self, why: str | None = None) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
            self._sock, self.error = None, why

    def check(self) -> None:
        """Notice a Pi that went away while we were idle, without stealing a byte."""
        with self._lock:
            if self._sock is None:
                return
            try:
                if self._sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT) == b"":
                    self.drop("the Pi closed the link")   # EOF: receiver stopped
            except BlockingIOError:
                pass                                       # nothing pending: alive
            except OSError as exc:
                self.drop(f"{exc.strerror or exc}")

    def send(self, class_id: int, payload: bytes) -> None:
        """Put one snippet on the wire. Does *not* wait for the model."""
        with self._lock:
            sock = self.connect()
            try:
                sock.sendall(pi_receive.build_header(class_id, len(payload)))
                for i in range(0, len(payload), CHUNK):
                    sock.sendall(payload[i:i + CHUNK])
            except OSError as exc:
                self.drop(f"{exc.strerror or exc}")
                raise

    def read_verdict(self) -> dict | None:
        """Block for the Pi's verdict. Separate from send() so the page can say
        'delivered, now classifying' -- folding the two together would bill the
        model's thinking time as transfer time."""
        with self._lock:
            sock = self._sock
            if sock is None:
                return None
            return self._read_verdict(sock)

    def _read_verdict(self, sock: socket.socket) -> dict | None:
        sock.settimeout(self.verdict_timeout)
        try:
            head = self._recv_exactly(sock, pi_receive.RESULT_HEADER_SIZE)
            n = pi_receive.parse_result_header(head)
            return json.loads(self._recv_exactly(sock, n)) if n else None
        except (socket.timeout, TimeoutError):
            return None            # a receiver run with --no-reply. Snippet still landed.
        except (OSError, ConnectionError, ValueError) as exc:
            self.drop(f"{exc}")
            raise
        finally:
            if self._sock is not None:
                sock.settimeout(None)

    @staticmethod
    def _recv_exactly(sock: socket.socket, n: int) -> bytes:
        chunks, remaining = [], n
        while remaining:
            chunk = sock.recv(min(remaining, 65536))
            if not chunk:
                raise ConnectionError(f"the Pi closed after {n - remaining}/{n} bytes")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


LINK: PiLink
WANT_VERDICT = True


def monitor() -> None:
    """Keep the link up and the dot honest, so the page knows before you press."""
    was: dict | None = None
    while True:
        LINK.check()
        if not LINK.up:
            try:
                LINK.connect()
            except OSError:
                pass
        now = LINK.state()
        if now != was:
            publish("link", now)
            was = now
        time.sleep(POLL_SECONDS)


# --------------------------------------------------------------------------- #
# Press -> send -> verdict
# --------------------------------------------------------------------------- #
def send_clip(class_id: int) -> None:
    clip = next(c for c in CLIPS if c["class_id"] == class_id)

    publish("clip", {
        "class_id": class_id, "class_name": clip["class_name"],
        "command_char": clip["command_char"], "action": clip["action"],
        "source": clip["source"], "t0_s": clip["t0_s"],
        "seconds": clip["seconds"], "sfreq": clip["sfreq"],
        "bytes": clip["bytes"], "file": clip["file"],
        "channels": clip["channels"], "autoscale": clip["autoscale"],
        "dt": clip["dt"], "trace": clip["trace"],
        "target": LINK.target,
    })

    t0 = time.monotonic()
    try:
        LINK.send(class_id, clip["payload"])
    except OSError as exc:
        publish("failed", {"message": f"could not reach the Pi at {LINK.target} "
                                      f"({exc.strerror or exc})"})
        publish("link", LINK.state())
        return
    elapsed = time.monotonic() - t0

    nbytes = pi_receive.HEADER_SIZE + clip["bytes"]
    publish("sent", {"bytes": nbytes, "ms": round(elapsed * 1000, 1),
                     "kbps": round(nbytes / max(elapsed, 1e-6) / 1024, 1)})

    if not WANT_VERDICT:
        publish("noreply", {"message": f"snippet delivered to {LINK.target}; "
                                       f"not waiting for a verdict (--no-verdict)"})
        return

    # The Pi is thinking now. That time is the model's, not the network's.
    try:
        verdict = LINK.read_verdict()
    except OSError as exc:
        publish("failed", {"message": f"link dropped while the Pi was classifying "
                                      f"({exc.strerror or exc})"})
        publish("link", LINK.state())
        return

    if verdict is None:
        publish("noreply", {"message": f"snippet delivered to {LINK.target}; the Pi's "
                                       f"receiver sent no verdict"})
        return
    publish("verdict", verdict)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    @property
    def route(self) -> str:
        """Path without the query string, so ``/?send=2`` still routes to ``/``."""
        return urlsplit(self.path).path

    def do_GET(self) -> None:
        if self.route in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.route == "/api/clips":
            self._json(200, {
                "clips": [{k: c[k] for k in
                           ("class_id", "class_name", "command_char", "action",
                            "seconds", "bytes", "source", "t0_s", "file")}
                          for c in CLIPS],
                "channels": CLIPS[0]["channels"],
                "gate_channels": GATE_CHANNELS,
                "link": LINK.state(),
                "want_verdict": WANT_VERDICT,
            })
        elif self.route == "/api/events":
            self._sse()
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if not self.route.startswith("/api/send/"):
            self._send(404, b"not found", "text/plain")
            return
        try:
            class_id = int(self.route.rsplit("/", 1)[1])
        except ValueError:
            self._json(400, {"error": "bad class id"})
            return
        if not any(c["class_id"] == class_id for c in CLIPS):
            self._json(404, {"error": "no such snippet"})
            return
        if not _busy.acquire(blocking=False):
            self._json(409, {"error": "a snippet is already in flight"})
            return

        def run() -> None:
            try:
                send_clip(class_id)
            finally:
                _busy.release()

        threading.Thread(target=run, daemon=True).start()
        self._json(202, {"ok": True})

    def _sse(self) -> None:
        q: queue.Queue = queue.Queue(maxsize=64)
        with _subs_lock:
            _subs.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(f"event: link\ndata: {json.dumps(LINK.state())}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    event, data = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")   # keep proxies/browsers awake
                    self.wfile.flush()
                    continue
                self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _subs_lock:
                if q in _subs:
                    _subs.remove(q)


# --------------------------------------------------------------------------- #
# Load the snippets once, at startup: a press is then just a socket write
# --------------------------------------------------------------------------- #
def load_clips(data_dir: Path) -> list[dict]:
    from scipy.signal import decimate

    manifest = json.loads((data_dir / "snippets.json").read_text())
    clips = []
    for entry in sorted(manifest, key=lambda e: e["class_id"]):
        path = data_dir / entry["file"]
        clip = read_edf(path)

        # Display-only conditioning. The Pi receives the file untouched.
        #  1. strip each channel's DC so the 19 lanes sit still
        #  2. decimate to the browser's rate through an anti-alias low-pass. Taking
        #     every Nth sample instead would fold the 50 Hz mains -- which carries
        #     ~92% of the power in these recordings -- onto |50 - 40| = 10 Hz and
        #     draw a clean rhythm that does not exist.
        centred = clip.uv - clip.uv.mean(axis=1, keepdims=True)
        disp = decimate(centred, DECIMATE, axis=1, ftype="fir", zero_phase=True)

        clips.append(entry | {
            "payload": clip.data,           # the exact bytes that go on the wire
            "bytes": len(clip.data),
            "channels": clip.electrodes,
            "sfreq": clip.sfreq,
            "seconds": round(clip.seconds, 3),
            "dt": DECIMATE / clip.sfreq,
            "autoscale": round(float(np.percentile(np.abs(disp), 99.5)), 1),
            "trace": [[round(float(x), 1) for x in row] for row in disp],
        })
    return clips


def main(argv=None) -> int:
    global CLIPS, LINK, WANT_VERDICT

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="raspberrypi.local",
                    help="the Pi, running pi_receive.py --tcp-listen")
    ap.add_argument("--port", type=int, default=5005,
                    help="the Pi's port (not 5000: macOS AirPlay Receiver owns it)")
    ap.add_argument("--http-port", type=int, default=8080, help="port for this dashboard")
    ap.add_argument("--data", type=Path, default=DATA_DIR,
                    help="directory holding snippets.json and s0..s4.edf")
    ap.add_argument("--verdict-timeout", type=float, default=60.0,
                    help="how long to wait for the Pi's classifier (seconds)")
    ap.add_argument("--no-verdict", action="store_true",
                    help="do not wait for a reply (a Pi running --no-reply)")
    args = ap.parse_args(argv)

    if not (args.data / "snippets.json").exists():
        print(f"error: {args.data / 'snippets.json'} missing. Run make_snippets.py first.",
              file=sys.stderr)
        return 2

    try:
        CLIPS = load_clips(args.data)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: could not load the snippets: {exc}", file=sys.stderr)
        return 2

    WANT_VERDICT = not args.no_verdict
    LINK = PiLink(args.host, args.port, args.verdict_timeout)
    threading.Thread(target=monitor, daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", args.http_port), Handler)
    srv.daemon_threads = True
    total = sum(c["bytes"] for c in CLIPS)
    print(f"headset dashboard on this laptop -- the ESP32 is not in the loop")
    print(f"  {len(CLIPS)} snippets, {len(CLIPS[0]['channels'])} channels, "
          f"{total / 1024:.0f} KiB loaded from {args.data}")
    print(f"  dashboard  ->  http://127.0.0.1:{args.http_port}")
    print(f"  the Pi     ->  {args.host}:{args.port}  (pi_receive.py --tcp-listen {args.port})")
    print("\nCtrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        LINK.drop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
