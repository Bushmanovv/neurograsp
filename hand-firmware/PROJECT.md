# InMoov EEG Prosthetic Hand — Full Project Documentation

A deep-dive technical reference for the EEG-controlled [InMoov](https://inmoov.fr/)
prosthetic hand. This document complements [README.md](README.md): the README is the
quick-start, this is the "how and why" of every part of the system.

Firmware version at time of writing: **`0.5.0-layer4`** (see
[`include/config.h`](include/config.h)).

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [System architecture](#2-system-architecture)
3. [Hardware](#3-hardware)
4. [The two contracts](#4-the-two-contracts)
5. [Firmware — module by module](#5-firmware--module-by-module)
6. [Concurrency & thread-safety model](#6-concurrency--thread-safety-model)
7. [Servo control in detail](#7-servo-control-in-detail)
8. [Persistence: mappings & poses](#8-persistence-mappings--poses)
9. [Web server & REST/WebSocket API](#9-web-server--restwebsocket-api)
10. [The web dashboard](#10-the-web-dashboard)
11. [The 3D hand twin](#11-the-3d-hand-twin)
12. [Build system, partitions & the FS image](#12-build-system-partitions--the-fs-image)
13. [Tooling](#13-tooling)
14. [Configuration reference](#14-configuration-reference)
15. [Safety features](#15-safety-features)
16. [Running & developing](#16-running--developing)
17. [File-by-file map](#17-file-by-file-map)
18. [Status, roadmap & known notes](#18-status-roadmap--known-notes)

---

## 1. What this project is

An **EEG-controlled prosthetic hand**. A person wears an EEG headset; a
**Raspberry Pi 5** runs a classifier that turns brain/facial-muscle *artifacts*
(blinks, jaw clenches) into short text **labels**. Those labels stream over a
serial (UART) link to an **ESP32** microcontroller, which:

- drives **6 hobby servos** (5 fingers + 1 wrist-rotation joint) directly from
  its GPIO pins, and
- hosts a **self-contained web dashboard** over its own WiFi access point.

Everything runs **on the device** — no internet, no cloud, no external
dependencies at runtime. The phone/browser dashboard is served entirely from the
ESP32's flash filesystem, so it works in a clinic, a lab, or a field with zero
connectivity.

The design goal that shapes almost every decision below: **two independent
control sources (the EEG cue stream and the human using the dashboard) must never
be able to disagree about what the hand is doing, and the hand must always fail
to a safe state.**

---

## 2. System architecture

```
  EEG headset ──►  Raspberry Pi 5   ──UART──►      ESP32       ──PWM──► 6 servos
   (electrodes)    (EEG classifier)   115200      (firmware)   GPIO     (MG996R)
                    emits "labels"    Serial2        │
                                                     └──WiFi soft-AP──► phone / browser
                                                          HTTP + WS      (dashboard)
```

There are **two control paths**, and they deliberately converge:

| Path | Source | Route through firmware |
|---|---|---|
| **Cue path** | Pi EEG classifier | `uart_link` → `dispatch` → `servos` |
| **App path** | Human on the dashboard | `webserver` → `dispatch` → `servos` |

Both funnel through **[`dispatch.cpp`](src/dispatch.cpp)** — the single place where an
*action* (a built-in gesture or a saved pose) becomes servo targets. Both also
update the one shared **`g_status`** snapshot that the dashboard renders. This is
the architectural spine of the whole system:

- No matter who commands the hand, the same code moves the servos.
- No matter who commands the hand, the dashboard shows the same truth.
- The two paths run on **different FreeRTOS tasks**, so all shared state is
  guarded by a single mutex (see §6).

---

## 3. Hardware

| Part | Detail |
|---|---|
| **MCU** | ESP32-WROOM dev board, chip **ESP32-D0WD-V3**, **4 MB** flash (`esp32dev_4mb` build env) |
| **Servo drive** | Direct ESP32 GPIO PWM via the **ESP32Servo** library (the ESP32 LEDC peripheral). **No PCA9685.** Servos are powered from an **external supply**, with a **common ground** back to the ESP32 |
| **Servos** | 6× **MG996R** class |
| **Pi link** | UART on **`Serial2`**, 115200 8N1 |
| **Battery** | 2S LiPo through a resistor divider into an ADC pin |

### Pin map (canonical channel order)

The order `thumb, index, middle, ring, pinky, wrist` is **canonical** everywhere —
every `angles[6]` array in the API, poses, and UI uses this order.

| Channel | Joint | ESP32 GPIO | Constant |
|:--:|---|:--:|---|
| 0 | Thumb | `GPIO13` | `SERVO_PIN_THUMB` |
| 1 | Index | `GPIO14` | `SERVO_PIN_INDEX` |
| 2 | Middle | `GPIO25` | `SERVO_PIN_MIDDLE` |
| 3 | Ring | `GPIO26` | `SERVO_PIN_RING` |
| 4 | Pinky | `GPIO27` | `SERVO_PIN_PINKY` |
| 5 | Wrist (rotation) | `GPIO33` | `SERVO_PIN_WRIST` |

Other pins:

| Function | Pin | Notes |
|---|:--:|---|
| UART RX (← Pi TX) | `GPIO16` | `Serial2` receive |
| UART TX (→ Pi RX) | `GPIO17` | `Serial2` transmit (mostly unused; the link is Pi→ESP32) |
| Battery ADC | `GPIO34` | input-only ADC1 pin, 11 dB attenuation for the full ~0–3.3 V range |

> ⚠️ Values in [`config.h`](include/config.h) marked **`ASSUMPTION`** (divider
> ratio, pulse limits, wrist endpoints, etc.) are educated guesses to be
> calibrated against the real wiring on the bench.

### The wrist joint (important nuance)

Channel 5 is a **rotation** servo. It turns the **whole hand around the wrist
axis** (pronation/supination) — it does **not** tilt the wrist up/down.

- **Neutral = 40°** — the centre used by every non-wrist gesture.
- `wrist_right` → **0°**, `wrist_left` → **180°**.
- The `wrist_left` / `wrist_right` actions **hold the current finger angles** and
  rotate only the wrist (they're synthesized on demand from the live position —
  see §7).

---

## 4. The two contracts

Both contracts are expressed **in code** ([`include/contracts.h`](include/contracts.h))
so they can't silently drift from the docs. The Python simulator
([`tools/fake_pi.py`](tools/fake_pi.py)) and the web app
([`data/app.js`](data/app.js)) mirror the same lists.

### Contract A — UART labels (Pi → ESP32)

One label per line, newline-terminated, `lower_snake_case`. Unknown labels are
logged and ignored. These are the EEG classifier's output classes:

```
single_blink   double_blink   clinch   bruxism_left   bruxism_right   rest
```

`rest` is the idle class. `clinch` is spelled that way deliberately — it's the
canonical string the Pi classifier emits.

### Contract B — actions

A label maps to an **action**, which is *either* a built-in gesture *or* the name
of a saved pose. Built-in gestures:

```
open_hand   close_fist   point   pinch   wrist_left   wrist_right   relax
```

The default label→action mapping (in [`data/mappings.json`](data/mappings.json)
and hard-coded as the firmware default in [`store.cpp`](src/store.cpp)):

| Label | Action | Result |
|---|---|---|
| `single_blink` | `open_hand` | fingers open, wrist neutral |
| `double_blink` | `pinch` | thumb + index pinch |
| `clinch` | `close_fist` | full fist |
| `bruxism_left` | `wrist_left` | rotate wrist to 180°, hold fingers |
| `bruxism_right` | `wrist_right` | rotate wrist to 0°, hold fingers |
| `rest` | `relax` | soft-open (all fingers ~20°) |

Built-in gesture angle tables (logical degrees, canonical order):

| Action | Thumb | Index | Middle | Ring | Pinky | Wrist |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `open_hand` | 0 | 0 | 0 | 0 | 0 | 40 |
| `close_fist` | 180 | 180 | 180 | 180 | 180 | 40 |
| `point` | 180 | 0 | 180 | 180 | 180 | 40 |
| `pinch` | 130 | 130 | 0 | 0 | 0 | 40 |
| `relax` | 20 | 20 | 20 | 20 | 20 | 40 |
| `wrist_left` | *(hold)* | *(hold)* | *(hold)* | *(hold)* | *(hold)* | 180 |
| `wrist_right` | *(hold)* | *(hold)* | *(hold)* | *(hold)* | *(hold)* | 0 |

This table lives in `BUILTIN_TABLE` in [`servos.cpp`](src/servos.cpp) and is
mirrored by `ACTION_ANGLES` in [`app.js`](data/app.js) — they **must** stay in
sync so the on-screen hand and the physical hand agree.

**Home / reset:** on power-on — and each time the dashboard connects — the hand
resets to **open fingers + wrist neutral (40°)**.

---

## 5. Firmware — module by module

The firmware is organized into **layers**, each building on the last. All layers
0–4 are implemented. The `loop()` in [`main.cpp`](src/main.cpp) is a simple
non-blocking super-loop that pumps every subsystem once per pass.

| Layer | What | Modules |
|:--:|---|---|
| 0 | scaffold + contracts + persistent config | `store.*` |
| 1 | GPIO servo core, smooth moves, built-in gestures | `servos.*` |
| 1 | UART label listener + fail-safe hold, battery monitor | `uart_link.*`, `battery.*` |
| 2 | WiFi soft-AP + REST API | `webserver.*` |
| 3 | WebSocket telemetry push | `webserver.*` |
| 4 | static dashboard served from LittleFS (gzipped) | `webserver.*` |

### `main.cpp` — boot & super-loop

**`setup()`** runs, in strict order:

1. `stateSyncBegin()` — create the shared-state mutex **before** anything can lock it.
2. `LittleFS.begin(true)` — mount the flash filesystem (format on failure).
3. `storeBegin()` — load mappings + poses (self-heals to defaults if missing/corrupt).
4. `servosBegin()` — attach the 6 servos, home the hand.
5. `batteryBegin()` — first ADC read (so the dashboard never shows 0 % at boot).
6. `uartLinkBegin()` — bring up `Serial2` for the label stream.
7. `webBegin()` — start the WiFi AP, REST routes, WebSocket, and static serving.

**`loop()`** calls, every pass:

```cpp
uartLinkUpdate();  // drain UART RX, run the fail-safe watchdog
servosUpdate();    // step the smooth interpolation (writes PWM)
batteryUpdate();   // periodic ADC sample (~2 Hz)
webUpdate();       // WebSocket housekeeping + telemetry push
storeFlush();      // persist any pending mapping/pose edits to flash
```

The web/WebSocket handlers do **not** run here — they run on the separate
`async_tcp` task (see §6).

### `dispatch.cpp` / `dispatch.h` — the convergence point

- **`applyAction(action, source)`** — resolves an action name to angles (built-in
  first, then saved-pose lookup), drives the servos, and records who commanded it
  in `g_status`. Returns `false` for an unknown action. The whole thing runs
  under one lock so a concurrent pose delete/edit can't pull the pose out from
  under the pointer.
- **`applyLabel(label)`** — Contract A entry point. Stamps the fail-safe clock,
  marks Link A up, looks up the label's mapping, and calls `applyAction(..., Cue)`.
- Also **owns the one global `g_status`** and the shared-state mutex accessors
  (`stateSyncBegin()`, `stateMutex()`).

### `servos.cpp` / `servos.h` — Layer 1 servo core

Direct GPIO PWM via ESP32Servo, non-blocking smooth interpolation, and the
built-in gesture table. Covered in detail in §7.

### `uart_link.cpp` / `uart_link.h` — Contract A listener + fail-safe

- Reads `Serial2` byte-by-byte, assembling newline-terminated lines into a
  fixed buffer (`UART_LINE_MAX` = 64). Trailing `\r` is trimmed (tolerates
  Windows senders). Over-long lines are dropped and resync at the next newline.
- Validated labels go to `applyLabel()`; unknown labels are logged and ignored.
- **Fail-safe watchdog:** if no valid label has arrived within
  `FAILSAFE_TIMEOUT_MS` (3 s), Link A is flagged **down**. Per the design, the
  hand **holds** its current position — it never goes limp or snaps to a default.

### `battery.cpp` / `battery.h` — 2S LiPo monitor

- Samples the ADC every 500 ms, smooths with an **exponential moving average**
  (α = 0.2) to tame the noisy ESP32 ADC.
- Converts raw → volts using the divider ratio, then volts → percentage against
  the full/empty thresholds, clamped to 0–100 %. Publishes into `g_status`.

### `store.cpp` / `store.h` — persistence

Mappings + poses, RAM working set backed by LittleFS JSON files. Covered in §8.

### `webserver.cpp` / `webserver.h` — Layers 2–4

WiFi AP, REST API, WebSocket telemetry, static file serving. Covered in §9.

### `status.h` — the shared snapshot

The single `SystemStatus g_status` struct every module writes its slice of:

```cpp
struct SystemStatus {
    float     batteryV;                 // smoothed volts
    int       batteryPct;               // 0..100
    bool      linkAConnected;           // valid label within FAILSAFE_TIMEOUT_MS
    char      lastLabel[UART_LINE_MAX]; // last valid label from the Pi
    char      lastAction[32];           // what it resolved to
    char      activePose[32];           // "" = none / built-in
    CmdSource source;                   // None | Cue | Manual
    uint32_t  lastLabelMs;              // millis() of last valid label
};
```

### `sync.h` — the mutex (see §6)

---

## 6. Concurrency & thread-safety model

This is the subtle heart of the firmware. **Two FreeRTOS tasks touch the same
data:**

| Task | Runs | Touches |
|---|---|---|
| Arduino **`loopTask`** | `uartLinkUpdate`, `servosUpdate`, `batteryUpdate`, `webUpdate` housekeeping, `storeFlush` | everything |
| **`async_tcp`** task | every HTTP request + WebSocket event handler (ESPAsyncWebServer / AsyncTCP) | `g_status`, servo arrays, `mappings[]`, `poses[]` |

Without care, a web write could tear a value mid-read — e.g. `deletePose()`
shifting the `poses[]` array exactly while a cue is resolving a pointer into it.

**The rule:** every access to shared mutable state — on *either* task — is wrapped
in a **`StateLock`** (RAII scoped lock over one recursive mutex, defined in
[`sync.h`](src/sync.h)):

```cpp
struct StateLock {
    StateLock()  { xSemaphoreTakeRecursive(stateMutex(), portMAX_DELAY); }
    ~StateLock() { xSemaphoreGiveRecursive(stateMutex()); }
};
```

Design points:

- **Recursive** — nested locked calls on the same task are fine
  (`applyAction` → `servosSetTargets` → `servoSetTarget` all lock).
- **Critical sections stay short and RAM-only.** Slow work — LittleFS flash
  writes — is *deferred*: web handlers set a dirty flag, and `storeFlush()` on the
  loop task does the actual write **outside** the lock. No flash I/O ever happens
  inside an async web handler or while holding the mutex.
- The **actual PWM hardware write** happens only in `servosUpdate()` on the loop
  task; web/UART callers only set *targets*.

This "RAM under lock, flash deferred to the loop task" pattern is what keeps the
async web server from ever stalling on flash or corrupting shared state.

---

## 7. Servo control in detail

All angles are **logical degrees 0–180** in canonical channel order. ESP32Servo
maps `0..180` onto each channel's `attach()` pulse-width window
(`SERVO_PULSE_MIN_US`..`SERVO_PULSE_MAX_US`, default 500–2500 µs at 50 Hz).

### Smooth, non-blocking interpolation

Servos are never snapped to a new angle (that stresses gears and cables).
Instead each channel **eases** from its start angle to its target over
`MOVE_DURATION_MS` (400 ms), stepped every `MOVE_STEP_MS` (15 ms):

- `servoSetTarget()` / `servosSetTargets()` record `startAngle`, `tgtAngle`, and a
  per-channel `moveStart` timestamp (under lock).
- `servosUpdate()` runs on the loop task: for each channel not yet at target, it
  computes `t = elapsed / MOVE_DURATION_MS` (clamped to 1.0), linearly
  interpolates `start + (tgt-start)*t`, and writes the new angle only if it
  changed. Cheap when idle.

### Built-in gestures & the wrist synthesis

Static gestures live in `BUILTIN_TABLE`. `wrist_left` / `wrist_right` are **not**
in the table — they'd otherwise force finger angles. Instead
`builtinActionAngles()` detects them and **synthesizes** a target on the fly:
copy the live finger angles from `curAngle[]`, override only channel 5 with the
wrist endpoint (180 or 0). This is why wrist rotation preserves whatever the
fingers were already doing.

### Bench-friendly degradation

`servosBegin()` reserves the four LEDC timers and attaches all six pins. If any
pin fails to attach, `hwPresent` goes false and the firmware **keeps running**
without driving PWM — angles are still tracked in software, so the **web app,
cue stream, and telemetry all work on a bare bench with no servos wired**. Great
for development.

On boot the hand **homes** to open fingers + wrist neutral (the initial values of
the `curAngle[]` / `tgtAngle[]` arrays).

---

## 8. Persistence: mappings & poses

[`store.cpp`](src/store.cpp) keeps two things in RAM as the source of truth and
mirrors them to LittleFS JSON so they survive a power cycle:

- **`mappings[]`** — one action string per Contract-A label (indexed to
  `VALID_LABELS`), persisted to `/mappings.json`.
- **`poses[]`** — up to `POSES_MAX` (24) named poses, each a name (≤32 chars) +
  6 angles, persisted to `/poses.json`.

Key behaviours:

- **Self-healing defaults.** `storeBegin()` writes defaults if a file is missing.
  Crucially it also handles a file that *exists but won't parse* (e.g. power loss
  mid-write): it rewrites defaults and reloads, so the tables can never be left
  empty (which would make every cue silently no-op forever). Defaults are
  compiled in as `PROGMEM` strings and kept identical to the shipped
  `data/*.json`.
- **Deferred writes.** Mutations (`setMappings`, `upsertPose`, `deletePose`) edit
  RAM under the lock and set a `volatile` dirty flag. `storeFlush()` on the loop
  task drains the flags and does the actual `serializeJson`→file write **off** the
  async task and **outside** the lock.
- **Dangling-mapping repair.** Deleting a pose that some label maps to rebinds
  that label to `relax`, so the cue keeps doing something safe instead of pointing
  at a pose that no longer exists. (The web app mirrors this exact rule.)
- **Input hardening.** Angles are `constrain()`-ed to 0–180 on load and on write;
  poses with the wrong angle count or empty names are skipped; unknown labels in a
  mapping POST are ignored.

Default seed pose: `ok_sign` = `[120, 100, 10, 10, 10, 90]`.

---

## 9. Web server & REST/WebSocket API

Built on **ESPAsyncWebServer** + **AsyncTCP** (pinned to the actively-maintained
`ESP32Async` GitHub forks for reproducibility). Serves on port 80 over the
device's own WiFi soft-AP.

### WiFi access point

| Setting | Value |
|---|---|
| SSID | `ProstheticHand` |
| Password | `inmoov1234` (≥8 chars; empty string ⇒ open AP) |
| Channel | 6 |
| Max clients | 4 |

No internet is provided or required — **every** asset is served locally from
LittleFS (no CDNs anywhere).

### REST endpoints (all JSON)

| Method | Path | Body | Purpose |
|---|---|---|---|
| `GET` | `/api/state` | — | full snapshot: `status` + `mappings` + `poses` (atomic) |
| `GET` | `/api/mappings` | — | label → action table |
| `POST` | `/api/mappings` | `{label:action, …}` | replace mappings, persist |
| `GET` | `/api/poses` | — | saved poses |
| `POST` | `/api/poses` | `{name, angles[6]}` | add/replace a pose |
| `DELETE` | `/api/poses/<name>` | — | delete a pose (name is percent-encoded) |
| `POST` | `/api/pose/apply` | `{name}` | apply a saved pose to the hand |
| `POST` | `/api/servo` | `{channel, angle}` | nudge one channel (0–5, 0–180) |
| `POST` | `/api/relax` | — | open/relax the hand |
| `WS` | `/ws` | — | server pushes `{type:"status", …}` at ~6–7 Hz |

Implementation notes:

- **JSON body buffering.** POST bodies arrive chunked; a small wrapper
  (`jsonBody`) buffers them into a `malloc`'d buffer (so ESPAsyncWebServer's
  `free(_tempObject)` on teardown is correct even if a client aborts mid-upload),
  parses once complete, then frees.
- **Regex DELETE route.** `DELETE /api/poses/<name>` uses a regex route
  (`ASYNCWEBSERVER_REGEX=1`) and a custom `urlDecode()` so poses named with spaces
  or symbols round-trip correctly with the dashboard's `encodeURIComponent`.
- **Snapshot consistency.** `/api/state` takes a single `StateLock` across status
  + mappings + poses so the client always gets a coherent picture.

### WebSocket telemetry

- On connect, the server immediately pushes one full status snapshot so the client
  is instantly current.
- `webUpdate()` pushes `{type:"status", …}` to all connected clients every
  `WS_PUSH_INTERVAL_MS` (150 ms ≈ 6–7 Hz) — but only if at least one client is
  connected. It also runs `ws.cleanupClients()` housekeeping each pass.

The status payload includes: `battery_pct`, `battery_v`, `linkA_connected`,
`last_label`, `last_action`, `active_pose`, `source`, and the live
`servo_angles[6]`.

### Static serving

`serveStatic("/", LittleFS, "/")` with `index.html` as the default file.
`prep_fs.py` gzips the assets, and ESPAsyncWebServer transparently serves
`foo.gz` when `foo` is requested. Unknown paths 404.

---

## 10. The web dashboard

A **dependency-free** (no framework), single-page clinical UI in
[`data/`](data/): [`index.html`](data/index.html) + [`app.js`](data/app.js) +
[`style.css`](data/style.css) + [`hand3d.js`](data/hand3d.js). It's phone-first
(bottom tab-bar navigation) with four screens:

| Screen | What |
|---|---|
| **Home** | 3D hand twin, greeting, battery + EEG-link chips, live "last cue → action" HUD with a rolling feed, a fail-safe banner, and a persistent **Relax** button |
| **Mappings** | edit each EEG cue's action (built-in or saved pose) and save |
| **Poses** | gallery of saved poses (with mini SVG thumbnails); a live pose **editor** with per-channel sliders, preset starting points, and an SVG preview |
| **Settings** | profile (name, device, left/right hand), dark-mode toggle, reset-app-data |

### MOCK vs LIVE

The app runs in one of two modes, chosen automatically:

- **MOCK** — when there's no ESP32 backend: `file://`, an explicit `?mock`, or a
  `localhost`/`127.*`/`0.0.0.0` host. It uses fake telemetry and a **simulated EEG
  cue stream** (random labels every ~5 s, occasional battery drain and simulated
  link dropouts so the fail-safe banner is exercised). The API layer becomes a set
  of no-ops. This lets you **build and preview the entire app in a browser with no
  hardware attached** — shown with a "Preview · mock data" banner.
- **LIVE** — on real hardware: it hydrates from `GET /api/state`, then opens the
  `/ws` WebSocket for live status, sends control actions to the POST/DELETE
  endpoints, and **homes the hand** (open + wrist neutral) on connect. The
  WebSocket auto-reconnects with a capped backoff.

### Client-side niceties

- **Local persistence.** Profile, poses, and mappings are cached in
  `localStorage` (`inmoov.v1`) and re-hydrated on load; the saved theme is applied
  *before first paint* to avoid a flash.
- **SVG hand preview.** A pure-SVG hand (`handMarkup`) renders pose thumbnails and
  the editor's live preview — no WebGL needed for those.
- **Mirrors firmware rules.** Deleting a pose rebinds any mapping that pointed at
  it to `relax`, exactly like the firmware, so mock and live behave identically.
- **Left/right hand** setting mirrors the 3D twin to match the user's physical
  hand.

---

## 11. The 3D hand twin

[`data/hand3d.js`](data/hand3d.js) renders a **live 3D twin** of the hand on the
Home screen using **Three.js** (vendored locally in `data/vendor/`, no CDN):

- **Default:** a **procedural** InMoov hand + forearm built to the real assembly's
  proportions (hand ≈ 187×146×71 mm, four 3-segment fingers, a 2-segment thumb, a
  flat palm plate, a tapered forearm shell). It **articulates** with app state —
  `setPose(angles)` drives finger curl and wrist rotation; you can drag to orbit;
  it waves on load.
- **Optional:** load a static realistic GLB instead via `?glb=models/<file>`
  (auto-stood-up, auto-fit, studio-lit). `?lite` skips shadows/env-map for slower
  devices.

Crucially, the 3D twin is **best-effort**: it's wrapped in try/catch so a WebGL
failure never stops the dashboard, cue stream, or telemetry from working — the
2D/SVG views and all controls keep functioning.

`data/models/` holds development GLBs (`scene.gltf`/`scene.bin`, `_test_duck.glb`)
that are **excluded** from the flash image by `prep_fs.py`; a future
`models/hand.glb` would be included automatically.

---

## 12. Build system, partitions & the FS image

Built with **[PlatformIO](https://platformio.org/)** (Arduino-ESP32 framework).

### Environments ([`platformio.ini`](platformio.ini))

| Env | Board | Flash | Partitions | Use |
|---|---|:--:|---|---|
| **`esp32dev_4mb`** *(default)* | `esp32dev` | 4 MB | `partitions_4mb.csv` | the real hardware (ESP32-D0WD-V3) |
| `esp32dev_8mb` | `esp32dev` | 8 MB | `partitions_8mb.csv` | alternate; only if you move to a true 8 MB board — hands more flash to LittleFS for the 3D stretch goal |

Shared settings: `lib_ldf_mode = deep+` (so the async-server forks resolve
transitive includes), LittleFS filesystem, 115200 monitor, 921600 upload.

### Libraries (`lib_deps`)

```
madhephaestus/ESP32Servo @ ^3.0.5
bblanchon/ArduinoJson    @ ^7.2.0
https://github.com/ESP32Async/AsyncTCP.git
https://github.com/ESP32Async/ESPAsyncWebServer.git
```

The async server + TCP forks are pinned by **git URL** on purpose — the registry
naming of the many ESPAsyncWebServer/AsyncTCP forks is a frequent source of build
breakage.

### Build flags

- `-DCORE_DEBUG_LEVEL=3` — Arduino-ESP32 log verbosity.
- `-DASYNCWEBSERVER_REGEX=1` — enables regex routes + `request->pathArg()` (needed
  for `DELETE /api/poses/<name>`).

### Partition table (4 MB, [`partitions_4mb.csv`](partitions_4mb.csv))

The stock `min_spiffs.csv` gives the filesystem only 128 KB — nowhere near enough
for the dashboard. This custom table drops OTA to a single app slot:

| Partition | Size | Purpose |
|---|:--:|---|
| `nvs` | 20 KB | non-volatile storage |
| `otadata` | 8 KB | (unused, single-slot) |
| `app0` | **1.75 MB** | the firmware |
| `spiffs` | **~2.1 MB** | **LittleFS** web assets (label *must* be `spiffs` even though formatted LittleFS) |
| `coredump` | 64 KB | crash dumps |

### `prep_fs.py` — staging the FS image

A PlatformIO `pre:` extra-script ([`tools/prep_fs.py`](tools/prep_fs.py)) that,
before the FS image is built, stages a copy of `data/` into the build dir and:

- **gzips** text assets (`.html .css .js .gltf .svg .txt .map`) at level 9 —
  Three.js drops from ~600 KB to ~150 KB, and the server serves the `.gz`
  transparently;
- **keeps `mappings.json` / `poses.json` raw** — the firmware reads *and rewrites*
  them at runtime, so they can't be gzipped;
- **excludes** dev-only models (`_test_duck.glb`, `scene.gltf/bin`, `license.txt`)
  and OS junk (`.DS_Store`);
- leaves the real `data/` untouched, so `open data/index.html` / a local
  `http.server` still work for UI development.

---

## 13. Tooling

### `tools/fake_pi.py` — pretend to be the Raspberry Pi

Streams Contract-A labels to the ESP32 over serial so you can build and test the
whole hand + dashboard **before the real EEG classifier exists**. Requires
`pyserial`.

```bash
python3 tools/fake_pi.py --list                    # find the serial port
python3 tools/fake_pi.py --port <port>             # interactive menu (pick a label)
python3 tools/fake_pi.py --port <port> --once clinch
python3 tools/fake_pi.py --port <port> --auto 2.0  # random label every 2 s
```

Its `VALID_LABELS` list is kept identical to `contracts.h`; it warns if you send a
label the firmware would ignore.

### `tools/prep_fs.py`

The build-time FS staging script — see §12.

---

## 14. Configuration reference

Every hardware/system tunable lives in [`include/config.h`](include/config.h) as a
`#define`, so it can be tuned without touching logic. Key groups:

| Group | Constants | Default |
|---|---|---|
| Firmware | `FW_VERSION` | `"0.5.0-layer4"` |
| Servo PWM | `SERVO_PWM_FREQ_HZ` | 50 Hz |
| Channel map | `CH_*`, `SERVO_PIN_*`, `SERVO_COUNT` | see §3 |
| Pulse limits | `SERVO_PULSE_MIN_US`, `SERVO_PULSE_MAX_US` | 500 / 2500 µs |
| Angle range | `SERVO_ANGLE_MIN`, `SERVO_ANGLE_MAX` | 0 / 180 |
| Wrist | `WRIST_ANGLE_NEUTRAL/LEFT/RIGHT` | 40 / 180 / 0 |
| Smoothing | `MOVE_DURATION_MS`, `MOVE_STEP_MS` | 400 / 15 ms |
| UART | `UART_RX_PIN`, `UART_TX_PIN`, `UART_BAUD`, `UART_LINE_MAX` | 16, 17, 115200, 64 |
| Fail-safe | `FAILSAFE_TIMEOUT_MS` | 3000 ms |
| Battery | `BATT_ADC_PIN`, `BATT_DIVIDER_RATIO`, `BATT_VOLT_FULL/EMPTY`, … | 34, 4.03, 8.40 / 6.40 V |
| WiFi AP | `AP_SSID`, `AP_PASSWORD`, `AP_CHANNEL`, `AP_MAX_CLIENTS` | ProstheticHand, inmoov1234, 6, 4 |
| WebSocket | `WS_PUSH_INTERVAL_MS` | 150 ms |
| FS paths | `PATH_MAPPINGS`, `PATH_POSES` | `/mappings.json`, `/poses.json` |

> The `BATT_DIVIDER_RATIO`, pulse limits, and wrist endpoints in particular are
> marked as assumptions to calibrate on the bench with a multimeter.

---

## 15. Safety features

Safety is designed in, not bolted on:

- **Single dispatch point** — cue and app paths can't command contradictory
  states; the last command wins and everyone sees the same `g_status`.
- **Fail-safe hold** — lose the EEG link for 3 s and the hand *holds* position; it
  never goes limp or snaps to a default.
- **Smooth interpolation** — no snapping; protects gears and cabling.
- **Per-channel travel limits** — pulse-width windows (tightenable per channel)
  physically bound how far a finger/wrist can be driven; all angles are
  `constrain()`-ed to 0–180.
- **Battery cutoff awareness** — `BATT_VOLT_EMPTY` (6.40 V) maps to 0 % to protect
  the 2S LiPo cells; the dashboard surfaces low/critical bands.
- **Self-healing persistence** — corrupt config files never brick the cue path.
- **Graceful HW absence** — missing servos degrade to software-only tracking, so
  nothing crashes on the bench.
- **No cloud, no internet** — the whole system is offline by construction; no
  external attack surface, no CDN dependencies.
- **Concurrency guard** — one recursive mutex prevents torn reads/writes between
  the loop and async-web tasks.

---

## 16. Running & developing

### A. Web dashboard in a browser (no hardware)

The dashboard auto-enters MOCK mode on localhost. Serve `data/`:

```bash
cd data
python3 -m http.server 8000 --bind 127.0.0.1
# open http://127.0.0.1:8000/
```

You'll see the "Preview · mock data" banner, live fake telemetry, and a simulated
cue stream. All controls work against the in-browser simulator.

### B. Build & flash the firmware (needs the ESP32)

```bash
pio run                       # compile (default env: esp32dev_4mb)
pio run --target upload       # flash firmware
pio run --target uploadfs     # build + upload the LittleFS web assets
pio device monitor -b 115200  # serial console
```

Then join WiFi **`ProstheticHand`** (password `inmoov1234`) and browse to the
ESP32's IP to reach the real dashboard.

### C. Simulate the Raspberry Pi (no EEG rig)

With the ESP32 on a USB-serial cable:

```bash
pip install pyserial
python3 tools/fake_pi.py --list
python3 tools/fake_pi.py --port <port> --auto 2.0
python3 tools/fake_pi.py --port <port> --once clinch
```

### Typical dev loop

1. Iterate on the UI with the browser MOCK mode (fast, no flashing).
2. Tweak firmware constants in `config.h`, `pio run` to compile.
3. Flash firmware + FS, monitor serial for the boot banner and per-subsystem `[OK]`
   lines.
4. Drive test cues with `fake_pi.py`; watch them on the live dashboard.

---

## 17. File-by-file map

```
platformio.ini          build envs (esp32dev_4mb default, esp32dev_8mb alt), libs, flags
partitions_4mb.csv      1.75 MB app + ~2.1 MB LittleFS (the real board)
partitions_8mb.csv      alternate table for a true 8 MB board
.gitignore              ignores .pio/, __pycache__, .DS_Store, generated .vscode

include/
  config.h              EVERY hardware/system tunable (pins, limits, timers, AP, …)
  contracts.h           Contract A labels + Contract B built-in actions (+ validators)

src/
  main.cpp              boot order + the non-blocking super-loop
  dispatch.{h,cpp}      action resolution shared by cue + app paths; owns g_status + mutex
  status.h              the single SystemStatus g_status snapshot struct
  sync.h                the recursive StateLock mutex guarding all shared state
  servos.{h,cpp}        GPIO PWM servo core, smooth interpolation, built-in gestures
  uart_link.{h,cpp}     Serial2 label listener (Contract A) + fail-safe watchdog
  battery.{h,cpp}       ADC sampling + EMA smoothing for the 2S LiPo
  store.{h,cpp}         mappings + poses persistence (LittleFS + ArduinoJson)
  webserver.{h,cpp}     WiFi AP + REST API + WebSocket telemetry + static serving

data/                   the web dashboard (served from LittleFS)
  index.html            4-screen SPA shell (home / mappings / poses / settings)
  app.js                all front-end logic, MOCK + LIVE modes, API layer
  style.css             clinical UI styling (light/dark)
  hand3d.js             procedural/GLB 3D hand twin (Three.js), best-effort
  mappings.json         default label→action table (also compiled into firmware)
  poses.json            default saved poses (seed: ok_sign)
  vendor/               three.min.js, GLTFLoader.js (local, no CDN)
  models/               dev GLBs (excluded from the flash image by prep_fs.py)

tools/
  prep_fs.py            PlatformIO pre-script: gzips data/ into the FS image
  fake_pi.py            serial label sender that impersonates the Pi classifier
```

---

## 18. Status, roadmap & known notes

### Current status

- **Layers 0–4 are implemented** and building: persistent config, servo core,
  UART cue listener + fail-safe, battery monitor, WiFi AP, REST API, WebSocket
  telemetry, and the gzipped dashboard served from LittleFS.
- The **web dashboard** is fully usable in MOCK mode in any browser, and wired to
  the LIVE firmware API.

### Roadmap / stretch goals

- **Layer 5 (8 MB board):** ship a decimated `models/hand.glb` and give LittleFS
  ~4.8 MB (already provisioned in `partitions_8mb.csv`).
- Per-channel pulse-limit calibration on the bench (tighten `PULSE_MIN/MAX_US`
  arrays in `servos.cpp`).
- Battery divider calibration against a multimeter.
- The real EEG classifier on the Pi replacing `fake_pi.py`.

### Notes & things to keep in sync

- **`BUILTIN_TABLE` (servos.cpp) ↔ `ACTION_ANGLES` (app.js)** must match, or the
  on-screen and physical hands diverge.
- **`VALID_LABELS` (contracts.h) ↔ `fake_pi.py` ↔ `app.js` `LABELS`** must match.
- **Firmware defaults (store.cpp) ↔ `data/mappings.json` / `data/poses.json`** —
  the FS image ships the same content the firmware would self-heal to.
- The seed pose `ok_sign` uses a wrist value of **90** (from the historic default),
  whereas built-in gestures use wrist **neutral = 40**. If you re-baseline the
  wrist neutral, revisit that seed pose.
- The filesystem partition label **must** be `spiffs` even though it's formatted
  LittleFS — the Arduino-ESP32 image tooling keys off that label.

---

*Generated as a detailed companion to the project. For the concise version see
[README.md](README.md); for the authoritative tunables see
[include/config.h](include/config.h) and the contracts in
[include/contracts.h](include/contracts.h).*
