# Chapter 6 — Data Collection

## 6.1 Overview

This project is an **EEG stimulus-presentation and labeling tool** built to collect
training and test data for a facial/cranial-artifact classification system. Rather
than recording a cognitive task, the tool cues a subject to perform a specific
**muscular/ocular action** (a blink, a jaw clench, a teeth-grind, etc.) at a precisely
known moment in time, while an EEG headset records continuously in parallel. The
tool's only job is to produce an accurately time-stamped **marker log** of what the
subject was told to do and when — this log is later aligned with the raw EEG/EDF
recording (by wall-clock or LSL time) to build a labeled dataset for classifier
training.

Two parallel implementations exist and are kept in sync:

| Implementation | File | Runtime | Output delivery |
|---|---|---|---|
| Desktop app | `eeg_stimulus.py` | Python 3 / Tkinter (+ optional `pygame`) | Writes files directly to `./recordings/` |
| Web app | `web/index.html` (deployed via `vercel.json`) | Single-file HTML/CSS/JS, runs in any browser | Triggers a browser download of the same two files |
| Static export | `eeg_stimulus.html` | Same web app, saved as a standalone artifact | — |

Both implementations present **identical stimuli, timing, and output format**, so
data collected on either one is interchangeable.

## 6.2 Purpose in the wider project

The broader goal is a system that can detect, from EEG, non-cognitive artifacts
produced by facial/jaw muscles and eye movements — signals that are normally treated
as *noise* to be filtered out of EEG, but here are treated as the **signal of
interest** (e.g., as a hands-free control channel, or to study/detect bruxism and
blink patterns). To train a classifier for this, labeled examples of each action are
needed, with millisecond-accurate onset markers. This tool is the instrument used to
generate that labeled dataset, one recording session at a time, across multiple
subjects.

## 6.3 The 9 target classes

The current version of the tool cues exactly nine classes. Each has a fixed,
stable numeric `marker_id` so that alignment with the EEG/EDF file never shifts
between sessions or app versions:

| ID | Class key | Title | Instruction |
|----|-----------|-------|-------------|
| 1 | `single_blink` | Single Blink | Blink ONCE, naturally |
| 2 | `double_blink` | Double Blink | Blink TWICE quickly (~200 ms apart) |
| 3 | `triple_blink` | Triple Blink | Blink THREE times rapidly |
| 4 | `jaw_clench_both` | Jaw Clench BOTH | Clench teeth on BOTH sides, hold |
| 5 | `jaw_clench_right` | Jaw Clench RIGHT | Clench the RIGHT side only, hold |
| 6 | `jaw_clench_left` | Jaw Clench LEFT | Clench the LEFT side only, hold |
| 7 | `bruxism_both` | Bruxism BOTH | Grind teeth, BOTH sides, hold |
| 8 | `bruxism_right` | Bruxism RIGHT | Grind on the RIGHT side, hold |
| 9 | `bruxism_left` | Bruxism LEFT | Grind on the LEFT side, hold |

Marker `0` is reserved for inter-trial rest/baseline. Each class also carries an
Arabic instruction string and an emoji, since the tool is used with Arabic-speaking
subjects.

> Note: earlier pilot sessions in `recordings/` (subjects such as `S060`–`S068`,
> and a handful of one-off labels like `left_wink`, `look_up`, `eyes_closed_alpha`,
> `teeth_grinding`) used an evolving, slightly different label set from an earlier
> iteration of the tool. The current `eeg_stimulus.py`/`web/index.html` pair reflects
> the **finalized 9-class scheme** used going forward; the previous, broader version
> is preserved as `eeg_stimulus_OLD_backup.py` for reference.

## 6.4 Recording modes

The tool supports two distinct session types, chosen at setup:

- **TRAIN mode** — records **one class repeatedly**, producing one file per
  (subject, class, run). The experimenter picks a single class from the 9-class
  grid and a trial count; every trial in the session is that same class. This is
  the mode used to build the bulk of the classifier's training set.
