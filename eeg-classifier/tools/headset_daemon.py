#!/usr/bin/env python3
"""Persistent headset link: EDF snippets in (Bluetooth/TCP) -> hand commands out (UART).

One long-lived process on the Raspberry Pi that ties the two halves together:

    headset simulator (laptop)  --EDF1 frame over TCP-->   \
                                                            +--> headset_daemon.py --Contract A over UART--> hand ESP32
    real headset (ESP32)        --EDF1 frame over BT/SPP--> /

Why a daemon and not `pi_receive.py --cmd 'python inference.py --file {edf}'`?
Spawning inference.py per button press reloads mne + sklearn + the DTW model
every time (~7 s on a laptop, worse on a Pi). This process loads the model and
opens the hand's serial port ONCE, then classifies each snippet as it arrives --
so every press after the first responds immediately, and the `rest` heartbeat
keeps flowing between presses so the firmware's 3 s fail-safe never trips.

It does NOT touch the model/feature/training pipeline: it reuses inference.py's
own helpers (load_predictor, stream_file, SerialSender) so the classification
path is byte-for-byte the same as `inference.py --file`. The EDF1 wire frame is
reused from pi_receive.py (one definition on the Pi side).

Current path (headset simulator on a laptop -> the Pi is the TCP server):
    # on the Pi:
    python tools/headset_daemon.py --tcp-listen 5005
    # on the laptop (drives one EDF per artifact; reference simulator):
    python host_send.py firmware/esp32_headset/data/s0.edf --host <pi-ip> --port 5005

Future path (real ESP32 headset over Bluetooth -> the Pi dials the board's SPP):
    python tools/headset_daemon.py --mac AA:BB:CC:DD:EE:FF

Bench / no hand attached: add --no-serial (labels printed, never opens a port).
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

# tools/ holds pi_receive (the EDF1 frame codec); the repo root holds inference + eeg_bci.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HERE))

import inference                              # noqa: E402  (reused, not modified)
from eeg_bci import config as cfg            # noqa: E402
from pi_receive import (                     # noqa: E402  EDF1 frame codec + transports
    HEADER_SIZE, open_rfcomm, open_tcp, parse_header, recv_exactly,
)

# How often we wake while idle to consider sending a heartbeat. Must be well
# under cfg.REST_HEARTBEAT_SEC so the heartbeat fires on time between presses.
HEARTBEAT_POLL_SEC = 0.4
# A single snippet's bytes arrive in well under this once its header lands; a
# longer stall means a broken link, so we drop and wait for a reconnect.
PAYLOAD_TIMEOUT_SEC = 30.0
RECONNECT_DELAY_SEC = 2.0


def _read_frame(sock: socket.socket, sender) -> tuple[int, bytes] | None:
    """Read one EDF1 frame, heartbeating while idle. ``None`` if the link closed.

    Between frames (waiting for the next press) we poll with a short timeout and
    resend ``rest`` on schedule. Once a header lands, the payload is read with a
    blocking timeout -- a snippet arrives fast, and we do not want a heartbeat to
    interleave mid-file.
    """
    sock.settimeout(HEARTBEAT_POLL_SEC)
    buf = b""
    while len(buf) < HEADER_SIZE:
        try:
            chunk = sock.recv(HEADER_SIZE - len(buf))
        except socket.timeout:
            if not buf:                    # only heartbeat at a frame boundary
                sender.maybe_heartbeat()
            continue
        if not chunk:
            return None                    # peer closed cleanly
        buf += chunk
    class_id, length = parse_header(buf)
    sock.settimeout(PAYLOAD_TIMEOUT_SEC)
    return class_id, recv_exactly(sock, length)


def _classify_snippet(path: Path, predictor, sender, *, quiet: bool) -> None:
    """Run the exact inference path on one received snippet; never crash the daemon."""
    try:
        inference.stream_file(path, predictor, sender, quiet=quiet)
    except Exception as exc:               # noqa: BLE001 - a bad snippet must not kill the link
        print(f"[daemon] classify failed for {path.name}: {type(exc).__name__}: {exc}",
              file=sys.stderr)


def serve(args, predictor, sender) -> None:
    """Accept connections and classify snippets until interrupted."""
    args.outdir.mkdir(parents=True, exist_ok=True)
    while True:                            # reconnect loop: survive a headset reboot
        try:
            sock = (open_tcp(args.tcp_listen) if args.tcp_listen
                    else open_rfcomm(args.mac, args.channel))
        except OSError as exc:
            print(f"[daemon] connect failed ({exc}); retrying in {RECONNECT_DELAY_SEC:g}s")
            time.sleep(RECONNECT_DELAY_SEC)
            continue
        if args.mac:
            print(f"[daemon] connected to {args.mac} on RFCOMM channel {args.channel}")
        print("[daemon] link up -- waiting for EDF snippets (rest heartbeat active)")
        try:
            while True:
                frame = _read_frame(sock, sender)
                if frame is None:
                    print("[daemon] link closed by peer")
                    break
                class_id, data = frame
                path = args.outdir / f"snippet{class_id}.edf"
                tmp = path.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(path)          # never hand a half-written file to the model
                print(f"[daemon] class {class_id}: {len(data):,} B -> {path}")
                _classify_snippet(path, predictor, sender, quiet=args.quiet)
                if args.once:
                    return
        except (OSError, ConnectionError, ValueError) as exc:
            print(f"[daemon] link error: {type(exc).__name__}: {exc}")
        finally:
            try:
                sock.close()
            except OSError:
                pass
        if args.once:
            return
        print(f"[daemon] reconnecting in {RECONNECT_DELAY_SEC:g}s ...")
        time.sleep(RECONNECT_DELAY_SEC)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--tcp-listen", type=int, metavar="PORT",
                     help="listen for the laptop simulator on this TCP port (current path)")
    src.add_argument("--mac", help="dial the ESP32 headset's Bluetooth SPP address (future)")
    p.add_argument("--channel", type=int, default=1, help="RFCOMM channel (default 1)")
    p.add_argument("--outdir", type=Path, default=Path("/tmp"),
                   help="where received snippets are written (default /tmp)")
    # --- classifier + hand-serial options, mirroring inference.py ---
    p.add_argument("--model", choices=("dtw", "hybrid", "hierarchical", "flat"),
                   default="dtw", help="classifier (default dtw; best 91.7%% LOSO)")
    p.add_argument("--port", default=cfg.SERIAL_PORT,
                   help=f"hand ESP32 UART port (default {cfg.SERIAL_PORT}; or $EEG_SERIAL_PORT)")
    p.add_argument("--no-serial", action="store_true",
                   help="do not open the hand port; print the label stream instead")
    p.add_argument("--quiet", action="store_true",
                   help="show only confirmed commands per snippet")
    p.add_argument("--threshold", type=float, default=cfg.CONF_THRESH,
                   help=f"confidence threshold (default {cfg.CONF_THRESH})")
    p.add_argument("--activity", type=float, default=cfg.ACTIVITY_THRESHOLD,
                   help=f"activity-gate µV threshold (default {cfg.ACTIVITY_THRESHOLD:g})")
    p.add_argument("--once", action="store_true",
                   help="handle a single snippet then exit (for testing)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)

    # Same runtime overrides as inference.main so every helper sees one source.
    cfg.CONF_THRESH = args.threshold
    cfg.ACTIVITY_THRESHOLD = args.activity

    # Load the model and open the hand's serial port ONCE, up front.
    predictor = inference.load_predictor(args.model)
    sender = inference.SerialSender(args.port, enabled=not args.no_serial)
    where = f"TCP :{args.tcp_listen}" if args.tcp_listen else f"BT {args.mac}"
    print(f"[daemon] ready: headset via {where}  ->  hand via "
          f"{'SIM' if args.no_serial else args.port}\n")
    try:
        serve(args, predictor, sender)
    except KeyboardInterrupt:
        print("\n[daemon] stopped")
    finally:
        sender.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
