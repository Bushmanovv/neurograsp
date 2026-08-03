#!/usr/bin/env python3
"""The Pi side, resident: load the model once, hold the UART open, classify snippets.

This is what runs at boot on the RPi5. It speaks exactly the frames the dashboard
already sends, so nothing on the laptop changes:

    in : "EDF1" | class_id u8 | length u32 | <length bytes of .edf>
    out: "RES1" | length u32  | <JSON: exit code, output, confirmed commands>

Why not just `pi_receive.py --cmd 'python inference.py --file {edf}'`? Two reasons,
both fatal once the thing has to run unattended:

  * **The hand goes limp between presses.** The ESP32 hand firmware fail-safes if
    it does not see a Contract A line for 3 s, and `inference.py` only sends the
    `rest` heartbeat (``cfg.REST_HEARTBEAT_SEC`` = 1.2 s) while it is streaming a
    clip -- it opens the port, streams, and closes. A process that exits between
    button presses stops the heartbeat, so the fail-safe trips within 3 s of every
    press. A resident process keeps `rest` flowing while idle, which is what the
    contract actually asks for.
  * **Every press would re-pay the cold start.** Importing mne + sklearn and
    unpickling the DTW/Riemann model costs ~3 s on a laptop and far more on a Pi.
    Here it is paid once, at boot.

The inference path itself is not reimplemented: this calls `inference.stream_file`,
the same function the CLI calls, so what the Pi decides here is what it decides
there.

    python pi_service.py --project ~/neurograsp/eeg-classifier          # real UART
    python pi_service.py --project ~/neurograsp/eeg-classifier --no-serial
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

import pi_receive   # the frames, single-sourced

MAX_OUTPUT = 8000


class HttpSender:
    """Contract A over WiFi, for a hand that has no working USB/UART wire.

    Drop-in for `inference.SerialSender`: same three methods, so
    `inference.stream_file` cannot tell the difference and the inference path
    stays byte-for-byte the one the CLI runs. The label goes to `POST /api/cue`,
    which the firmware feeds to the same `applyLabel()` the wire fed -- mappings,
    the link indicator and the `rest` heartbeat all behave identically.

    The heartbeat rule is `SerialSender`'s, restated: resend `rest` only if
    REST_HEARTBEAT_SEC has passed since *any* send, so a fired command suppresses
    the next heartbeat rather than racing it.
    """

    def __init__(self, base_url: str, heartbeat_s: float, labels, rest_label: str,
                 timeout: float = 2.0, *, clock=time.monotonic) -> None:
        self.url = base_url.rstrip("/") + "/api/cue"
        self.heartbeat_s = heartbeat_s
        self.labels = set(labels)
        self.rest_label = rest_label
        self.timeout = timeout
        self._clock = clock
        self._last_send: float | None = None
        self.ser = object()          # truthy: pi_service's --require checks this

    def _post(self, label: str) -> None:
        import json as _json
        import urllib.request

        req = urllib.request.Request(
            self.url, method="POST",
            data=_json.dumps({"label": label}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            r.read()

    def send_label(self, label: str) -> None:
        if label not in self.labels:
            raise ValueError(f"{label!r} is not a Contract A label; the firmware "
                             f"would log and ignore it")
        try:
            self._post(label)
        except OSError as exc:
            # Never kill the run over one dropped packet: the next heartbeat (1.2 s)
            # re-arms the link, and the fail-safe holds the pose meanwhile.
            print(f"[wifi] {label}: {exc}", file=sys.stderr)
        self._last_send = self._clock()

    def maybe_heartbeat(self) -> bool:
        now = self._clock()
        if self._last_send is None or (now - self._last_send) >= self.heartbeat_s:
            self.send_label(self.rest_label)
            return True
        return False

    def close(self) -> None:
        pass

    def reachable(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(self.url.replace("/api/cue", "/api/state"),
                                        timeout=self.timeout) as r:
                r.read()
            return True
        except OSError:
            return False


class LockedSender:
    """`inference.SerialSender` made safe to share between the heartbeat and a clip.

    Both threads write Contract A lines to one open port and both consult the same
    "when did we last send" clock, so they take turns rather than interleaving
    bytes. Wrapping the real sender (instead of reimplementing it) keeps the
    heartbeat rule exactly as `inference.py` defines it: `maybe_heartbeat` sends
    `rest` only if `REST_HEARTBEAT_SEC` has elapsed since *any* send, so a fired
    command naturally suppresses the next heartbeat.
    """

    def __init__(self, sender) -> None:
        self._sender = sender
        self._lock = threading.Lock()

    def send_label(self, label: str) -> None:
        with self._lock:
            self._sender.send_label(label)

    def maybe_heartbeat(self) -> bool:
        with self._lock:
            return self._sender.maybe_heartbeat()

    def close(self) -> None:
        with self._lock:
            self._sender.close()


def heartbeat_forever(sender: LockedSender, every: float) -> None:
    """Keep `rest` flowing while no clip is playing, or the hand fail-safes."""
    while True:
        try:
            sender.maybe_heartbeat()
        except Exception as exc:                     # noqa: BLE001 - never die
            print(f"[hb] heartbeat failed: {exc}", file=sys.stderr)
        time.sleep(every)


def classify(path: Path, predictor, sender: LockedSender, quiet: bool) -> dict:
    """Run the project's own inference path on one snippet; collect what it said."""
    import inference

    buf = io.StringIO()
    t0 = time.monotonic()
    try:
        with contextlib.redirect_stdout(buf):
            confirmed = inference.stream_file(path, predictor, sender, quiet=quiet)
        returncode = 0
    except Exception:                                # noqa: BLE001 - report, don't die
        confirmed = []
        returncode = 1
        buf.write("\n" + traceback.format_exc())
    elapsed = time.monotonic() - t0

    output = buf.getvalue()
    print(output, end="" if output.endswith("\n") else "\n", flush=True)  # the journal
    if len(output) > MAX_OUTPUT:
        output = "... (truncated)\n" + output[-MAX_OUTPUT:]

    return {
        "cmd": f"inference.stream_file (resident, model={predictor.kind})",
        "returncode": returncode,
        "seconds": round(elapsed, 2),
        "output": output,
        # What the hand was actually told to do. The dashboard shows these as chips.
        "fires": [{"t": c["t"], "char": c["char"], "action": c["action"],
                   "name": c["name"], "conf": c["conf"]} for c in confirmed],
    }