- **TEST mode** — records a **random, shuffled mix of all 9 classes** in a single
  session/file, used for held-out evaluation. Trials-per-class is configurable, and
  the shuffle is post-processed to avoid two identical classes appearing back to
  back (`_fix_repeats`), so the subject can't anticipate the next cue from a
  repeat pattern.

## 6.5 Trial structure and timing

Every trial cycles through three timed phases, each independently configurable in
seconds:

1. **Cue** (`cue_dur`, default 2.0 s) — the class emoji, title, Arabic label, and
   instruction are shown along with a countdown ring, so the subject knows what's
   coming but has not yet acted.
2. **Active** (`active_dur`, default 2.0 s) — a large "GO!" prompt appears and the
   subject performs the action. **The marker is written to the log at the exact
   moment this phase begins** (cue → active transition), which is the operational
   definition of the action's onset for EEG alignment purposes.
3. **Rest** (`rest_dur`, default 3.0 s) — a blank fixation cross (+) is shown as an
   inter-trial baseline/washout period.

Additional session-level controls:

- **`break_every`** — inserts a full-screen "Break Time!" pause every *N* trials
  (0 disables it), to reduce subject fatigue over long sessions.
- **Live preview** on the setup screen computes total trial count and estimated
  session duration from these parameters before recording starts.
- **Reject-in-flight**: during the Active phase, the experimenter can press `R` to
  flag the trial the subject just performed as **rejected** (e.g., subject blinked
  early, was startled, moved) without stopping the session. Rejected trials remain
  in the marker log (so the EEG timeline is unbroken) but are flagged
  `accepted=False` and excluded from the "good" trial counts shown in the summary.
- **Pause/resume** (`SPACE`), **skip current trial** (`N`), and **stop** (`ESC`)
  are all available mid-session; stopping asks whether to keep the partial data
  collected so far.

## 6.6 Session identity and file naming

Each recording is uniquely identified by **subject ID + mode (+ class, if TRAIN) +
an auto-incrementing run number**, so repeat sessions never overwrite each other.
The run number is computed automatically:

- Desktop app: scans `./recordings/` for existing files matching the same
  subject/class/mode prefix and picks `max(existing run) + 1`.
- Web app: since it has no filesystem access, it persists the last run number per
  subject/class/mode key in the browser's `localStorage`, incrementing it only once
  a session is actually saved (not on every attempt).

File stem pattern:

```
TRAIN:  {subject_id}_{class}_train_R{run:02d}_{YYYYMMDD}_{HHMMSS}
TEST:   {subject_id}_MIX_test_R{run:02d}_{YYYYMMDD}_{HHMMSS}
```

## 6.7 Output format

Every saved session produces **two files** in `./recordings/` (desktop) or as two
browser downloads (web), sharing the same stem:

### `*_markers.csv`

One row per trial, in chronological order:

| Column | Meaning |
|---|---|
| `time_sec` | Time of action onset, in seconds relative to session start |
| `marker_id` | Integer 1–9 identifying the class (stable across the whole project) |
| `signal_name` | Class key string, e.g. `single_blink` |
| `trial_num` | 1-based trial index within the session |
| `accepted` | `True`/`False` — whether the experimenter flagged the trial as clean |
| `duration_sec` | Length of the Active phase for that trial |

Example:

```csv
time_sec,marker_id,signal_name,trial_num,accepted,duration_sec
2.603,1,single_blink,1,True,2.0
7.136,1,single_blink,2,True,2.0
11.722,1,single_blink,3,True,2.0
```

`time_sec` is what gets aligned against the EEG amplifier's own timestamp (or LSL
clock) to cut labeled epochs out of the continuous recording.

### `*_summary.txt`

A human-readable session report: subject ID, mode, run number, date/time, the
timing parameters used, and a per-class breakdown of trials/accepted/rejected
counts plus totals — useful for a quick sanity check in the field without opening
the CSV.

## 6.8 Desktop vs. web implementation

