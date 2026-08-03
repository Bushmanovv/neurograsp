# EEG-BCI Graduation Project — Full Technical Summary

> A single-subject EEG brain–computer interface (BCI) that decodes **deliberate facial/ocular gestures** (eye blinks + jaw movements) from a 19-channel clinical EEG and maps them to discrete **prosthetic-hand commands** sent to an Arduino over serial.

This document explains **what was built, how each stage works, and why each design decision was made**, including the experiments that were *rejected* (they shaped the final design). It reflects the **actual current state of the code**, and flags where the code has moved past the written LaTeX report.

---

## 1. Objective & core idea

Reliable motor-imagery decoding from a low-cost montage is hard, so the system instead decodes **large, repeatable EEG/EMG artifacts** produced by intentional gestures (blinks, jaw clenches, bruxism/grinding). These are easy to produce on demand and map cleanly to commands.

The system is **single-subject**: the same person who trains the model uses it. The evaluation target is therefore **per-session generalization for one person**, *not* cross-subject transfer.

### Command mapping (current 5-class scheme — `config.py`)

| Label | Gesture (class) | Arduino char | Action |
|------:|-----------------|:------------:|--------|
| 0 | `double_blink`  | **S** | start / confirm |
| 1 | `single_blink`  | **O** | open hand |
| 2 | `clinch`        | **C** | close hand (bilateral clench only) |
| 3 | `bruxism_left`  | **L** | rotate left |
| 4 | `bruxism_right` | **R** | rotate right |

> **⚠ Code-vs-doc note.** The LaTeX report (`docs/accuracy_improvement.tex`) documents an older **6-class** scheme that additionally had `triple_blink` (char **T**) and a heterogeneous `clinch` mega-class. On **2026-06-18** the taxonomy was deliberately cleaned to the **5 pure classes above**: `triple_blink` was dropped (it caused an unfixable single↔triple blink confusion), and `clinch` was narrowed to *bilateral clench only* (bilateral-bruxism and clinch-left/right were excluded so each class is one separable gesture). The 85.2% headline in the report is the 6-class number; the current code runs the 5-class taxonomy.

---

## 2. Hardware & data acquisition

- **Device:** clinical 19-channel EEG, international 10–20 montage, all referential `-Ref` channels.
- **Sampling rate:** 200 Hz.
- **Montage (acquisition order):** `Fp1, Fp2, Fz, F8, F7, F4, F3, C4, C3, O2, P3, Cz, O1, P4, Pz, T6, T5, T4, T3` (each suffixed `-Ref`).
- **Files:** each recording is an `.EDF` (signal) + `.TEV` (device events) pair, ~2–5 min long.
- **Stimulus / cueing app** (lives in the sibling `EEG_DATA/` working dir): `eeg_stimulus.py` / `eeg_stimulus.html` — a Vercel-deployable web app that cues the subject ("Cue 1s → Action 2s → Rest 1s" ≈ 4 s/trial) and writes per-trial **marker CSVs** + **summary TXTs** into `EEG_DATA/recordings/`. The held-out "Random" mixed-gesture session's marker CSV comes from this app.

### Subject (single-subject — all 3 sessions)
- **Session1, Session2, and Session3 are all the same subject, *Qusai*.** This is a single-subject BCI; the entire evaluation methodology depends on it.
- **Naming caveat:** Session3 was *misnamed* during recording. The only on-disk artifact of this is one filename, `DATA/Session3/Bruxissem/Bruxissem Right/FADIBRUX.EDF` (+ its `.TEV`), which carries a different name token. **It has no effect on the pipeline** — the loader labels purely from the *folder path* (`Bruxissem` + `Right` → `bruxism_right`) and never reads filenames or EDF subject fields.
- **Metadata check:** EDF `his_id` headers do not encode a real subject identity (Session1 = `TEST01-`, Session2 = `Tests`, Session3 = gesture tags like `BLINKING`/`BRUXISM`/`GLINCH`), so no metadata field contradicts the single-subject assumption. Subject identity rests on the recordist's own record, not on anything stored in the data.

---

## 3. Dataset (current, as the loader actually discovers it)

