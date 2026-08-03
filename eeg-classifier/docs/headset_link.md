# Headset link — EDF in, hand commands out

One long-lived process on the Raspberry Pi, `tools/headset_daemon.py`, ties the
whole demo together:

```
  headset simulator (laptop)  ──EDF1 frame over TCP──┐
                                                     ├─►  headset_daemon.py  ──Contract A labels over UART──►  hand ESP32
  real headset (ESP32, later) ──EDF1 frame over BT ──┘        (Pi 5)                (/dev/serial0, 8N1 115200)
```

The headset sends **one `.edf` per artifact** (a ~5 s snippet). The daemon loads
the classifier **once**, opens the hand's serial port **once**, then classifies
each snippet as it arrives and drives the hand. It reuses `inference.py`'s own
helpers unchanged — the classification path is identical to `inference.py --file`.

## Wire format (Contract, owned by the headset-link tree)

```
"EDF1" | class_id u8 | length u32 little-endian | <length bytes of .edf>
```

Byte-identical whether it arrives over TCP (laptop) or Bluetooth SPP (ESP32).
Source of truth: `~/neurograsp` (`pi_receive.py`, `firmware/.../esp32_headset.ino`,
pinned by `tests/test_edf_link.py`). `tools/pi_receive.py` here is a vendored copy
of that frame codec — keep them in sync.

`class_id` only names the received file; the classifier re-derives the gesture
from the EDF content, so a wrong `class_id` cannot mislabel the hand.

---

## Current path — headset simulator on a laptop (TCP)

The Pi is the **server**; the laptop **connects in**. Both must be on the same
Wi-Fi/LAN.

**On the Pi** (hand attached on `/dev/serial0` — see [../PROJECT_SUMMARY.md] and
the ESP32 hand wiring from the UART task):

```bash
cd ~/neurograsp/eeg-classifier
python3 tools/headset_daemon.py --tcp-listen 5005
#   add --no-serial to test without the hand (labels are printed, no port opened)
#   add --quiet     to show only the confirmed command per snippet
```

First start takes ~10–20 s (loads mne + the DTW model); after that every press
responds in ~1–2 s because nothing reloads.

Find the Pi's address for the laptop to dial:

```bash
hostname -I        # e.g. 192.168.1.42
```

**On the laptop** — send one EDF per artifact. The reference simulator is
`host_send.py` in the headset-link tree (it speaks the exact EDF1 frame):

```bash
cd ~/neurograsp
python3 host_send.py firmware/esp32_headset/data/s0.edf --host 192.168.1.42 --port 5005
# many presses on one connection:
python3 host_send.py firmware/esp32_headset/data/s{0,1,2,3,4}.edf --host 192.168.1.42 --port 5005
```

> **Not port 5000** — macOS AirPlay Receiver listens there and will eat the
> connection. 5005 (or any free high port) is fine; match `--tcp-listen`.

Any dashboard that emits the same EDF1 frame to the Pi's TCP port works too —
the daemon does not care what the sender is, only that the frame matches.

---

## Future path — real ESP32 headset (Bluetooth SPP)

The Pi **dials** the board's SPP service (the board is the server). Linux only —
`AF_BLUETOOTH` does not exist on macOS, which is why the laptop path is TCP.

Pair once:

```bash
bluetoothctl
  scan on            # find the ESP32 (BT name "ESP32-EEG-Headset")
  pair  AA:BB:CC:DD:EE:FF
  trust AA:BB:CC:DD:EE:FF
  quit
```

Then run the daemon against it — everything downstream is identical:

```bash
python3 tools/headset_daemon.py --mac AA:BB:CC:DD:EE:FF
```

---

## Idle heartbeat

While a connection is open but no gesture is being emitted, the daemon resends
`rest` every `REST_HEARTBEAT_SEC` (1.2 s, in `eeg_bci/config.py`) so the hand
firmware's 3000 ms fail-safe never trips between presses. Verified: a 4 s idle
hold emits ~3 `rest` lines; between-press gaps stay under the fail-safe.

## Options (mirror `inference.py`)

| flag | meaning |
|---|---|
| `--tcp-listen PORT` / `--mac ADDR` | transport (one required) |
| `--model dtw\|hybrid\|hierarchical\|flat` | classifier (default `dtw`) |
| `--port /dev/serial0` | hand UART (default `cfg.SERIAL_PORT` / `$EEG_SERIAL_PORT`) |
| `--no-serial` | do not open the hand port; print labels |
| `--quiet` | only confirmed commands per snippet |
| `--threshold` / `--activity` | confidence / activity-gate overrides |
| `--once` | handle a single snippet then exit (testing) |

## Fallback — subprocess per press

`tools/pi_receive.py` is the simpler receiver that runs a fresh
`inference.py --file {edf}` per snippet. Correct, but reloads the model every
press (~7 s on a laptop, more on a Pi) and sends no heartbeat between presses.
The daemon is preferred; `pi_receive.py` is kept for parity with headset-link/ and
as the EDF1 frame codec the daemon imports.

## Verified (2026-07-12, on the dev laptop over TCP)

- All five snippets `s0..s4.edf` → `double_blink / single_blink / clinch /
  bruxism_left / bruxism_right`, matching the headset-link table.
- Model loaded once; five snippets classified with no reload.
- Heartbeat fires during idle (pure 4 s hold → 3 × `rest`).
- Not yet run on the real Pi 5 (needs the board + the hand ESP32).
