# InMoovApp — EEG-Controlled InMoov Prosthetic Hand

A 3D-printed [InMoov](http://inmoov.fr) robotic hand that is driven by **EEG
brain/face artifacts** instead of muscle sensors. A user wearing an EEG headset
triggers gestures (open, close, pinch, point, wrist rotation) by blinking,
clenching the jaw, raising eyebrows, or looking left/right. An ESP32 drives the
servos and hosts a phone-friendly web app for configuration — entirely offline.

This file is the high-level map of the project. For the precise interface specs
see [`CONTRACTS.md`](CONTRACTS.md); for flashing instructions see
[`README.md`](README.md).

---

## System overview

```
 ┌────────────┐   classified    ┌──────────────┐   label/line   ┌─────────────┐   PWM    ┌──────────┐
 │ EEG headset│ ───artifacts──► │ Raspberry Pi │ ──(UART 8N1)──►│   ESP32     │ ──I2C──► │ PCA9685  │──► 6 servos
 │  (signals) │                 │ 5 classifier │   Contract A   │ (this repo) │  GPIO21/22│  16-ch   │   5 fingers
 └────────────┘                 └──────────────┘                └─────────────┘          └──────────┘   + wrist
                                                                       │
                                                          WiFi Access Point (Contract B)
                                                                       │ no internet — assets served locally
                                                                       ▼
                                                             ┌───────────────────┐
                                                             │ phone / laptop    │
                                                             │ web dashboard +   │
                                                             │ mapping/pose editor│
                                                             └───────────────────┘
```

- The **Pi** does the heavy EEG signal classification and emits an abstract
  **label** (e.g. `jaw_clench`) — one per line over UART.
- The **ESP32** (this firmware) looks the label up in a user-editable **mapping
  table**, runs the resulting **action**, and drives the 6 servos through a
  PCA9685.
- The ESP32 also runs a **WiFi Access Point**. The phone joins the hand's own
  network — there is **no internet**, so every web asset is served locally from
  the on-chip filesystem (no CDNs anywhere).

---

## Repository layout

```
platformio.ini        Build config — 8 MB primary env + 4 MB fallback env
partitions_8mb.csv    Custom 8 MB partition table (≈3 MB app + ≈4.8 MB LittleFS)
CONTRACTS.md          Source-of-truth interface specs (UART + Web API + data models)
README.md             Layer-by-layer build plan + flash/test instructions

include/
  config.h            ALL hardware/system tunables (pins, channels, SSID, timeouts…)
  contracts.h         Valid labels + built-in actions, mirrored in code

src/
  main.cpp            Firmware entry point (currently Layer 0)

data/                 LittleFS image (flashed to the device)
  mappings.json       Default label → action map
  poses.json          Default saved poses
  index.html          Web app shell (vanilla SPA, native-app feel)
  style.css           "Light clinical" theme
  app.js              App logic + LIVE/MOCK API layer
  hand3d.js           Three.js 3D hand (GLB loader + procedural fallback)
  vendor/             Locally vendored Three.js r137 + GLTFLoader (no CDNs)
  models/             3D model assets (.glb)

tools/
  fake_pi.py          Stand-in for the Pi — sends fake labels over serial
```

---

## Hardware

| Part | Detail |
|------|--------|
| MCU | ESP32-D0WD-V3 dev board, **4 MB flash** (board on hand). 8 MB env provided as a stretch target. |
| Servo driver | PCA9685 16-channel PWM over I2C — SDA=GPIO21, SCL=GPIO22, addr `0x40`, 50 Hz |
| Servos | 6 total: ch 0–4 = thumb/index/middle/ring/pinky, ch 5 = wrist |
| Pi link | `Serial2` UART — RX=GPIO16, TX=GPIO17, 115200 baud, common ground |
| Battery | 2S LiPo via voltage divider into GPIO34 (ADC1) for % monitoring |

All of the above are `#define`s in [`include/config.h`](include/config.h) — that
file is the single place to correct wiring and calibrate.

> **Toolchain note:** the `pio` CLI is not on PATH on the dev machine — use
> `~/.platformio/penv/bin/pio`. The board enumerates at
> `/dev/cu.usbserial-0001`. Build env is `esp32dev_4mb`.

---

## The two contracts

Everything hinges on two interfaces, mirrored in code so they can't silently
drift. Full detail in [`CONTRACTS.md`](CONTRACTS.md).

### Contract A — UART (Pi → ESP32)
One lower_snake_case **label** per newline-terminated line. Unknown labels are
logged and ignored (never crash, never move).

Valid labels: `eye_blink`, `double_blink`, `jaw_clench`, `eyebrow_raise`,
`look_left`, `look_right`, `rest`.

### Contract B — Web API (ESP32 → browser, over the AP)
Static files + REST + a WebSocket, all from LittleFS:

| | |
|---|---|
| `GET /` | the web app |
| `GET/POST /api/mappings` | read / replace the label→action map |
| `GET/POST /api/poses`, `DELETE /api/poses/{name}` | manage saved poses |
| `POST /api/servo` | live-set one servo angle (pose-editor preview) |
| `POST /api/pose/apply` | apply a saved pose by name |
| `POST /api/relax` | emergency open/relax |
| `GET /api/status` · `WS /ws` | live telemetry (battery, link, last label, angles…) |

### Data models
- **Mapping** (`/mappings.json`): flat object, each label → an **action string**
  that is *either* a built-in action *or* the name of a saved pose.
- **Pose** (`/poses.json`): `{ "name", "angles": [6 ints] }`, degrees 0–180, in
  channel order `[thumb, index, middle, ring, pinky, wrist]`.
- **Built-in actions:** `open_hand`, `close_fist`, `point`, `pinch`,
  `wrist_left`, `wrist_right`, `relax`.

### Fail-safe
If no valid label arrives within `FAILSAFE_TIMEOUT_MS` (default 3 s) the hand
**holds its current position** — it does not go limp or snap to a default. A
`POST /api/relax` button is the manual escape hatch.

---

## Build plan (layers)

The firmware is being built in deliberate, independently-verifiable layers.

| Layer | What | Status |
|-------|------|--------|
| 0 | Scaffold, `platformio.ini`, contracts, default JSON, FS self-heal | ✅ done — flashed & boot-verified on real board |
| 1 | PCA9685 servo core, built-in actions, UART listener, fail-safe | ⏳ next |
| 2 | WiFi AP + read-only status dashboard + WebSocket | ⬜ |
| 3 | Mapping editor (remap labels live) | ⬜ |
| 4 | Pose creator (sliders drive the real hand; save/apply/delete) | ⬜ |
| 5 | Three.js 3D digital twin (stretch; degrades gracefully) | ⬜ |

**Layer 0 is verified on hardware:** the boot banner prints, LittleFS mounts,
both config files load, and both contracts parse (7 labels, 7 built-in actions,
1 saved pose). Flash footprint on the 4 MB board is ≈16% (≈319 KB).

---

## Web app

A vanilla-JS single-page app (no frameworks, no CDNs) living in [`data/`](data/),
designed to feel like a **native phone app**, not a web page: full-screen, phone
frame on desktop, bottom tab bar (Home · Mappings · Poses).

- **Theme:** "light clinical" — white/blue, rounded cards, mobile-first (used on a
  phone joined to the hand's WiFi AP).
- **Home:** a drag-to-rotate **3D model of the InMoov hand** (real WebGL via
  Three.js r137, vendored locally) that re-poses live as cues arrive.
  [`data/hand3d.js`](data/hand3d.js) loads `models/hand.glb` and falls back to a
  procedural articulated robot hand if the model is missing.
- **Mappings / Poses:** editors that talk to the Contract B REST API; a
  lightweight inline SVG hand previews pose-editor sliders.
- **MOCK mode:** [`data/app.js`](data/app.js) auto-runs with fake data and a
  simulated EEG cue stream when opened via `file://`, on `localhost`, or with
  `?mock`, so the whole UI works with **no ESP32 attached**. The same `api`
  object is where the real `/api/*` + `/ws` calls wire in for Layers 2+.

> This web layer is **design-first**: it's a working prototype, but the firmware
> that actually serves it over the AP (Layers 2–4) is not built yet. GLB loading
> needs HTTP, so preview with `cd data && python3 -m http.server 8777`.

---

## Quick start

```bash
# 1. Upload the filesystem image (data/ → flash)
~/.platformio/penv/bin/pio run -e esp32dev_4mb -t uploadfs --upload-port /dev/cu.usbserial-0001

# 2. Flash the firmware
~/.platformio/penv/bin/pio run -e esp32dev_4mb -t upload --upload-port /dev/cu.usbserial-0001

# 3. Watch the boot banner
~/.platformio/penv/bin/pio device monitor

# Preview the web app standalone (mock mode, no board needed)
cd data && python3 -m http.server 8777   # → http://localhost:8777/index.html
```

See [`README.md`](README.md) for the expected serial output and the generic
(`pio` on PATH) command forms.
