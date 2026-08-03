#!/usr/bin/env python3
"""Find each servo's SAFE travel, one small step at a time, and write calib.json.

config.h ships the same wide pulse limits (500-2500 us) on all six channels, so a
built-in action like close_fist -- which drives every finger to 180 deg -- will
keep pushing after a finger has hit its mechanical stop. Stalled hobby servos
strip their own gears, snap tendons and cook their windings, and inside an
assembled hand you will not even hear it happening.

So we measure instead of guessing. This walks each channel outward in 5 deg steps
and waits for you at every step. The moment a finger strains, hits its stop, or
the servo starts to buzz, you press `x` and it backs off one step and records that
as the limit.

    # 1. join the hand's WiFi:  SSID ProstheticHand   password inmoov1234
    # 2. run this from the laptop:
    python3 tools/calibrate_servos.py

It only ever moves ONE servo at a time, never jumps straight to an extreme, and
returns the channel to where it started when it is done (or if you Ctrl-C).

Writes tools/calib.json — the measured safe angle range per channel.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "calib.json"

# Channel order is canonical (config.h): thumb, index, middle, ring, pinky, wrist.
CHANNELS = [
    (0, "thumb",  0),
    (1, "index",  0),
    (2, "middle", 0),
    (3, "ring",   0),
    (4, "pinky",  0),
    (5, "wrist",  40),      # WRIST_ANGLE_NEUTRAL
]

STEP = 5                     # degrees per step: small enough to stop before damage
SETTLE = 0.45                # > MOVE_DURATION_MS (400 ms) so the move finishes


def post(host: str, path: str, body: dict) -> None:
    req = urllib.request.Request(
        f"http://{host}{path}", method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as r:
        r.read()


def move(host: str, ch: int, angle: int) -> None:
    post(host, "/api/servo", {"channel": ch, "angle": int(angle)})
    time.sleep(SETTLE)


def check(host: str) -> None:
    try:
        with urllib.request.urlopen(f"http://{host}/api/state", timeout=4) as r:
            state = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        sys.exit(f"cannot reach the hand at http://{host} ({exc}).\n"
                 f"Join the 'ProstheticHand' WiFi (password inmoov1234) and retry.")
    print(f"connected to the hand: fw {state.get('fw', '?')}, "
          f"link A {'up' if state.get('linkAConnected') else 'down'}\n")


def sweep(host: str, ch: int, name: str, home: int, direction: int) -> int:
    """Step outward from home until the user says stop. Returns the last safe angle."""
    way = "closing / up" if direction > 0 else "opening / down"
    print(f"  {name}: sweeping {way} from {home} deg")
    print(f"    [Enter] = {STEP * direction:+d} deg   |   x = it is binding, stop   |   "
          f"s = skip this direction")

    angle = home
    last_safe = home
    while 0 <= angle + direction * STEP <= 180:
        nxt = angle + direction * STEP
        ans = input(f"    -> move {name} to {nxt:3d} deg ? ").strip().lower()
        if ans == "s":
            print(f"    skipped; keeping {last_safe} deg")
            return last_safe
        if ans == "x":
            break
        move(host, ch, nxt)
        angle = last_safe = nxt

    if angle in (0, 180):
        print(f"    reached the end of travel ({angle} deg) with no binding")
        return angle

    backed = max(0, min(180, last_safe - direction * STEP))
    print(f"    binding at ~{last_safe} deg -> backing off one step, "
          f"safe limit = {backed} deg")
    move(host, ch, backed)
    return backed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="192.168.4.1", help="the hand's AP address")
    ap.add_argument("--only", type=int, default=None, metavar="CH",
                    help="calibrate a single channel (0..5)")
    args = ap.parse_args(argv)

    print(__doc__.split("\n\n")[0] + "\n")
    check(args.host)

    print("Servos must be POWERED and the fingers free to move.")
    print("Stop the moment you hear a servo strain -- do not 'just one more step'.\n")
    input("Enter to begin, Ctrl-C to abort ")

    todo = [c for c in CHANNELS if args.only is None or c[0] == args.only]
    result = json.loads(OUT.read_text()) if OUT.exists() else {}

    for ch, name, home in todo:
        print(f"\n--- channel {ch}: {name.upper()} (home {home} deg) ---")
        move(args.host, ch, home)
        try:
            hi = sweep(args.host, ch, name, home, +1)
            lo = sweep(args.host, ch, name, home, -1)
        except KeyboardInterrupt:
            print(f"\n  aborted -> returning {name} to {home} deg")
            move(args.host, ch, home)
            raise

        result[str(ch)] = {"name": name, "min": lo, "max": hi, "home": home}
        print(f"  {name}: SAFE RANGE {lo} .. {hi} deg")
        move(args.host, ch, home)
        OUT.write_text(json.dumps(result, indent=2) + "\n")   # save as we go

    print(f"\nwrote {OUT}\n")
    print(f"  {'ch':<3} {'joint':<8} {'safe min':>8} {'safe max':>8}")
    for k in sorted(result, key=int):
        r = result[k]
        print(f"  {k:<3} {r['name']:<8} {r['min']:>8} {r['max']:>8}")
    print("\nBake these limits into the firmware by copying them into the per-channel")
    print(f"pulse/angle limits in include/config.h, or keep {OUT.name} for later reruns.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
        sys.exit(1)
