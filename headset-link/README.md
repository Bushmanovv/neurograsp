# headset-link — the laptop↔Pi transport

Two things live here, in this order:

1. **[`virtual_headset.py`](virtual_headset.py)** — turns any recorded EEG session
   into the exact `.edf` the classifier will accept.
2. **[The dashboard](#the-headset-dashboard)** — five buttons on the laptop; each
   ships a 5 s `.edf` snippet to the Pi over TCP and shows what the model said.

The laptop *is* the headset. There is no separate acquisition device in the loop:
a recorded snippet is played to the Pi exactly as a live one would be, so the Pi
and the hand cannot tell the difference.

---

# virtual_headset

Conditions a recorded EEG session into the exact `.edf` that the classifier's
`load_edf` accepts: all 19 canonical channels, correctly named, in `config.ALL_CH`
order, at 200 Hz, with the labels CSV embedded as EDF+ annotations.

## Install

```bash
pip install mne pandas edfio     # edfio is the EDF *export* backend
```

`check` only needs `mne`; `build` also needs `edfio`. Both are imported lazily,
so `check` works on a machine without the export backend.

## Usage

Read-only montage report — writes nothing:

```bash
python virtual_headset.py check --in session.edf
```

Produce the classifier-ready file:

```bash
python virtual_headset.py build --in session.edf --labels labels.csv --out ready.edf
```

## Channel naming

The canonical names come verbatim from `eeg_bci/config.py::ALL_CH`, which
carries a `-Ref` suffix:

```
Fp1-Ref, Fp2-Ref, Fz-Ref, F8-Ref, F7-Ref, F4-Ref, F3-Ref, C4-Ref, C3-Ref,
O2-Ref, P3-Ref, Cz-Ref, O1-Ref, P4-Ref, Pz-Ref, T6-Ref, T5-Ref, T4-Ref, T3-Ref
```

`load_edf` compares channel names by exact string against that list, so writing
bare `Fp1` would make it report all 19 channels missing. `--naming bare` emits
`Fp1`-style names if some other consumer wants them; the default is `ref`.

Normalization of source names, in order:

1. Strip a leading `EEG ` / `POL ` prefix.
2. Keep the token before the first `-`, `_`, or space: `EEG Fp1-REF` -> `Fp1`,
   `Cz-LE` -> `Cz`.
3. Uppercase for matching.
4. Remap modern 10-10 to the 10-20 names config uses: `T7`->`T3`, `T8`->`T4`,
   `P7`->`T5`, `P8`->`T6`.
5. Anything that isn't one of the 19 electrodes (`EKG`, `Status`, `A1`, ...) is
   ignored.

`Cz` is a channel, **not** a reference marker. Stripping reference *tokens*
anywhere in a name deletes the real `Cz` channel, because `Cz` is itself a
common reference (`Fp1-Cz`). Taking the first token before the separator is what
avoids that; `tests/test_channels.py::test_cz_is_never_eaten` pins it.

## Labels CSV

Column names vary, so onset / label / duration / end columns are auto-detected
(`onset`, `time`, `start_time`, ...; `label`, `event`, `side`, ...). Each row
becomes one annotation. If there is no duration column but there is an end
column, `duration = end - onset`.

Overrides, when auto-detection can't win:

```bash
python virtual_headset.py build --in session.edf --labels labels.csv --out ready.edf \
    --time-unit ms --time-col t_ms --label-col evt
```

`--time-unit ms` scales every time column (onset, duration, end) by 1/1000.
`--dur-col` and `--end-col` are available too.

## Build steps

rename matched channels to canonical -> pick and reorder to exactly the 19 in
`ALL_CH` order (extras dropped) -> resample to 200 Hz if the source rate differs
-> attach CSV labels as annotations -> write via MNE's EDF export.

If **any** of the 19 channels is missing after normalization, the build stops and
prints exactly which ones. It never writes a partial file: the montage is checked
before anything is written, and the export goes to a temp file that is atomically
renamed into place only on success.

---

# The headset dashboard

**The laptop is the headset.** Five buttons; each sends a 5 s `.edf` snippet over
TCP to the Raspberry Pi. The Pi already has the model — it writes the bytes to a
file and runs its existing pipeline, then sends back what the model printed.
**Nothing in your classifier project changes, because the payload is a plain EDF.**

```
laptop                                            RPi5 (systemd, headless)
+------------------------+                        +--------------------------+     UART
| dashboard.py, 5 buttons|  "EDF1"|id|len|.edf    | pi_service.py            |  Contract A
| plot of the snippet    | -------- TCP --------> |   model resident in RAM  | ----------> ESP32 hand
| s0..s4.edf, 212 KiB    |                        |   `rest` heartbeat, idle |
|                        | <--- "RES1"|len|json --|   your inference.py path |
+------------------------+                        +--------------------------+
```

The length prefix exists because TCP is a stream: one open link carries every
button press, and the Pi has to know where each snippet ends. The reply is framed
for the same reason.

```bash
# on the Pi -- or let systemd start it at boot, see "Deploying on the RPi5"
python pi_service.py --project ~/neurograsp/eeg-classifier

# on the laptop
python dashboard.py --host raspberrypi.local     # then open http://127.0.0.1:8080
```

Press a button (or `1`–`5`): the page draws the snippet, ships it, and shows the
exit code and output of your `--cmd`. The dot next to *Link to the Pi* goes green
on its own when the receiver is up, and the link redials if the Pi restarts. One
snippet is in flight at a time, exactly as the board behaved.

`--verdict-timeout` (default 60 s) bounds the wait for the model. A Pi running
`--no-reply` never answers; the page then says *delivered, no verdict* instead of
hanging, and you read the result off the Pi's own terminal.

The plot is decoded from the very bytes that went on the wire — `edf.py` is a
~90-line EDF reader, so the dashboard neither imports `mne` nor risks drawing
something other than what it sent. It is 19 stacked lanes, not 19 colours:
identity comes from the channel label, and the single accent is reserved for the
four channels `window_activity` actually reads (Fp1, Fp2, T3, T4).

Display applies per-channel DC removal, then decimates 200 → 40 Hz **through an
anti-alias low-pass**. This matters: these recordings carry ~92% of their power in
the 50 Hz mains, and plain every-Nth-sample decimation folds it onto |50 − 40| =
10 Hz, drawing a clean 10 Hz "rhythm" that does not exist and inflating the
autoscale ~21×. The browser therefore shows the sub-20 Hz band; the Pi receives
the `.edf` intact and notches it itself.

## The snippets

```bash
python make_snippets.py --project ~/neurograsp/eeg-classifier
```

Cuts one verified 5 s window per command out of the real recordings and writes
`firmware/esp32_headset/data/s0.edf` … `s4.edf` (43,406 B each, 212 KiB total).
Each is read back through the Pi's own `load_edf` before it is accepted.

| file | class | command | verified with your `inference.py --file` |
|---|---|---|---|
| `s0.edf` | double_blink | `S` start/confirm | 3 × S |
| `s1.edf` | single_blink | `O` open hand | 4 × O |
| `s2.edf` | clinch | `C` close hand | 4 × C |
| `s3.edf` | bruxism_left | `L` rotate left | 3 × L |
| `s4.edf` | bruxism_right | `R` rotate right | 4 × R |

## Two receivers, and which one to run

Both speak the same frames, so the dashboard cannot tell them apart.

| | `pi_receive.py` | `pi_service.py` |
|---|---|---|
| what it does | writes the `.edf`, runs any `--cmd` | **the deployment**: model resident, UART held open |
| imports the model | never | yes, once at boot |
| per press | a fresh `python inference.py` (~10 s+ on a Pi) | ~0.75 s |
| `rest` heartbeat while idle | **no** | yes |
| use it for | the bench, any pipeline, no-model debugging | **the Pi, at boot** — see below |

`pi_receive.py` is standalone and stdlib-only — copy the single file next to your
project. It never imports the model.

```bash
python pi_receive.py --tcp-listen 5005 \
    --cmd 'python inference.py --file {edf}' --cwd ~/neurograsp/eeg-classifier
```

`{edf}` is substituted with the path it just wrote — swap in whatever command your
pipeline uses. It writes through a `.part` file so the model never sees a
half-written EDF, tees the command's output (the Pi keeps its live console, the
dashboard gets a copy), and re-accepts if the sender goes away.