| Aspect | Desktop (`eeg_stimulus.py`) | Web (`web/index.html`) |
|---|---|---|
| UI | Tkinter, canvas-drawn buttons for consistent cross-platform styling | Plain HTML/CSS/JS, same visual design |
| Audio cues | System sounds — macOS `afplay`, Windows `winsound`, or `pygame` tone fallback | Browser `Audio`/oscillator equivalents |
| Fullscreen | Native window fullscreen toggle (`F11`) | Fullscreen API |
| Storage | Writes CSV/summary straight to disk in `./recordings/` | Triggers two staggered file downloads (CSV first, then summary, delayed ~700 ms to avoid the browser's popup/download blocker) |
| Run counter persistence | Filesystem scan of `./recordings/` | `localStorage` |
| Deployment | Run locally: `python eeg_stimulus.py` | Deployed as a static site via Vercel (`vercel.json`, `outputDirectory: web`) |

The web version exists so a session can be run from any machine with a browser
(no Python environment needed) — e.g., a lab laptop or tablet — while producing
byte-for-byte-compatible output files.

## 6.9 Collected dataset (current snapshot)

As of this writing, `./recordings/` contains:

- **44 completed sessions** across **17 subjects**, mixing TRAIN and TEST runs, plus one older cross-subject naming variant (`S062-rebruxism`).
- **1,156 total logged trials** across all sessions.
- Class distribution (TRAIN + TEST trials combined, current + legacy label sets):

  | Class | Trials |
  |---|---:|
  | `single_blink` | 189 |
  | `double_blink` | 117 |
  | `triple_blink` | 135 |
  | `bruxism_left` | 145 |
  | `bruxism_right` | 95 |
  | `bruxism_both` | 45 |
  | `jaw_clench_both` | 95 |
  | `jaw_clench_left` | 45 |
  | `jaw_clench_right` | 45 |
  | *legacy/pilot labels* (`left_jaw`, `right_jaw`, `prox_left/right/both`, `jaw_clench`, `left_wink`, `look_up`, `eyes_closed_alpha`, `teeth_grinding`) | ~201 combined, from earlier pilot sessions before the label set was finalized |

Subject IDs follow an `S0NN` / `S0NNN` convention (e.g., `S001`, `S031`–`S040`,
`S060`–`S068`), incremented per new participant enrolled in the study.

## 6.10 Typical data-collection workflow

1. Fit the EEG headset on the subject and start the amplifier's own recording
   (external to this tool).
2. Launch the stimulus tool (desktop or web), enter the **Subject ID**, choose
   **TRAIN** mode and the class to elicit, and confirm the trial count/timing in
   the live preview.
3. Run the session: the tool cues the subject, waits for the action, logs the
   marker at action onset, and rests — repeating for the configured trial count,
   with periodic breaks.
4. On completion, the tool auto-saves the marker CSV + summary TXT and shows a
   results table (trials/accepted/rejected per class) before returning to the
   setup screen for the next run.
5. Repeat step 2–4 for each of the 9 classes (TRAIN), then run one **TEST**
   session with a shuffled mix of all classes for held-out evaluation.
6. Offline: align each `*_markers.csv` against the corresponding EEG/EDF file by
   timestamp, cut labeled epochs around each accepted marker, and assemble the
   per-subject files into the full training/test dataset for the classifier.

## 6.11 Design choices worth noting

- **Marker IDs are fixed and never renumbered**, even as class labels were
  refined over the project's history — this guarantees that EEG/EDF alignment
  logic written against `marker_id` doesn't silently break when the label set
  changes.
- **In-session rejection (`R`) instead of post-hoc cleaning** lets the
  experimenter, who can see the subject in real time, flag a bad trial the
  moment it happens rather than relying on offline visual EEG inspection alone.
- **Every stopped session still offers to save partial data** rather than
  discarding it outright — long sessions can be safely cut short (subject
  fatigue, equipment issue) without losing already-collected trials.
- **Auto-incrementing run numbers** prevent accidental overwrites when the same
  subject/class is recorded across multiple days or after a restart.
