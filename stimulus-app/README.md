# EEG Stimulus Presentation

A stimulus-presentation and marker-logging tool for collecting labeled EEG data.
It shows a participant a sequence of visual/audio cues, tells them exactly when to
perform an action, and writes a precisely time-stamped **markers file** you can
align against a raw EEG/EDF recording for training and evaluating classifiers.

There are two implementations of the same app:

- **`eeg_stimulus.py`** — a single-file desktop app (Python + tkinter). This is the
  primary tool.
- **`web/index.html`** — a browser version of the same stimulus flow that runs with
  no install and exports its markers as a CSV.

---

## The 9 classes

Each class has a fixed, stable `marker_id` so EEG/EDF alignment never shifts:

| marker_id | class              | action        |
|-----------|--------------------|---------------|
| 1         | `single_blink`     | Blink ×1      |
| 2         | `double_blink`     | Blink ×2      |
| 3         | `triple_blink`     | Blink ×3      |
| 4         | `jaw_clench_both`  | Clench both   |
| 5         | `jaw_clench_right` | Clench right  |
| 6         | `jaw_clench_left`  | Clench left   |
| 7         | `bruxism_both`     | Grind both    |
| 8         | `bruxism_right`    | Grind right   |
| 9         | `bruxism_left`     | Grind left    |

`marker_id = 0` is reserved for the inter-trial rest / baseline period.

---

## Recording modes

- **TRAIN** — record **one class repeatedly** (one file per class). Use this to
  build a labeled training set for each action.
- **TEST** — record a **random mix of all 9 classes** in a single file. Use this
  to evaluate a trained model on realistic, interleaved data.

Each trial follows the same structure:

```
CUE (prompt shown)  →  GO (perform action)  →  REST (baseline)
```

Timing is configurable per session:

| setting        | meaning                                            | default |
|----------------|----------------------------------------------------|---------|
| `cue_dur`      | seconds the prompt is shown before GO              | 2.0 s   |
| `active_dur`   | seconds to perform the action                      | 2.0 s   |
| `rest_dur`     | seconds of rest between trials                     | 3.0 s   |
| `trials`       | trials of the class (train) / per class (test)     | 20      |
| `break_every`  | short break every N trials (0 = never)             | 30      |

The operator can **accept** or **reject** each trial live (e.g. if the participant
blinked at the wrong time), and rejected trials are flagged in the output.

---

## Output

Everything is written to `./recordings/` as two files per run:

### 1. Markers CSV — `<subject>_..._markers.csv`

```
time_sec,marker_id,signal_name,trial_num,accepted,duration_sec
2.603,1,single_blink,1,True,2.0
7.136,1,single_blink,2,True,2.0
25.443,1,single_blink,6,False,2.0
```

- `time_sec` — onset of the action relative to session start
- `marker_id` / `signal_name` — the class (see table above)
- `trial_num` — trial index
- `accepted` — whether the operator kept the trial
- `duration_sec` — length of the action window

### 2. Summary TXT — `<subject>_..._summary.txt`

A human-readable per-class tally of trials / accepted / rejected, plus the
session's subject, mode, run number, and timing parameters.

---

## Running it

### Desktop app (recommended)

```bash
cd EEG_DATA
source .venv/bin/activate      # optional; a virtualenv is included
python eeg_stimulus.py
```

`tkinter` ships with Python, so there are no required dependencies. `pygame` is an
optional audio fallback only — on macOS the app uses `afplay` (system sounds) and
on Windows it uses `winsound`, so sound works out of the box on both.

### Web version

Open `web/index.html` in a browser, or serve the folder locally:

```bash
python3 -m http.server 8000 --directory web
# then visit http://localhost:8000
```

The web version runs the same stimulus flow and offers a guaranteed CSV download
of the markers on the finish screen.

---

## Repository layout

```
eeg_stimulus.py     Desktop app (Python + tkinter) — the main tool
web/index.html      Browser version of the stimulus flow
recordings/         Output markers CSV + summary TXT per run
eeg_stimulus.html   Standalone HTML prototype
```