**Do not deploy it this way.** Spawning `inference.py` per press is fine on the
bench and wrong in the field, for a reason that has nothing to do with speed: the
hand firmware fail-safes after 3 s without a Contract A line, and `inference.py`
only sends the `rest` heartbeat (`cfg.REST_HEARTBEAT_SEC` = 1.2 s) *while it is
streaming a clip*. It opens the port, streams, closes. Between button presses
nothing sends `rest`, so the hand goes limp 3 s after every command. That is what
`pi_service.py` exists to fix.

**Not port 5000** — macOS AirPlay Receiver listens there, so the dashboard would
connect to Control Center and the snippet would die mid-flight. The default is 5005.

No dashboard needed to exercise it — `host_send.py` speaks the same frame from the
command line, and both snippets below travel down one connection, exactly as two
button presses would:

```bash
python host_send.py firmware/esp32_headset/data/s0.edf firmware/esp32_headset/data/s4.edf --port 5005
```

## Deploying on the RPi5 — boots with no screen

> **There is now a script for this.** [`../raspberry-pi/install.sh`](../raspberry-pi/install.sh)
> does every step below and *generates* the systemd unit from the Pi's real paths
> and username rather than having you hand-copy one — a stale path in a copied unit
> file is the usual way this goes wrong. It also handles a Pi 5 trap these manual
> steps predate: on a Pi 5 `/dev/serial0` is the 3-pin debug connector, **not** GPIO
> 14/15, so the hand is on `/dev/ttyAMA0`. Follow
> [`../raspberry-pi/README_PI.md`](../raspberry-pi/README_PI.md) unless you want to
> understand each step by doing it by hand — which is what the rest of this section
> is for.

