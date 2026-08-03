#!/usr/bin/env python3
"""serial_smoketest.py -- isolate wiring/port/baud from the classifier.

Opens the SAME serial port + baud the classifier uses (cfg.SERIAL_PORT /
cfg.SERIAL_BAUD, 8N1) and writes ONE Contract A label line -- by default
``clinch\\n`` -- straight to the ESP32, bypassing all model code.

Purpose (see inference.py step 9): if the real hand does NOT move when
inference.py runs but DOES move when this script sends ``clinch``, the model
path is fine and you should look at the model/gate/FSM. If it does NOT move
here either, the problem is wiring / port / baud / ground -- fix that layer
first. The label strings are Contract A, shared with the ESP32 firmware's
include/contracts.h (VALID_LABELS) -- keep them in sync.

Run ON THE PI (not a laptop):
    pip install pyserial                      # if not already present
    python3 tools/serial_smoketest.py                 # writes clinch once
    python3 tools/serial_smoketest.py --label single_blink
    python3 tools/serial_smoketest.py --port /dev/ttyAMA0
    python3 tools/serial_smoketest.py --sequence clinch,rest,single_blink --gap 1.0
    python3 tools/serial_smoketest.py --list          # list serial ports, exit
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Import the project's config so port/baud/labels can't drift from inference.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eeg_bci import config as cfg  # noqa: E402


def list_ports() -> None:
    """Print every serial port pyserial can see, then exit."""
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device:24s} {p.description}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    ap.add_argument("--port", default=cfg.SERIAL_PORT,
                    help=f"serial port (default {cfg.SERIAL_PORT}; or $EEG_SERIAL_PORT)")
    ap.add_argument("--baud", type=int, default=cfg.SERIAL_BAUD,
                    help=f"baud (default {cfg.SERIAL_BAUD})")
    ap.add_argument("--label", default="clinch",
                    help="single Contract A label to send (default clinch)")
    ap.add_argument("--sequence",
                    help="comma-separated labels to send in order (overrides --label)")
    ap.add_argument("--gap", type=float, default=1.0,
                    help="seconds between labels in a --sequence (default 1.0)")
    args = ap.parse_args(argv)

    try:
        import serial  # pyserial
    except ImportError:
        sys.exit("pyserial not installed.  pip install pyserial")

    if args.list:
        list_ports()
        return 0

    labels = ([s.strip() for s in args.sequence.split(",") if s.strip()]
              if args.sequence else [args.label])

    unknown = [l for l in labels if l not in cfg.CONTRACT_A_LABELS]
    if unknown:
        print(f"WARNING: {unknown} not in Contract A "
              f"{sorted(cfg.CONTRACT_A_LABELS)} -- the ESP32 will log+ignore them.")

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1,
                            bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                            stopbits=serial.STOPBITS_ONE)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Could not open {args.port} @ {args.baud}: "
                 f"{type(exc).__name__}: {exc}\n"
                 f"(is the port right? try --list; is the Linux console still bound "
                 f"to this UART? check /boot/firmware/config.txt)")

    print(f"[smoketest] opened {args.port} @ {args.baud} baud 8N1")
    time.sleep(2.0)  # let the ESP32 finish resetting after the port opens
    for i, label in enumerate(labels):
        line = f"{label}\n"
        ser.write(line.encode("utf-8"))   # exact bytes inference.py sends
        ser.flush()
        print(f"[smoketest] -> sent {line!r}")
        if i < len(labels) - 1:
            time.sleep(args.gap)
    ser.close()
    print("[smoketest] done. Watch the ESP32 monitor (pio device monitor -b 115200) "
          "and the hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
