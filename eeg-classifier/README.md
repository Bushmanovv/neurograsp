# eeg-classifier

The BCI. Takes a 19-channel `.edf`, decides which of five deliberate facial
gestures is in it, and emits the matching hand command.

```
.edf ──► notch 50 Hz ──► 1–45 Hz ──► CAR ──► 2 s windows ──► activity gate
                                                                   │
     hand command ◄── 3-in-a-row FSM ◄── confidence ≥ 0.60 ◄── classify
```

**91.8% accuracy, macro-F1 0.918** — leave-one-session-out over 3 sessions,
1,246 activity-gated windows. Per-class F1 runs 0.95–0.99 on the jaw classes and
0.83–0.84 on the blink classes; the split is architectural and explained below.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# classify one recording, no hardware attached
.venv/bin/python inference.py --file "DATA/Session2/Blink/Double Blink/BLINK-DO.EDF" --no-serial

# stage-by-stage health report, no retraining
.venv/bin/python validate_pipeline.py
```

The pins in `requirements.txt` matter. A `.pkl` is pickled scikit-learn objects,
so a different scikit-learn either warns or refuses to unpickle. These are the
versions the models in `models/` were written with.

## Layout

```
eeg_bci/
  config.py          every tunable — paths, rates, bands, labels, thresholds.
                     No other module hardcodes any of them.
  loader.py          finds recordings, labels them from the FOLDER PATH
  preprocessing.py   crop → notch → bandpass → CAR → epoch → reject → z-score
  features.py        93 amplitude-invariant features per epoch
  activity_gate.py   keeps gesture-present windows, drops rest
  hierarchical.py    the deployed classifier (Stage 1 / 2a / 2b)
  riemann.py         covariance → tangent space, for the jaw classes
  train*.py          fitting; train_dtw_hybrid.py produces the deployed model
  eval_*.py          one file per evaluation protocol and per experiment
inference.py         real-time streaming: gate → classify → FSM → serial
DATA/                the raw recordings, 3 sessions
models/              the fitted pickles
tools/               Pi-side helpers (a vendored copy of the receiver)
```

### Labels come from folders, not filenames

Real recording filenames are a mess — `BLINK-DO`, `QUSAITTE`, `CLINCH-L`,
`GLENCH03`, and one file misnamed outright. `loader.py` therefore ignores
filenames entirely and derives the class from the *directory path*, tolerating
the spelling drift that accumulated across sessions (`Bruxissem`, `Bileteral`,
`Clinich`). Adding a session needs zero code changes.

**Do not rename anything under `DATA/`** — the misspelled folder names are load-
bearing.

## The model

Blinks and jaw gestures fail in different ways, so they are classified by
different mathematics:

| Stage | Scope | Method | Result |
|---|---|---|---|
| 1 | blink vs muscle | 93 features → classifier | the easy split |
| 2a | single vs double blink | DTW-KNN on the raw blink waveform | F1 0.83–0.84 |
| 2b | clinch / brux-L / brux-R | Riemannian covariance → tangent space | F1 0.95–0.99 |

Jaw gestures are a *spatial* pattern — which temporal channel is hot — and
covariance geometry represents that almost perfectly. Blinks are a *temporal*
pattern — one deflection or two — which no summary statistic captures; DTW
compares the waveforms directly. Five attempts at the blink split are documented
in the report, four of which failed.

`--model` swaps the classifier behind an identical gate + confidence + FSM:

```bash
python inference.py --file X.edf --model dtw           # default, deployed
python inference.py --file X.edf --model hybrid        # no DTW stage
python inference.py --file X.edf --model hierarchical  # no Riemannian stage
python inference.py --file X.edf --model flat          # single flat classifier
```

## Two design decisions worth knowing

**Dual-output preprocessing.** Per-recording z-scoring deliberately destroys
absolute µV so features describe the gesture's shape rather than the recording's
gain. But blink amplitude features genuinely need µV. So
`preprocess_recording_dual` returns both copies with an *identical* reject mask —
row *i* is the same window in both arrays. Getting this wrong produced one of the
rejected experiments: peak-counting on the z-scored signal rescales spiky EMG up
to blink level and cannot separate one blink from two.

**The activity gate.** About half of every recording is the subject sitting still
between gestures. Labelling those windows with the recording's class is pure
label noise — a rest window from the double-blink file is identical to one from
the triple-blink file but carries a different label. Gating on relevant-channel
peak-to-peak, measured relative to *that recording's own* 90th percentile, was
worth +3.1 points, concentrated on the classes that were drowning.

## Retraining

```bash
.venv/bin/python -m eeg_bci.loader             # what it discovers, and what it skips
.venv/bin/python -m eeg_bci.train_dtw_hybrid   # fit + save the deployed model
.venv/bin/python -m eeg_bci.eval_loso          # the honest evaluation
.venv/bin/python -m eeg_bci.eval_stratified    # the inflated one, for comparison
```

`eval_loso` is the number to trust. A stratified random split puts 50%-overlapping
near-duplicate windows on both sides and scores the model on data it has
effectively already seen — that split once reported 0.80 where grouped folds gave
0.45. Chapter 9 of [the report](../docs/ENCS5300-Final-Report.pdf) documents the
audit.

## Talking to the hand

Inference emits a lowercase label per Contract A — `single_blink`,
`double_blink`, `clinch`, `bruxism_left`, `bruxism_right`, `rest` — over UART at
115200 8N1. The label set is byte-for-byte the `VALID_LABELS` in
[`../hand-firmware/include/contracts.h`](../hand-firmware/include/contracts.h);
neither side may add a label alone.

```bash
EEG_SERIAL_PORT=/dev/ttyAMA0 python inference.py --file X.edf   # Pi 5 GPIO UART
python inference.py --file X.edf --no-serial                    # simulate
```

On a Pi 5 the port is `/dev/ttyAMA0`, **not** `/dev/serial0` — see
[`../raspberry-pi/README_PI.md`](../raspberry-pi/README_PI.md).

## Further reading

- **[`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md)** — the full engineering log: every
  experiment, why each rejected idea failed, and the reasoning behind each stage.
  Written during the RandomForest era, so its headline (85.2%, 6-class) predates
  the DTW-hybrid model above; the pipeline reasoning it records is still current.
- **[`docs/accuracy_improvement.tex`](docs/accuracy_improvement.tex)** — the
  seven-step accuracy journey, 6-class era.
- **[`docs/headset_link.md`](docs/headset_link.md)** — the Pi-side link.