The Pi comes up, loads the model, opens the UART to the hand, starts the `rest`
heartbeat and listens. Nobody logs in; there is no monitor. You open the dashboard
on the laptop and press a button.

```
 power on ──► systemd ──► pi_service.py ──► model in RAM (once)
                                       ├──► /dev/serial0 held open, `rest` every 1.2 s
                                       └──► :5005, waiting for the laptop
```

Everything below is done once, over `ssh`.

**1 — Get a 64-bit OS.** `uname -m` must print `aarch64`. On 32-bit (`armv7l`)
there are no aarch64 wheels for scikit-learn/scipy/tslearn and the install will
try to compile them for an hour. Reflash with the 64-bit image instead.

**2 — Copy the repo to the Pi.** The classifier lives inside it
(`neurograsp/eeg-classifier`), so this is one folder. From the laptop:

```bash
rsync -av --exclude .venv --exclude DATA --exclude __pycache__ --exclude .git \
    ~/neurograsp pi@raspberrypi.local:~/
```

The excludes are not optional. `.venv` is ~486 MB of **macOS** binaries with
`/opt/homebrew` paths baked in — it cannot run on the Pi and a venv is not
relocatable anyway (step 3 builds a fresh one). `DATA/` is 39 MB of raw recordings
that inference never opens. What is left is ~36 MB, nearly all of it `models/` —
which *must* come across, because that is the thing being deployed.

**3 — Install the dependencies, pinned.**

```bash
cd ~/neurograsp/eeg-classifier
python3 -m venv .venv
.venv/bin/pip install -r ~/neurograsp/headset-link/deploy/requirements-pi.txt
```