The loader scans `DATA/Session*` and labels each EDF from its **folder structure** (not the inconsistent filenames). Current discovery: **15 usable recordings = 3 sessions × 5 classes** (perfectly balanced at the *recording* level), plus 9 EDFs intentionally skipped as "not in active taxonomy".

| Session | Usable EDFs | Skipped (excluded taxonomy) |
|---------|:-----------:|------------------------------|
| Session1 | 5 | BLINK03 (triple), BRUXES01 (bilat-brux), GLENCH02 (clinch-L), GLENCH03 (clinch-R) |
| Session2 | 5 | BLINK-TR (triple), QUSAITTE (bilat-brux), CLINCH-L, CLINCH-R |
| Session3 | 5 | BLINKTRIPLE (triple) |
| **Total** | **15** | **9 skipped** |

Per-class recording counts: **3 each** for double_blink, single_blink, clinch, bruxism_left, bruxism_right.

After preprocessing (sliding windows), this yields **2,564 epochs × 19 channels × 400 samples** → **93 features/epoch** (confirmed by `validate_pipeline.py`).

- **Noisy files** (`config.NOISY_FILES = {BLINK01, BRUXESRIGHT}`): loaded anyway but flagged `[WARN]`.
- **"Random" session** (`DATA/Random/`): a 180 s mixed-gesture recording with a 45-marker CSV. **It is excluded from training/headline** because its stimulus-app clock does not align to the EDF clock — the timestamps can't be trusted, so it can only be scored by *content/order alignment*, which is unreliable (see §8).

---

## 4. The pipeline (stage by stage)

The reusable pipeline lives in the **`eeg_bci/`** Python package. All tunable parameters are centralized in `config.py` — no other module hardcodes paths, rates, bands, or labels.

```
Stage 1  loader.py         EDF discovery + folder-based labelling
Stage 2  preprocessing.py  crop → notch → bandpass → CAR → epoch → reject → z-score
Stage 3  features.py       93 amplitude-invariant features per epoch + SelectKBest(50)
Stage 4  train.py          Scaler → SelectKBest → SMOTE → classifier; model selection
         inference.py      real-time streaming: activity gate → features → FSM → serial
```

