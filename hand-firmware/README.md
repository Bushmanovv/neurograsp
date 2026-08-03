# InMoov EEG Prosthetic Hand — ESP32 firmware + web dashboard

An EEG-controlled [InMoov](https://inmoov.fr/) prosthetic hand. A Raspberry Pi
runs the EEG classifier and streams *artifact labels* (blink, clinch, …)
over UART to an **ESP32**, which drives six servos directly from its GPIO pins
and hosts a self-contained web dashboard over its own WiFi access point. No
internet, no cloud — everything runs on the device.

```
  EEG headset ──► Raspberry Pi 5 ──UART──►  ESP32  ──PWM──► 6 servos
   (classifier)     (labels)                 │
                                             └──WiFi AP──► phone / browser dashboard
```

Cue path (`Pi → UART → dispatch → servos`) and app path
(`phone → HTTP/WS → dispatch → servos`) both funnel through **`dispatch.cpp`**
so the two control sources can never disagree, and both update the single
`g_status` snapshot the dashboard renders.

## Hardware

| Part | Detail |
|---|---|
| MCU | ESP32-WROOM dev board, **4 MB** flash (`esp32dev_4mb` env) |
| Servo drive | Direct ESP32 GPIO PWM via **ESP32Servo** — no PCA9685. Servos powered from an external supply with a common ground |
| Servos | 6× MG996R — thumb `GPIO13`, index `GPIO14`, middle `GPIO25`, ring `GPIO26`, pinky `GPIO27`, wrist `GPIO33` |
| Pi link | UART on `Serial2` — Pi TX→GPIO16, Pi RX←GPIO17, common ground, 115200 baud |
| Battery | 2S LiPo via divider into ADC `GPIO34` (calibrate `BATT_DIVIDER_RATIO`) |

All hardware/system tunables live in [`include/config.h`](include/config.h) —
pins, pulse limits, angle range, fail-safe timeout, AP SSID/password, etc.
Values marked `ASSUMPTION` are guesses to correct against your actual wiring.

## Firmware layers

Defined in [`src/main.cpp`](src/main.cpp) (`FW_VERSION 0.5.0-layer4`):

| Layer | What | Module |
|---|---|---|
| 0 | scaffold + contracts + persistent config | `store.*` |
| 1 | GPIO servo core (ESP32Servo), smooth moves, built-in gestures | `servos.*` |
| 1 | UART label listener + fail-safe hold | `uart_link.*`, `battery.*` |
| 2 | WiFi soft-AP + REST API | `webserver.*` |
| 3 | WebSocket telemetry push | `webserver.*` |
| 4 | static dashboard served from LittleFS (gzipped) | `webserver.*` |

## Contracts

Two contracts are expressed in code ([`include/contracts.h`](include/contracts.h))
so they can't drift from the docs:

- **Contract A — UART labels** (Pi → ESP32): one label per line, lower_snake_case.
  These are the EEG classifier's classes: `single_blink`, `double_blink`,
  `clinch`, `bruxism_left`, `bruxism_right`, plus `rest` (idle). Unknown
  labels are logged and ignored.
- **Contract B — actions**: a label maps to either a built-in action
  (`open_hand`, `close_fist`, `point`, `pinch`, `wrist_left`, `wrist_right`,
  `relax`) or the name of a saved pose. Default mapping lives in
  [`data/mappings.json`](data/mappings.json); poses in
  [`data/poses.json`](data/poses.json):

  | Label | Action |
  |---|---|
  | `single_blink` | `open_hand` |
  | `double_blink` | `pinch` |
  | `clinch` | `close_fist` |
  | `bruxism_left` | `wrist_left` |
  | `bruxism_right` | `wrist_right` |
  | `rest` | `relax` |

**Wrist:** channel 5 is a rotation servo — it turns the **whole hand around the
wrist axis** (pronation/supination), it does not tilt the wrist. Neutral is
**40°** (the centre used by every non-wrist gesture); `wrist_right` rotates to
**0°** and `wrist_left` to **180°**, holding the current finger angles.

**Home / reset:** on power-on — and each time the dashboard connects — the hand
resets to **open fingers + wrist neutral (40°)**.

**Fail-safe:** if no valid label arrives within `FAILSAFE_TIMEOUT_MS` (3 s), the
hand **holds** its current position — it never goes limp or snaps to a default.

## Web dashboard (`data/`)

A dependency-free clinical UI served from LittleFS. It has a **MOCK mode** that
kicks in automatically on `file://` or `localhost`/`127.*` (or with `?mock`),
using fake telemetry and a simulated EEG cue stream — so you can preview and
develop the whole app in a browser with **no ESP32 attached**. On real hardware
it talks to the firmware over `GET /api/state`, `POST` control endpoints, and a
`/ws` WebSocket for ~6–7 Hz live status.

## Project layout

```
platformio.ini        build envs (esp32dev_4mb default, esp32dev_8mb alt)
partitions_4mb.csv    1.75 MB app + ~2.1 MB LittleFS
include/              config.h, contracts.h
src/                  main + servos, uart_link, dispatch, webserver, store, battery, status
data/                 web dashboard (index.html, app.js, style.css, hand3d.js, vendor/, models/)
tools/prep_fs.py      gzips data/ into the FS image at build time
tools/fake_pi.py      pretends to be the Pi — streams test labels over serial
```

---

## Running it locally

### A. Web dashboard in the browser (no hardware) ✅ running now

The dashboard auto-enters MOCK mode on localhost. Serve the `data/` folder:

```bash
cd data
python3 -m http.server 8000 --bind 127.0.0.1
```

Then open **http://127.0.0.1:8000/** — you'll see the "Preview · mock data"
banner, live fake telemetry, and a simulated cue stream. All controls work
against the in-browser simulator.

### B. Build & flash the firmware (needs the ESP32)

Requires [PlatformIO](https://platformio.org/) (`pio` CLI). The default env is
`esp32dev_4mb`.

```bash
pio run                          # compile
pio run --target upload          # flash firmware
pio run --target uploadfs        # build + upload the LittleFS web assets
pio device monitor -b 115200     # serial console
```

Then join the WiFi AP **`ProstheticHand`** (password `inmoov1234`) and browse to
the ESP32 to reach the real dashboard.

### C. Simulate the Raspberry Pi (no EEG rig)

With the ESP32 connected over a USB-serial cable, stream test labels:

```bash
pip install pyserial
python3 tools/fake_pi.py --list                        # find the port
python3 tools/fake_pi.py --port <port> --auto 2.0      # random label every 2 s
python3 tools/fake_pi.py --port <port> --once clinch
```