`tslearn` pulls in `numba`/`llvmlite`; this takes a while on a Pi. Let it run.

The pins matter: a `.pkl` is pickled scikit-learn objects, so a different
scikit-learn either warns or refuses to unpickle. They are the versions the models
in `models/` were written with.

**4 — Give the Pi its UART.** `sudo raspi-config` → *Interface Options* → *Serial
Port*:

- login shell over serial → **No** (otherwise the console owns `/dev/serial0` and
  the hand receives your boot messages)
- serial port hardware → **Yes**

Then let the service write to it without being root, and reboot:

```bash
sudo usermod -aG dialout pi
sudo reboot
```

Using a USB-serial adapter instead of the GPIO pins? The port is then
`/dev/ttyUSB0` — change `EEG_SERIAL_PORT` in the unit file.

**5 — Prove it works before making it a service.** On the Pi:

```bash
cd ~/neurograsp/headset-link
EEG_GRADUATIO_PROJECT/.venv/bin/python pi_service.py \
    --project ~/neurograsp/eeg-classifier
```

Wait for `[boot] ready: listening on 0.0.0.0:5005`. You should already see
`rest` going out every 1.2 s — *before anyone presses anything*. That is the hand's
fail-safe being fed. Then, from the laptop:

```bash
python dashboard.py --host raspberrypi.local
```

Press a button. If it classifies and the hand moves, `Ctrl-C` and continue.

**6 — Make it start at boot.**

```bash
sudo cp ~/neurograsp/headset-link/deploy/eeg-headset.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eeg-headset
```

`enable` is what survives the reboot; `--now` also starts it immediately. It is
wired to `multi-user.target`, not `graphical.target`, so it comes up with no
monitor and nobody logged in, and `Restart=always` brings it back if it crashes
mid-demo.

**7 — Confirm, then pull the screen.**

```bash
journalctl -u eeg-headset -f          # live; the boot log and every window
systemctl is-enabled eeg-headset      # -> enabled
sudo reboot                           # with the monitor unplugged
```

After the reboot, from the laptop: `python dashboard.py --host raspberrypi.local`.
The *Link to the Pi* dot goes green on its own. The Pi never needed a screen.

### When it does not come up

| symptom | what it is |
|---|---|
| dot stays red, `Connection refused` | service is not up — `journalctl -u eeg-headset -n 50` |
| dot stays red, name does not resolve | mDNS. Use the Pi's IP: `dashboard.py --host 192.168.x.x` (`hostname -I` on the Pi) |
| `no inference.py in ...` | `--project` path in the unit file is wrong |
| `FileNotFoundError: models/dtw_hybrid_model.pkl` | `WorkingDirectory=` is not the project — `config.py` names its models by *relative* path |
| `InconsistentVersionWarning` / unpickle error | the venv's scikit-learn is not the pinned one |
| classifies fine, hand does nothing | serial. Is `pi` in `dialout`? Did you disable the serial *console*? Is `EEG_SERIAL_PORT` the right device? Run once by hand without `--no-serial` and watch `[serial] opened ...` |
| hand goes limp ~3 s after each command | you are running `pi_receive.py --cmd`, not `pi_service.py` — the heartbeat stops when the process exits |

## Keeping the ESP32 in the loop (optional)

The board is no longer needed — but the firmware still works, and the frame is the
same one the dashboard sends, so the Pi cannot tell the two apart.

`firmware/esp32_headset/esp32_headset.ino`. Set `WIFI_SSID` / `WIFI_PASS` first.

- **Board**: ESP32 Dev Module (WROOM-32). The S3/C3 have BLE only — no SPP.
- **Partition Scheme**: `No OTA (2MB APP / 2MB SPIFFS)`. The default 1.2 MB app is
  too small once Bluedroid + WiFi + WebServer link, and "Minimal SPIFFS" gives a
  190 KB data partition — smaller than the 212 KB of snippets.