### Stage 1 — Discovery & labelling (`loader.py`)
Filenames are wildly inconsistent across sessions (`BLINK-DO`, `QUSAITTE`, `CLINCH-L`, `GLENCH03`…). The loader therefore derives the label from the **folder path**: it detects a **category** (Blink / Bruxissem / Clinch — tolerant of misspellings like "Bileteral", "Glinch", and Session2's `QUSAI*` bruxism naming) and a **side** (single/double/multiple/left/right/bilateral), then maps `(category, side)` to a canonical stem (`BLINK02`, `GLENCHDOUBLE`, …) that keys into `config.LABEL_MAP`. Stems outside the active taxonomy are cleanly skipped. **Why:** adding a new session requires *zero code changes*, and the label logic is robust to the messy real filenames.

### Stage 2 — Preprocessing (`preprocessing.py`)
Exact order per recording:
1. **Crop** — discard the first **40 s** (`CROP_SECONDS`) of setup/settling.
2. **Notch** — 50 Hz mains.
3. **Band-pass** — 1–45 Hz.
4. **CAR** — common-average reference (subtract the across-channel mean).
5. **Epoch** — fixed **2 s** windows with **50% overlap** (`make_fixed_length_epochs`).
6. **Reject** — drop any epoch whose peak amplitude exceeds **500 µV** (movement/electrode artifact). Rejection is done on the **raw-µV** signal (the threshold only means something before normalization).
7. **Per-recording z-score** — each channel z-scored over the *whole recording*.

> **Key trick — dual output (`preprocess_recording_dual`).** The same epochs are returned **twice**: once **z-scored** (for most features) and once in **raw µV** (filtered+CAR, pre-normalization) for the amplitude-sensitive blink-peak features. Both share the identical reject mask so row *i* is the same window in both arrays. **Why:** per-recording z-scoring deliberately destroys absolute µV (so features describe gesture *shape*, not recording gain) — but peak/amplitude features *need* the µV scale, so they get the un-normalized copy.

A separate `filter_and_car()` path (no crop, no epoching) is used by real-time inference, which filters the full signal before sliding windows over it.

### Stage 3 — Feature extraction (`features.py`) → **93 features/epoch**

> The module docstring still says "78"; the code actually produces **93** (the SelectKBest then keeps the best 50). The 78→93 redesign is documented as a foundational experiment (§7).

Layout (**93 = 22 + 22 + 11 + 38**):

| Group | Channels | Features | Count |
|-------|----------|----------|------:|
| Frontal blocks | Fp1, Fp2 | 11-feature block × 2 | 22 |
| Temporal blocks | T3, T4 | 11-feature block × 2 | 22 |
| T4−T3 asymmetry | (T4 vs T3) | normalized asym index per block-feature | 11 |
| Statistical | all 19 channels | kurtosis + skewness | 38 |

Each **11-feature channel block** = **3 time** (`rms`, zero-crossing-rate, peak-to-peak) + **5 relative band powers** (delta/theta/alpha/beta/gamma, each ÷ total power, via Welch PSD) + **3 Hjorth** parameters (activity, mobility, complexity).

**Design principles (the "why"):**
- **Amplitude-invariant by construction** — raw mean & std were *removed* (they encode recording identity/gain, not the gesture); absolute band power → **relative** band power; Hjorth mobility/complexity are scale-free.
- **T4−T3 asymmetry index** `(T4−T3)/(|T4|+|T3|)` exposes left/right lateralization — essential for `bruxism_left` vs `bruxism_right`.
- **Hard assertions** after extraction: feature count matches names, and **zero NaN / zero Inf** (the pipeline aborts otherwise).

**Disabled-but-preserved toggles** (kept for reproducibility, all `False`):
- `BLINK_PEAK_FEATURES` (+8 frontal peak-count/timing features) — rejected (Steps 2 & 4).
- `FIX1_ASYM_RATIOS`, `FIX2_DROP_TEMPORAL_RMS`, `FIX3_LATERAL_INDEX` (lateralization fixes) — rejected (hurt `bruxism_right`).

**Feature selection:** `SelectKBest(mutual_info_classif, k=50)` — keep the 50 most informative features; prints the top-10 by mutual information.

### Stage 4 — Classifier pipeline (`train.py`)
An **imbalanced-learn** pipeline (so SMOTE only ever sees the *training* fold — no leakage into the test fold):

```
StandardScaler → SelectKBest(mutual_info, k=50) → SMOTE → Classifier
```

Three classifiers are compared and the best is chosen by **macro-F1** (tie-broken by accuracy), because the classes are imbalanced:
- **RandomForest** — `n_estimators=600`, `max_features="sqrt"`, `class_weight="balanced_subsample"` ← **winner, deployed**
- SVC-RBF (`probability=True`)
- LDA (`lsqr`, auto-shrinkage)

CV uses **`StratifiedGroupKFold`** grouped **by recording**, so the 50%-overlap near-duplicate windows of one recording never straddle train/test. The winner is refit on all data and saved.

> RandomForest was retained over a gradient-boosting / voting / stacking bake-off: those only beat RF on the leakage-prone stratified split but were **worse on the honest cross-session test** (train S1+S2 → unseen S3). See the `[[boosting-ensembles-overfit-leakage]]` finding.

### Real-time inference (`inference.py`)
Deployment-faithful streaming of an EDF → Arduino commands. Per file:
1. Load EDF → notch → bandpass → CAR on the **full** signal (**no crop**), keeping both µV and z-scored copies.
2. Slide a **2 s window** (`WINDOW_SEC`, must equal `EPOCH_SEC`) every **0.2 s** (`STEP_SEC`).
3. **Activity gate:** `activity = max(frontal RMS, temporal RMS)` in µV. If `< 20 µV` (`ACTIVITY_THRESHOLD`) → **rest**, skip (and reset the FSM). *Why:* the gated model was trained only on gesture-present windows; a controller must never fire on rest.
4. Extract 93 features on the z-scored window → `gated_model.predict_proba`.
5. **Confidence gate:** if `max proba < 0.60` (`CONF_THRESH`) → skip.
6. **Finite-state machine:** fire the command only after **3 identical predictions in a row** (`FSM_THRESH`). Any rest/low-conf/different prediction resets the streak; firing also resets (so holding the gesture doesn't re-fire).
7. Send the Arduino char over serial (115200 baud, `COM3`), or simulate with `--no-serial`.

CLI: `python inference.py --file path.edf [--no-serial] [--quiet] [--threshold 0.65] [--activity 20]`.

---

## 5. Evaluation methodology & honesty caveats

Because the system is single-subject, the **headline metric is a stratified random 80/20 split** of pooled epochs (`random_state=42`), reporting accuracy, per-class F1, macro-F1, and confusion matrix. Two caveats are stated openly:

- **Overlap inflation.** With 50%-overlap epochs, a random split puts near-duplicate windows in both train and test, so the within-session number *overstates* true generalization. The **leakage-free cross-session number (~65% / macro-F1 0.53)** is the conservative truth.
- **Split variance.** On this small, correlated dataset a single split has **~1.5% accuracy noise** → later experiments report the **mean over 5 seeds** (42, 1, 7, 123, 2024).

---

## 6. Models & evaluation scripts

| File | Role |
|------|------|
| `models/best_model.pkl` | ungated pipeline (classify *every* window), ~0.9 MB |
| `models/best_model_gated.pkl` | **activity-gated** pipeline used by `inference.py`, ~10 MB |
| `eeg_bci/eval_stratified.py` | Step 1 — 5-class stratified 80/20 (S1+S2) |
| `eeg_bci/eval_6class.py` | Step 3 — 6-class retrain + comparison |
| `eeg_bci/eval_augmented.py` | Step 6 — augmentation experiment |
| `eeg_bci/eval_gated.py` | Step 7 — activity-gated epoching (trains the gated model) |
| `eeg_bci/eval_random.py` | held-out Random-session scoring by content/order alignment |
| `eeg_bci/blink_peak_diag.py`, `blink_peak_v2_viz.py` | Steps 2 & 4 blink-peak validation/diagnostics |
| `validate_pipeline.py` | end-to-end stage-by-stage pass/fail report (no retrain) |
| `test_per_artifact.py` | per-class cross-session accuracy + per-class top features |
| `feature_fix_experiment.py` | lateralization-fix experiment (rejected) |

---

## 7. The accuracy-improvement journey (results)

> Numbers below are from `docs/accuracy_improvement.tex` (the 6-class era). They remain the authoritative record of *how the design was reached*; the live code subsequently moved to the 5-class taxonomy (§1).

### Foundational design experiments
| # | Approach | Outcome |
|---|----------|---------|
| F1 | Relative band power + Hjorth + T4−T3 asymmetry (78→**93** features) | **Adopted** |
| F2 | Per-recording z-score normalization | **Adopted** |
| F3 | Lateralization fixes (T4/T3 ratio, drop-RMS, lateral index) | **Rejected** — hurt `bruxism_right` (F1 0.33 → 0.23–0.26) |
| F4 | `StratifiedGroupKFold` (anti-leakage CV) | **Adopted** — exposed a fake 0.80 → real **0.45** grouped accuracy |
| F5 | SMOTE + SelectKBest(50) + 3-classifier compare | **Adopted** |

### The seven steps
| Step | Change | Classes | Eval | Accuracy | Macro-F1 | Verdict |
|:----:|--------|:-------:|:----:|:--------:|:--------:|---------|
| — | Prior baseline cross-session S1→S2 | 5 | LDA | 65.0% | 0.53 | conservative truth |
| 1 | Stratified 80/20 split | 5 | RF | 80.4% | 0.728 | ✅ adopted |
| 2 | Blink peak-count on **z-scored** signal | 5 | — | rejected | — | ❌ normalization artifact |
| 3 | **Label scheme 5 → 6 classes** (pure blink classes) | 6 | RF | 83.4%† | 0.778 | ✅ first big win |
| 4 | Blink peak-count on **raw µV** (8 features) | 6 | RF | 82.8% | — | ❌ noise-level gain |
| 5 | Data "Bileteral" bug fix + 5-seed reporting | 6 | RF | 82.1% ±1.6% | 0.761 | ✅ adopted |
| 6 | Physiological augmentation (jitter/scale/shift/warp) | 6 | RF | 80.9% | — | ❌ −1.1% |
| 7 | **Activity-gated epoching** | 6 | RF | **85.2%** | **0.818** | ✅ decisive win |

† single seed-42 split before the data fix; the honest multi-seed ungated baseline is 82.1±1.6%.

**Why each rejected idea failed (the valuable part):**
- **Step 2 (blink peaks on z-scored signal):** per-recording z-scoring rescales spiky EMG up to blink level → `find_peaks` can't separate single vs double vs multiple. Caught at a *validation gate* before any retrain. See `[[blink-peak-counting-fails]]`.
- **Step 4 (blink peaks on raw µV):** validation ordering was clean (single < double < triple), but as classifier features they gave only noise-level deltas (S +0.024, T +0.008) while slightly hurting C/L/R — the existing 93 features already encode multi-peak blink shape. Redundant.
- **Step 6 (augmentation):** the real bottleneck is the number of *independent recordings* (~2–3/class), not epochs. Synthesizing jitter/scale/shift/warp variants didn't add genuine session variability → −1.1%. **Clean labels beat synthetic data.**

**Step 7 — the decisive win (why it worked):** sliding-window epoching labels *every* 2 s window with the recording's class, including the **~48% that are rest** between gestures. A rest window from the double-blink file is identical to one from the triple-blink file but carries a different label → **label noise**. Gating by relevant-channel peak-to-peak µV (frontal for blinks, temporal for jaw), recording-relative (≥ frac × 90th-percentile of that recording), and keeping ~52% active windows redefines the task to the **real deployment task** ("classify gesture-present windows"). Result: **82.1% → 85.2%**, with the biggest gains exactly on the noise-drowned classes — `bruxism_left` +0.117, `bruxism_right` +0.093, `triple_blink` +0.092 macro-F1.

---

## 8. Known limitations

- **Within-session vs cross-session gap.** Headline 85.2% (overlapped within-session) vs honest **~65% / 0.53** cross-session — the small dataset and overlapping epochs inflate the headline. Stated explicitly everywhere.
- **Data bottleneck:** only ~3 independent recordings per class; augmentation can't substitute for real sessions.
- **Random session unscorable by time:** the stimulus app and EEG record on **separate clocks**, so `RANDOM.EDF` can't be reliably scored against its marker CSV by timestamp — only by content/order alignment, which the script itself flags as "WEAK". See `[[random-session-unalignable]]`.
- **Doc/code drift:** `docs/accuracy_improvement.tex` is the 6-class era; live code is 5-class. `features.py` docstring still says "78" (actual 93). `validate_pipeline.py` looks for `eeg_bci/inference.py` / `run_test.py` (it reports them "not built" — `inference.py` actually lives at the project root).

---

## 9. How to run (uses the project's Python env)

```bash
cd /Users/karimdwikat/Desktop/EEG_GRADUATIO_PROJECT

# End-to-end sanity report (no retrain)
python validate_pipeline.py

# Discover + label recordings
python -m eeg_bci.loader

# Retrain & save best_model.pkl (5-fold grouped CV)
python -m eeg_bci.train
python -m eeg_bci.train --cross-session     # honest S1→S2 test

# Headline stratified eval (Step 1/3 style)
python -m eeg_bci.eval_stratified
python -m eeg_bci.eval_6class

# Train & save the gated model (Step 7)
python -m eeg_bci.eval_gated

# Per-class cross-session report
python test_per_artifact.py

# Real-time inference on one EDF (simulation, no Arduino)
python inference.py --file "DATA/Session2/Blink/Double Blink/BLINK-DO.EDF" --no-serial --quiet
```

---

## 10. At a glance

- **Input:** 19-channel, 200 Hz EEG `.EDF` of intentional blink/jaw gestures.
- **Pipeline:** crop 40 s → notch 50 Hz → bandpass 1–45 Hz → CAR → 2 s/50%-overlap epochs → reject >500 µV → per-recording z-score → **93 amplitude-invariant features** → SelectKBest(50) → SMOTE → **RandomForest(600)**.
- **Deployment:** activity-gated sliding-window inference → 3-in-a-row FSM → Arduino char (S/O/C/L/R).
- **Accuracy:** **85.2%** / macro-F1 **0.818** (6-class gated, within-session); **~65%** / 0.53 (honest cross-session). Live code now runs the cleaner **5-class** taxonomy.
- **Biggest lessons:** validate features before retraining; mind the normalization domain; report split variance; **clean labels > more/synthetic data**; report rejected experiments.