def serve(sock: socket.socket, predictor, sender: LockedSender, outdir: Path,
          quiet: bool) -> None:
    """Handle every snippet on one open link, until the dashboard goes away."""
    while True:
        class_id, length = pi_receive.parse_header(
            pi_receive.recv_exactly(sock, pi_receive.HEADER_SIZE))
        data = pi_receive.recv_exactly(sock, length)

        path = outdir / f"snippet{class_id}.edf"
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)          # never hand a half-written file to the model
        print(f"[rx] class {class_id}: {length:,} B -> {path}", flush=True)

        verdict = classify(path, predictor, sender, quiet)
        verdict |= {"class_id": class_id, "bytes": length, "file": str(path)}
        fires = verdict["fires"]
        print(f"[rx] {len(fires)} command(s) confirmed in {verdict['seconds']}s: "
              f"{', '.join(f['name'] for f in fires) or '-'}", flush=True)

        try:                       # best-effort: a sender that hangs up is still correct
            sock.sendall(pi_receive.build_result(verdict))
        except OSError as exc:
            print(f"[rx] verdict not delivered ({exc}); the hand was still commanded",
                  file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path,
                    default=Path.home() / "EEG_GRADUATIO_PROJECT",
                    help="the classifier project (holds inference.py and models/)")
    ap.add_argument("--model", default="dtw",
                    choices=("dtw", "hybrid", "hierarchical", "flat"),
                    help="which trained model to serve (default: dtw)")
    ap.add_argument("--listen", type=int, default=5005,
                    help="TCP port the dashboard connects to (not 5000)")
    ap.add_argument("--serial-port", default=None,
                    help="UART to the hand (default: cfg.SERIAL_PORT / $EEG_SERIAL_PORT). "
                         "On a Pi 5 the hand on GPIO 14/15 is /dev/ttyAMA0 -- NOT "
                         "/dev/serial0, which is the debug connector")
    ap.add_argument("--hand-url", default=None, metavar="URL",
                    help="send Contract A over WiFi instead of a wire, e.g. "
                         "http://192.168.4.1 (the hand's own access point). Use this "
                         "when there is no working USB/UART link to the ESP32")
    ap.add_argument("--no-serial", action="store_true",
                    help="print the labels instead of writing them to a port")
    ap.add_argument("--require-serial", action="store_true",
                    help="refuse to start if the link will not open (use this in the "
                         "boot service: a silent fall-back to simulation looks exactly "
                         "like success while the hand never moves)")
    ap.add_argument("--outdir", type=Path, default=Path("/tmp/eeg-headset"),
                    help="where received snippets are written")
    ap.add_argument("--quiet", action="store_true",
                    help="log only confirmed commands, not every window")
    args = ap.parse_args(argv)

    sys.stdout.reconfigure(line_buffering=True)     # journald/nohup: don't buffer

    project = args.project.expanduser().resolve()
    if not (project / "inference.py").exists():
        print(f"error: no inference.py in {project} -- pass --project", file=sys.stderr)
        return 2
    # config.py names its models by RELATIVE path ("models/dtw_hybrid_model.pkl"),
    # so the model only loads if the project is the working directory.
    sys.path.insert(0, str(project))
    os.chdir(project)

    import inference
    from eeg_bci import config as cfg

    args.outdir.mkdir(parents=True, exist_ok=True)

    if args.no_serial and args.require_serial:
        print("error: --no-serial and --require-serial contradict each other",
              file=sys.stderr)
        return 2

    print(f"[boot] project {project}")
    predictor = inference.load_predictor(args.model)        # the slow part, paid once

    if args.hand_url:
        # WiFi: the Pi and the hand share the ESP32's own access point, so there is
        # no wire to fall out and no cable to be charge-only.
        raw_sender = HttpSender(args.hand_url, cfg.REST_HEARTBEAT_SEC,
                                cfg.CONTRACT_A_LABELS, cfg.REST_LABEL)
        if args.require_serial and not raw_sender.reachable():
            print(f"error: --require-serial: the hand is not answering at "
                  f"{args.hand_url}.\n"
                  f"  Is this Pi joined to the hand's WiFi?\n"
                  f"    nmcli -t -f NAME connection show --active   # ProstheticHand?\n"
                  f"    curl -s {args.hand_url}/api/state           # does it reply?",
                  file=sys.stderr)
            return 3
        print(f"[link] Contract A over WiFi -> {args.hand_url}/api/cue")
    else:
        port = args.serial_port or cfg.SERIAL_PORT
        raw_sender = inference.SerialSender(port, enabled=not args.no_serial)

        # SerialSender swallows *any* open failure and drops into simulation mode.
        # That is right for a laptop and dangerous for the deployed hand: the model
        # still classifies, the dashboard still reports "Hand commanded: C C C C",
        # and the labels go nowhere. Fail at boot instead, loudly, where systemd
        # will show it.
        if args.require_serial and raw_sender.ser is None:
            print(f"error: --require-serial: could not open {port}.\n"
                  f"  No USB/UART link? Use WiFi instead:  --hand-url http://192.168.4.1\n"
                  f"  Otherwise check:\n"
                  f"    ls -l /dev/ttyUSB* /dev/ttyACM* /dev/ttyAMA*  # does it exist?\n"
                  f"    id -nG | grep dialout                        # may we write it?",
                  file=sys.stderr)
            return 3

    sender = LockedSender(raw_sender)

    # Start the heartbeat before the first snippet: the hand must see `rest` from
    # the moment we are up, not from the moment someone presses a button.
    threading.Thread(target=heartbeat_forever,
                     args=(sender, cfg.REST_HEARTBEAT_SEC / 2), daemon=True).start()
    print(f"[boot] heartbeat: '{cfg.REST_LABEL}' every {cfg.REST_HEARTBEAT_SEC}s "
          f"(hand fail-safes after 3s of silence)")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.listen))
    srv.listen(1)
    print(f"[boot] ready: listening on 0.0.0.0:{args.listen} for the dashboard")

    try:
        while True:                       # outer loop: survive the laptop going away
            conn, addr = srv.accept()
            print(f"[rx] dashboard connected from {addr[0]}:{addr[1]}", flush=True)
            try:
                serve(conn, predictor, sender, args.outdir, args.quiet)
            except (ConnectionError, OSError) as exc:
                print(f"[rx] link closed: {exc}", flush=True)
            except ValueError as exc:
                print(f"[rx] bad frame, dropping link: {exc}", file=sys.stderr)
            finally:
                conn.close()
            print("[rx] waiting for the dashboard again ...", flush=True)
    except KeyboardInterrupt:
        print("\n[bye] stopped")
    finally:
        srv.close()
        sender.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