- **Upload data/**: Tools → *ESP32 Sketch Data Upload* (LittleFS).

Optional physical buttons on GPIO 32/33/25/26/27 to GND (internal pull-ups); set
`ENABLE_GPIO_BUTTONS 0` to drop them. The sketch streams straight off LittleFS in
1 KB chunks and never buffers a whole snippet, because WiFi and Bluetooth Classic
share one radio and a tight heap.

The Pi dials the board, and `--no-reply` keeps the verdict bytes off the SPP link —
the firmware never reads them:

```bash
bluetoothctl            # scan on; pair <ESP_MAC>; trust <ESP_MAC>
python pi_receive.py --mac AA:BB:CC:DD:EE:FF --no-reply \
    --cmd 'python inference.py --file {edf}' --cwd ~/neurograsp/eeg-classifier
```

**This sketch has not been compiled or flashed** — no board was attached here. The
frame it speaks is round-tripped by `host_send.py` → `pi_receive.py` and pinned by
`tests/test_edf_link.py`.

Bluetooth from the *laptop* is not an option: `AF_BLUETOOTH` doesn't exist in
Python on macOS. The laptop dashboard talks TCP.

## Tests

```bash
python -m pytest tests/ -q
```

---

<details>
<summary><b>Appendix: the raw-sample path (superseded)</b></summary>

`esp_headset/` streams raw int16 counts in a custom `VHS1` frame and rebuilds an
`mne.io.RawArray` on the Pi (`python -m esp_headset.receiver`, `python -m
esp_headset.sender`). Built before it was clear the Pi wants an `.edf`. It still
works from the command line, but the EDF path above needs no Pi-side model code at
all, so `dashboard.py` now drives *that* path and no longer speaks `VHS1`.

Playback there was real-time (press → command ≈ 5.6 s) because the samples were
streamed as they would have been acquired. The EDF path sends the whole 43 KB file
at once — press → command is transfer (~100 ms on a LAN) plus inference. The clip
length analysis below is what fixed both at 5 s, and still applies.

## Choosing the clip length

`inference.preprocess_stream` band-passes with a **3.31 s** FIR kernel and
z-scores each channel over the *whole* signal, so the clip cannot be arbitrarily
short. A lone 2 s window is shorter than its own filter, and its z-score is set
by the artifact instead of by rest — that flips **25%** of predicted labels and
**18%** of accept/reject decisions at `CONF_THRESH`.

Measured against the full-recording path:

| clip | label agreement | gate agreement | stream | classify | press → command |
|---|---|---|---|---|---|
| 3 s | 100% | 100% | — | — | too short for the FSM's 2.4 s |
| **5 s** (default) | **100%** | **91%** | 5.0 s | ~0.6 s | **~5.6 s** |
| 10 s | 100% | 94% | 10 s | ~1.8 s | ~12 s |
| 30 s | 100% | 98% | 30 s | ~5.5 s | ~36 s |

The *predicted label* never changes; only borderline confidence decisions do, and
`export_segments.py` rejects any clip that fires the wrong command anyway. So 5 s
is the default. Classification cost scales with clip length (74 ms per gated
window), which is why shortening the clip beats speeding up playback — and a 6×
speed-up would need ~365 kbit/s, above what BLE comfortably sustains.

One consequence stands regardless: a segment is classified once it has fully
arrived. Playback is real-time; inference is per-segment.

## Numbers

| | |
|---|---|
| stream rate | 19 ch × 200 Hz × int16 = **7.6 kB/s** (61 kbit/s) |
| one 5 s segment | 37.1 KiB |
| five segments | **186 KiB** (13% of a 4 MB no-OTA LittleFS partition) |
| ESP32 free heap (WiFi+BT up) | ~100–160 KB → one clip now fits in RAM |

`sender.py` still streams chunks straight off the file rather than buffering, so
the firmware can keep doing the same on a 30 s clip if you re-export with
`--seconds 30`.

## Wire format

The recordings map ±5000 µV onto the int16 range, so samples are *already*
digital counts. They go out raw — unfiltered, un-referenced, exactly what an ADC
emits. Notch, band-pass, CAR and z-score all stay on the Pi.

```
header : "VHS1" | class_id u8 | n_ch u8 | sfreq u16
         | scale f32 | offset f32 | n_samples u32                     (20 B)
payload: per sample t: int16 ch0..ch18, little-endian     (channel order = config.ALL_CH)
```

Reconstruction needs **both** constants: `microvolts = count * scale + offset`.
The int16 range is asymmetric (`-32768..32767`) while the physical range is
symmetric, which forces a non-zero half-LSB offset — `scale = 0.152590 µV`,
`offset = 0.076295 µV`. Computing `rint(µV / scale)` and ignoring the offset
yields `rint(count + 0.5)`, corrupting the code by an LSB; `export_segments.py`
reads both constants out of each EDF header rather than assuming them, and
`tests/test_protocol.py::test_edf_physical_values_recover_their_exact_adc_codes`
pins it.

Sample-major interleave means a chunk boundary never splits a sample. `Header`
narrows both floats to float32 on construction, so the firmware and the Python
simulator agree bit-for-bit.

## Building the segments

Picks the busiest `--seconds` window of a real recording per class (default 5 s),
then **proves** it by pushing the exported bytes through the receiver path; a clip
that confirms the wrong command is rejected and the next candidate tried.

```bash
python export_segments.py --project ~/neurograsp/eeg-classifier --out firmware/data
python export_segments.py --seconds 30            # slower button, best fidelity
```

Writes `seg0.bin` … `seg4.bin` + `manifest.json` — the LittleFS image.

## Two processes, two machines

The headset never classifies. It replays a clip and transmits it. The Pi owns the
model — and on this path it also owns `mne`, because the payload is raw counts
rather than an EDF.

```
 headset (esp_headset.sender)                RPi5 (esp_headset.receiver)
 ┌──────────────────────────┐                ┌───────────────────────────┐
 │ replays a clip           │  segment ───►  │ preprocess_stream         │
 │ no model, no mne         │                │ stream_windows + CommandFSM│
 │                          │  ◄─── verdict  │ SerialSender → Arduino    │
 └──────────────────────────┘                └───────────────────────────┘
```

On the Pi:

```bash
python -m esp_headset.receiver --project ~/neurograsp/eeg-classifier --port 5005
python -m esp_headset.receiver --project ~/neurograsp/eeg-classifier --rfcomm 1   # Bluetooth SPP
```

From the headset:

```bash
python -m esp_headset.sender firmware/data/seg0.bin --host raspberrypi.local --port 5005
```

Both can run on one machine for testing — that is the same topology over
loopback, not a mock.

**Not port 5000.** macOS AirPlay Receiver listens there, so the headset connects
to Control Center and the stream dies mid-flight. The default is 5005.

Commands appear only when the clip finishes — see "Choosing the clip length".

## Running the link

On the Pi:

```bash
python -m esp_headset.receiver --project ~/neurograsp/eeg-classifier --port 5000 --no-serial
```

From the headset (or this simulator while the board is on the bench):

```bash
python -m esp_headset.sender firmware/data/seg0.bin --host <pi-ip> --port 5000
```

Bluetooth sits behind `Transport`: swap `tcp_listen()` for `rfcomm_listen(1)` on
the Pi and nothing else changes — RFCOMM is a stream socket like TCP. (SPP needs
Linux; `AF_BLUETOOTH` doesn't exist on macOS. BLE would need a framing adapter,
and only matters on an S3/C3, which have no Bluetooth Classic.)

## Tests

```bash
python -m pytest tests/ -q
```

No real `.edf` is needed — the channel normalizer is tested against in-memory
channel lists, the CSV parser against small in-memory CSVs, and the wire format
against synthetic counts.

</details>
