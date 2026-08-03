# InMoov EEG Prosthetic Hand — ESP32 controller + web app

Firmware + offline web app for an EEG-controlled 3D-printed InMoov hand.

```
EEG headset -> Raspberry Pi 5 (classifier) -(UART)-> ESP32 (this) -(WiFi AP)-> phone/laptop
```

The ESP32 receives abstract artifact **labels** from the Pi, looks them up in a
user-editable **mapping table**, and drives 6 servos (5 fingers + wrist) via a
PCA9685. It also hosts the configuration/dashboard web app in **WiFi Access
Point mode** — the phone joins the ESP32's own network with **no internet**, so
**every asset is served locally** (no CDNs).

See [`CONTRACTS.md`](CONTRACTS.md) for the UART + Web API contracts and data models.

## Build plan (layers)

| Layer | What | Status |
|-------|------|--------|
| 0 | Scaffold, `platformio.ini`, contracts, default JSON | ✅ done |
| 1 | PCA9685 servo core, built-in actions, UART listener, fail-safe | ⏳ next |
| 2 | WiFi AP + read-only status dashboard + WebSocket | ⬜ |
| 3 | Mapping editor (remap labels live) | ⬜ |
| 4 | Pose creator (sliders drive the real hand, save/apply/delete) | ⬜ |
| 5 | Three.js 3D digital twin (stretch; degrades gracefully) | ⬜ |

## Project layout
```
platformio.ini        build config (8 MB primary env, 4 MB fallback env)
partitions_8mb.csv     custom 8 MB partition: 3 MB app + ~4.8 MB LittleFS
include/config.h       ALL hardware/system tunables (pins, channels, SSID, ...)
include/contracts.h    valid labels + built-in actions, in code
src/main.cpp           firmware entry point
data/                  LittleFS image: mappings.json, poses.json (+ web assets later)
tools/fake_pi.py       pretend to be the Pi: send fake labels over serial
```

## Hardware assumptions (correct these in `include/config.h`)
- Generic ESP32 dev board, **8 MB flash** preferred (4 MB env provided as fallback).
- PCA9685 on I2C: SDA=GPIO21, SCL=GPIO22, addr 0x40.
- Servos on PCA9685 ch 0–4 (thumb,index,middle,ring,pinky) + ch 5 (wrist).
- Battery via voltage divider into GPIO34 (ADC1).
- Pi UART on `Serial2`: RX=GPIO16, TX=GPIO17, 115200 baud.

---

## Layer 0 — flash & test

**1. Install PlatformIO** (VS Code extension, or `pip install platformio`).

**2. Upload the LittleFS image** (the `data/` folder → flash):
```bash
pio run -t buildfs
pio run -t uploadfs
```

**3. Flash the firmware:**
```bash
pio run -t upload
```

**4. Open the serial monitor:**
```bash
pio device monitor
```

### What you should see
On boot, over serial at 115200:
```
=============================================
  InMoov Hand controller  fw 0.1.0-layer0
  LAYER 0 — scaffold + contracts
=============================================
[FS] LittleFS mounted (xxxxx / xxxxxx bytes used)
[FS] /mappings.json present
[FS] /poses.json present
[CONTRACT A] 7 valid labels, 7 built-in actions
[MAP] label -> action:
       eye_blink      -> open_hand    [label ok, built-in]
       double_blink   -> pinch        [label ok, built-in]
       ...
[POSE] 1 saved pose(s):
       ok_sign      [120, 100, 10, 10, 10, 90]
[OK] Layer 0 ready. Proceed to Layer 1 (servo control).
```

That confirms: the board flashes, LittleFS mounts, the default config files are
present (or were auto-created), and both contracts parse correctly.

> If you have a **4 MB** board, build with `-e esp32dev_4mb` (e.g.
> `pio run -e esp32dev_4mb -t upload`).

**fake_pi.py** isn't needed yet (no UART listener until Layer 1), but you can
already sanity-check your serial wiring later with:
```bash
pip install pyserial
python3 tools/fake_pi.py --list
```

---

Confirm Layer 0 flashes and prints the above, and I'll build **Layer 1** (servo
control core + UART label handling + fail-safe).
