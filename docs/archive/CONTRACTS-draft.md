# System Contracts

These two contracts are the foundation every layer depends on. They are mirrored
in code (`include/contracts.h`) and must not drift.

```
EEG headset -> Raspberry Pi 5 -(UART, Contract A)-> ESP32 -(WiFi, Contract B)-> browser
```

---

## Contract A — UART message format (Pi → ESP32)

* Physical link: ESP32 `Serial2`, **115200 baud** (`UART_BAUD`), 8N1.
  Pi TX → ESP32 GPIO16 (RX), Pi RX ← ESP32 GPIO17 (TX), common ground.
* The Pi sends **one label per line**, newline-terminated ASCII:
  `jaw_clench\n`, `double_blink\n`, …
* The ESP32 parses each line, looks the label up in the mapping table, and
  executes the mapped action.
* **Unknown labels are logged and ignored** (never crash, never move).

**Valid labels** (editable in `contracts.h` / `tools/fake_pi.py`):

| label           | meaning                  |
|-----------------|--------------------------|
| `eye_blink`     | single eye blink         |
| `double_blink`  | two quick blinks         |
| `jaw_clench`    | jaw clench               |
| `eyebrow_raise` | eyebrow raise            |
| `look_left`     | gaze/saccade left        |
| `look_right`    | gaze/saccade right       |
| `rest`          | neutral / no artifact    |

---

## Contract B — Web API (ESP32 serves these over the AP)

Static + REST + WebSocket, all served locally from LittleFS (no internet, no CDNs).

| Method | Path                   | Purpose |
|--------|------------------------|---------|
| GET    | `/`                    | the web app (`index.html`) |
| GET    | `/api/status`          | live status (see shape below) |
| GET    | `/api/mappings`        | current label→action map |
| POST   | `/api/mappings`        | replace/update the map (persist to LittleFS) |
| GET    | `/api/poses`           | list of saved poses |
| POST   | `/api/poses`           | create/update a named pose (persist) |
| DELETE | `/api/poses/{name}`    | delete a pose |
| POST   | `/api/servo`           | live-set ONE servo angle (pose-editor preview) |
| POST   | `/api/pose/apply`      | apply a saved pose by name immediately |
| POST   | `/api/relax`           | emergency open/relax |
| WS     | `/ws`                  | push live status ~5–10 Hz (no polling) |

### `GET /api/status` response
```json
{
  "battery_pct": 87,
  "battery_v": 7.92,
  "linkA_connected": true,
  "last_label": "jaw_clench",
  "last_label_ms_ago": 412,
  "servo_angles": [120, 100, 10, 10, 10, 90],
  "active_pose": "close_fist",
  "failsafe": false
}
```

### `POST /api/mappings` request body
Full map object (server replaces the stored map and persists it):
```json
{ "jaw_clench": "close_fist", "double_blink": "pinch", "...": "..." }
```

### `POST /api/poses` request body
```json
{ "name": "ok_sign", "angles": [120, 100, 10, 10, 10, 90] }
```

### `POST /api/servo` request body
```json
{ "channel": 1, "angle": 95 }
```

### `POST /api/pose/apply` request body
```json
{ "name": "pinch" }
```

### `WebSocket /ws` push message
Same shape as `GET /api/status`, sent every `WS_PUSH_INTERVAL_MS`.

---

## Data models

### Mapping  (`/mappings.json`)
A flat object: each valid label → an **action string**, where the action is
**either a built-in action OR the name of a saved pose**.
```json
{ "jaw_clench": "close_fist", "double_blink": "pinch" }
```

### Pose  (`/poses.json`)
```json
{ "poses": [ { "name": "pinch", "angles": [a0,a1,a2,a3,a4,a5] } ] }
```
`angles` has exactly **6** entries (degrees, 0–180), in channel order:
`[thumb, index, middle, ring, pinky, wrist]`.

### Built-in actions (implemented in firmware)
`open_hand`, `close_fist`, `point`, `pinch`, `wrist_left`, `wrist_right`, `relax`
— plus any saved pose name is also a valid action.

---

## Fail-safe
If no valid label arrives within `FAILSAFE_TIMEOUT_MS` (default 3000 ms), the
hand **holds its current position** — it does not go limp and does not snap to a
default. The UI also exposes an emergency **relax/open** button (`POST /api/relax`).
