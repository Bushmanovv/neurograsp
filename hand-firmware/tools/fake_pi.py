#!/usr/bin/env python3
"""
fake_pi.py — pretend to be the Raspberry Pi EEG classifier.

Sends fake artifact labels to the ESP32 over serial (Contract A: one label per
line, newline-terminated). Use this to build and test the whole hand + web app
BEFORE the real EEG classifier is finished.

Requires: pip install pyserial

Examples:
    # List available serial ports
    python3 fake_pi.py --list

    # Interactive menu (pick a label by number, repeatedly)
    python3 fake_pi.py --port /dev/ttyUSB0

    # Send one label and exit
    python3 fake_pi.py --port /dev/ttyUSB0 --once clinch

    # Auto-loop random labels every 2 s (great for watching the dashboard)
    python3 fake_pi.py --port /dev/ttyUSB0 --auto 2.0

Notes:
 * On the Pi the ESP32 link is typically /dev/serial0 or /dev/ttyAMA0 (the GPIO
   UART). When testing from a laptop with a USB-serial cable it's usually
   /dev/ttyUSB0 (Linux), /dev/tty.usbserial-* (macOS), or COMx (Windows).
 * Baud must match UART_BAUD in include/config.h (default 115200).
"""

import argparse
import random
import sys
import time

# Contract A — MUST stay in sync with include/contracts.h (VALID_LABELS).
# These are the exact labels the ESP32 firmware accepts; anything else is
# logged and ignored by the device.
VALID_LABELS = [
    "single_blink",
    "double_blink",
    "clinch",
    "bruxism_left",
    "bruxism_right",
    "rest",
]

BAUD = 115200


def list_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("pyserial not installed.  pip install pyserial")
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device:20s} {p.description}")


def open_serial(port, baud):
    try:
        import serial
    except ImportError:
        sys.exit("pyserial not installed.  pip install pyserial")
    try:
        return serial.Serial(port, baud, timeout=1)
    except Exception as e:
        sys.exit(f"Could not open {port} @ {baud}: {e}")


def send(ser, label):
    line = (label + "\n").encode("ascii")
    ser.write(line)
    ser.flush()
    print(f"-> sent: {label}")


def interactive(ser):
    print("\nPick a label to send (Ctrl-C to quit):")
    while True:
        for i, lbl in enumerate(VALID_LABELS):
            print(f"  [{i}] {lbl}")
        try:
            choice = input("label #> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not choice:
            continue
        try:
            send(ser, VALID_LABELS[int(choice)])
        except (ValueError, IndexError):
            print("  invalid choice")


def auto_loop(ser, period):
    print(f"Auto-sending random labels every {period}s (Ctrl-C to quit)")
    try:
        while True:
            send(ser, random.choice(VALID_LABELS))
            time.sleep(period)
    except KeyboardInterrupt:
        print()


def main():
    ap = argparse.ArgumentParser(description="Fake EEG-classifier label sender")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    ap.add_argument("--port", help="serial port (e.g. /dev/ttyUSB0, COM3)")
    ap.add_argument("--baud", type=int, default=BAUD, help=f"baud (default {BAUD})")
    ap.add_argument("--once", metavar="LABEL", help="send one label and exit")
    ap.add_argument("--auto", type=float, metavar="SECS",
                    help="auto-send random labels every SECS seconds")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return
    if not args.port:
        ap.error("--port is required (or use --list)")

    ser = open_serial(args.port, args.baud)
    print(f"Opened {args.port} @ {args.baud}")
    time.sleep(2)  # let the ESP32 reset after the port opens

    if args.once:
        if args.once not in VALID_LABELS:
            print(f"WARNING: '{args.once}' is not in VALID_LABELS "
                  f"(ESP32 will log+ignore it)")
        send(ser, args.once)
    elif args.auto:
        auto_loop(ser, args.auto)
    else:
        interactive(ser)

    ser.close()


if __name__ == "__main__":
    main()
