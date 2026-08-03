# Artifact-Based EEG Brain-Computer Interface for Prosthetic Hand Control
## Complete Research & Development Documentation

**Project type:** Single-subject, artifact-based BCI
**Application:** Real-time prosthetic hand control via voluntary facial/jaw gestures
**Final result:** 91.3% accuracy (Leave-One-Session-Out), macro-F1 0.913
**Institution:** Birzeit University — Computer Engineering Graduation Project

---

## Abstract

This project develops a Brain-Computer Interface (BCI) that translates voluntary EEG artifacts — eye blinks and jaw muscle activations — into discrete control commands for a prosthetic hand. Rather than relying on motor imagery (which typically achieves only 60-70% accuracy), the system deliberately exploits high-amplitude physiological artifacts (EOG from blinks, EMG from jaw muscles) that are easier to detect and voluntarily control.

The work progressed through systematic experimentation, beginning with a conventional flat classifier (85.1% LOSO) and culminating in a **three-way hybrid architecture** that reached **91.3% LOSO accuracy**. The final design routes each gesture type to the classification method best suited to its physiology: hand-crafted features for the blink-vs-muscle decision, Dynamic Time Warping (DTW) shape-matching for blink sub-classification, and Riemannian geometry (covariance-based) for muscle sub-classification.

Two key scientific insights drove the final gains:
1. **Muscle classes:** covariance structure survives day-to-day amplitude drift that defeated amplitude-based features (TKEO).
2. **Blink classes:** waveform shape-matching survives label contamination that defeated five separate event-counting methods.

---

## 1. Problem Definition & Motivation

### 1.1 Why Artifact-Based BCI

Traditional motor-imagery BCIs suffer from low accuracy and high inter-session variability. This project takes an alternative approach: using **voluntary artifacts** as control signals. These artifacts are:
- High amplitude (blinks ~50-350µV, jaw EMG ~80-1000µV) — easy to detect
- Voluntarily controllable — the user can produce them on demand
- Distinct from everyday movements — low false-activation risk

### 1.2 The 5-Command Gesture Set

| Command | Gesture | Signal type | Hand action |
|---------|---------|-------------|-------------|
| `S` | Double blink | EOG (frontal) | Start / Confirm |
| `O` | Single blink | EOG (frontal) | Open hand |
| `C` | Jaw clench | EMG (temporal) | Close hand |
| `L` | Bruxism left | EMG (left temporal) | Rotate left |
| `R` | Bruxism right | EMG (right temporal) | Rotate right |

**Hardware:** 19-channel EEG, 200 Hz sampling, EDF format. Final deployment target: Emotiv EPOC X headset.

**Critical physiological insight:** Although the device is marketed as "EEG," the clench/bruxism commands are fundamentally **EMG** (muscle electrical activity) captured by temporal electrodes (T3, T4), while blinks are **EOG** (eye movement potentials) captured by frontal electrodes (Fp1, Fp2). This dual nature became central to the final architecture.

---

## 2. Data Collection

### 2.1 Session Structure

All data collected from a **single subject** across multiple recording sessions (the misnamed "Session3/Fadi" was confirmed to be the same subject — a recording labeling error, not a second person).

```
DATA/
├── Session1/   (Train)
├── Session2/   (Train)
├── Session3/   (Train / cross-session test)
│   ├── Blink/      (BLINK01, BLINK02, BLINK03)
│   ├── Bruxissem/  (BRUXESLEFT, BRUXESRIGHT, BRUXESDOUBLE)
│   └── Clinch/     (GLENCHLEFT, GLENCHRIGHT, GLENCHDOUBLE)
└── Random/     (mixed-gesture validation — see §9)
```

### 2.2 Recording Protocol

Each gesture recorded as a separate continuous EDF file (3-5 minutes). Recordings begin with a settling period; the first 40 seconds are cropped to avoid electrode-settling noise. Two files were flagged as inherently noisy: `BLINK01` (single blink) and `BRUXESRIGHT`.

### 2.3 Data Quality Issues Discovered

- **Electrode settling:** first 5-35s of several recordings unusable.
- **Single-blink contamination (critical, discovered late):** ~45% of "single blink" trials actually contained clusters of 3+ blinks within ~1 second — the subject blinked repeatedly instead of once. This contamination would later prove central to the blink-classification difficulty.
- **Loader bug:** a misspelled folder ("Bileteral" vs "Bilateral") silently dropped 2 of 18 recordings, training clinch on 1002 epochs instead of 1328. Fixed once discovered.

---

## 3. Pipeline Architecture (Stages 1-5)

### Stage 1 — Data Loading
- Auto-scans `DATA/` for any `Session*` folder (zero code change to add sessions)
- Assigns labels from folder structure (filenames were inconsistent across sessions)
- Validates 19 channels, 200 Hz, flags noisy files

### Stage 2 — Preprocessing
Per recording, in order:
1. **Crop** first 40s (electrode settling)
2. **Notch filter** at 50 Hz (power-line interference)
3. **Bandpass filter** 1-45 Hz (initially)
4. **CAR** (Common Average Reference)
5. **Epoch segmentation:** 2-second windows, 50% overlap
6. **Artifact rejection:** drop epochs exceeding 500µV

Output: ~2821 epochs × 19 channels × 400 samples.

### Stage 3 — Feature Extraction (channel-aware)
93 features per epoch, grouped by physiological relevance:

| Group | Channels | Features |
|-------|----------|----------|
| FRONTAL | Fp1, Fp2 | time-domain + 5 band powers + peak features |
| TEMPORAL | T3, T4 | time-domain + 5 band powers + asymmetry |
| ALL | 19 channels | kurtosis, skewness |

Top discriminative features (mutual information): T4 gamma power, T4 peak-to-peak, T4 beta, Fp1/Fp2 peak-to-peak, T3-T4 asymmetry.

### Stage 4 — Classification
StandardScaler → SelectKBest(MI) → SMOTE → classifier. Tested RandomForest, SVM-RBF, LDA.

### Stage 5 — Real-Time Inference
Sliding window (1.5-2.0s, 200ms step) → activity gate → features → predict → FSM (3 consecutive identical predictions confirm a command) → Arduino serial output.

---

## 4. The Evaluation Methodology Crisis (Critical Section for Paper)

This was the single most important methodological lesson of the project.

### 4.1 The Inflated Number

Initial results using **random StratifiedKFold** gave ~80-85% accuracy. This number was **inflated by epoch-overlap leakage**: with 50%-overlapping epochs, adjacent near-duplicate windows landed in both train and test folds.

### 4.2 The Leakage Audit

A formal audit ran four diagnostic tests:

| Test | Purpose | Result |
|------|---------|--------|
| Strict cross-session (S1+S2→S3) | true generalization | 74.4% ungated / 81% gated — does NOT collapse → signal is real |
| Scaler/SelectKBest fit-on-train | preprocessing leak | CLEAN (verified numerically) |
| Same-recording epochs in both folds | overlap leak | headline protocol: YES (leaks); grouped protocols: NO |
| Shuffle test (permuted labels) | implementation leak | 21% (≈ chance) → pipeline is clean |

**Conclusion:** No implementation leakage, but the headline protocol leaked via epoch overlap. The shuffle test (21% with random labels — exactly chance for 5 classes) proved the pipeline does not manufacture signal.

### 4.3 The Honest Protocols Going Forward

| Protocol | Use | Property |
|----------|-----|----------|
| GroupKFold (recording-level) | development/tuning | no overlap leakage |
| Leave-One-Session-Out (LOSO) | final reporting | strictest, cross-day, deployment-realistic |

**All subsequent numbers in this document use LOSO** unless stated. The single-subject design means cross-session (same person, different day) is the correct generalization target — not cross-subject.

---

## 5. Label Taxonomy Evolution

### 5.1 5-Class → 6-Class (+3.0%)

**Problem:** `BLINK01` (single) and `BLINK03` (multiple) were merged into one "single_blink" class, contaminating it.

**Fix:** Split into pure classes — single, double, triple as separate labels.

**Result:** single_blink F1 0.818→0.885, bruxism_left 0.609→0.737, overall 80.4%→83.4%.

### 5.2 6-Class → 5-Class (final)

Triple blink was ultimately dropped (and bilateral-bruxism, which had been mislabeled as clinch). Rationale: triple blink craters the blink stage to ~56% regardless of method (double and triple are ~300-400ms apart and merge at this resolution), and dropping the two hardest cases is a legitimate design decision for a *working* prosthetic. Final system: **5 robust gestures.**

---

## 6. Activity-Gated Epoching (+3.1%)

**Problem discovered:** ~48% of epochs were *rest* windows (no gesture) but were labeled with the gesture's class. A rest window in the double-blink file looked identical to a rest window in the triple-blink file — with conflicting labels.

**Fix:** Keep only epochs whose energy exceeds 50% of the recording's own activity level:
```python
activity = max(rms(Fp1/Fp2), rms(T3/T4))
if activity < ACTIVITY_THRESHOLD: skip_epoch()
```

**Result:** ungated 82.1% → gated 85.2%. Biggest gains on the weakest classes (bruxism_left +0.117, triple_blink +0.092). This also matches real deployment — a prosthetic only acts on active windows.

**Note:** A separate "session-simulating augmentation" experiment (jitter/scale/shift/warp) was tested and **failed (-1.1%)** — perturbing epochs cannot replace independent recordings.

**Caveat caught:** The original gated evaluation used the *true label* to pick activity channels (label-peek), inflating gated numbers by ~6 points. The deployment-faithful, label-agnostic gate gives the honest 81% figure.

---

## 7. Feature Engineering Experiments (Mostly Negative — Important for Paper)

A systematic exploration of advanced features, evaluated under GroupKFold. **Most failed**, and the failures were diagnostic.

### 7.1 The Experiments

| Feature family | Result vs baseline (77.2%) | Verdict |
|----------------|---------------------------|---------|
| DWT (full, 108 feats) | −14.4% | Catastrophic — amplitude-scaled coefficients are noise |
| DWT relative-energy only (36 feats) | break-even (+0.1%) | Wash — helps blinks, costs clinch |
| TKEO (Teager-Kaiser Energy) | −5.7% | Squared-amplitude doesn't survive session drift |
| EMG descriptors (WL/SSC/Willison/CV) | −3.1% overall, but C +0.06, L +0.06 | Helps muscle, hurts blinks |

### 7.2 The Key Realization

Every advanced feature added discriminative power for **one** class group while acting as **pure noise** for the other:
- Muscle features (EMG, TKEO) help C/L/R but are meaningless for blinks (frontal EOG)
- A single flat RandomForest cannot apply features *conditionally*

**The bottleneck was architectural, not feature count.** This realization motivated the hierarchical design.

---

## 8. The Hierarchical Architecture (+5.0%)

### 8.1 Design

A 2-stage hierarchical classifier routes each window to a specialized sub-model:

```
Stage 1: blink {S,O} vs muscle {C,L,R}
         features: frontal/EOG channels (Fp1, Fp2, Fz, F3, F4)
              │
      ┌───────┴───────┐
   blink            muscle
      │                │
Stage 2a:          Stage 2b:
S vs O             C vs L vs R
+ blink peak       + EMG descriptors
  features           + asymmetry
```

Each stage trains **only on its own epoch subset**, so muscle features can never reach the blink decision (and vice versa). One 129-feature superset is extracted once; each stage selects its columns by name.

### 8.2 Results

| Stage | Accuracy |
|-------|----------|
| Stage 1 (blink/muscle) | 98.7% |
| Stage 2a (S vs O) | 76.4% |
| Stage 2b (C vs L vs R) | 87.8% |
| **End-to-end** | **82.2%** (vs 77.2% flat, GroupKFold) |

**Key wins:** The biggest gains were the *blink* classes (S +0.092, O +0.120), because Stage 1 (98.7%) almost eliminates blink↔muscle confusion, and Stage 2a sub-classifies blinks free of muscle-feature dilution.

**Blink-peak features finally worked** — they had failed in the flat multi-class context due to label contamination; in the pure 2-class S-vs-O stage that contamination is gone.

### 8.3 LOSO Reconciliation

On the strictest LOSO protocol, the hierarchical model initially regressed (-1.9pt) due to two session-fragile choices. An ablation revealed:
- **TKEO is the poison** — dragged bruxism_right to 0.789 (doesn't survive amplitude drift). Dropped.
- **EMG descriptors help cross-session** — clinch 0.74→0.84 (complexity measures generalize). Kept.
- **Stage 1 needed temporal channels** — adding them took routing isolation 98%→100%.

After the fix: hierarchical matched flat at 85.1% LOSO but with better macro-F1 (0.839 vs 0.837) and cleaner live routing.

---

## 9. The Random-Session Validation Attempt (Failed — Documented)

A special "Random" session was recorded — a single EDF with all gestures in random order, plus a markers CSV with timestamps. Intended as the cleanest possible real-world test.

**Failure:** The EDF and the markers CSV were on **unsynchronized clocks**, and order-based burst alignment could not be verified. Both alignment methods landed near chance. This is a **data-acquisition limitation** (the stimulus app and EEG device used separate clocks), not a model failure.

**Lesson for future work:** record markers directly on the EEG device, not from a separate application.

---

## 10. Riemannian Geometry for Muscle Classes (+4.1%)

### 10.1 Motivation

The TKEO failure revealed that absolute-amplitude features don't survive day-to-day drift. Riemannian geometry operates on **inter-channel covariance matrices** rather than absolute amplitude — making it inherently robust to amplitude scaling and ideal for cross-session BCI.

### 10.2 Method

```python
Covariances(estimator='oas') → TangentSpace(metric='riemann') → SVC
```

Applied to **Stage 2b** (muscle C/L/R), the stage where amplitude drift hurt most. Input: raw epochs (covariance computed across channels), not hand-crafted features.

### 10.3 Results (LOSO)

| Model | Overall | C | L | R |
|-------|---------|---|---|---|
| Hierarchical (features) | 85.1% | 0.83 | 0.90 | 0.94 |
| **Riemann hybrid** | **89.2%** | **0.952** | **0.984** | **0.983** |

The entire +4.1pt gain came from muscle classes — confirming the hypothesis that covariance survives amplitude drift.

### 10.4 Key Negative Findings

- **Pure Riemannian is not viable** — near-perfect on muscle but destroys blinks (covariance is blind to the temporal single-vs-double pattern). The *hybrid* shape is essential.
- **`tsupdate=True` was a trap** — best on LOSO but collapses on GroupKFold (clinch 0.653). Plain TangentSpace+SVM is robust on both.
- **Unit correctness:** the tangent space is fit in volts, so inference must convert µV→volts before covariance — a silent unit mismatch would wreck muscle predictions.

---

## 11. The Blink Ceiling — Five Attempts (Central Narrative)

The blink classes (S/O) remained the ceiling at ~0.74/0.78. Five independent methods attacked single-vs-double-blink discrimination:

| # | Method | Result | Why it failed |
|---|--------|--------|---------------|
| 1 | Raw peak-count | failed | counts compressed, single≈double |
| 2 | µV peak-count | failed | z-scoring breaks amplitude threshold |
| 3 | Sliding-window count (moving-std) | failed (70.2% vs 77.8%) | 2s windows aren't event-locked |
| 4 | Event-locked epoching | failed at validation gate | single recordings contaminated |
| 5 | **DTW shape-matching** | **SUCCESS (+2.1%)** | shape survives contamination |

### 11.1 The Diagnostic Discovery (Attempts 1-4)

Attempt 4's validation gate produced the crucial finding. Blinks-per-detected-gesture:

| Class | Expected | Detected | Quality |
|-------|----------|----------|---------|
| single | 1 | 2.60 | only 39% clean; 45% are 1s clusters of ≥3 blinks |
| double | 2 | 2.07 | 55% correct ✓ |
| triple | 3 | 3.08 | clean ✓ |

The detector **correctly counts double and triple** — the problem is that single-blink recordings are physically contaminated with multi-blink instances. **When one class's recordings contain instances of another class, no counting method can separate them.** This is data-limited, proven across four independent methods.

### 11.2 The Breakthrough — DTW Shape-Matching (Attempt 5)

**Insight:** Stop counting; compare *shape*. Dynamic Time Warping compares the full waveform morphology with elastic time-warping, so a single (one bump), double (two bumps), and triple (three bumps) have distinct shapes even with timing variation — and a *contaminated* single window still has a shape nearest to clean single exemplars.

**Method:**
```python
TimeSeriesScalerMeanVariance() →
KNeighborsTimeSeriesClassifier(n_neighbors=5, metric="dtw",
    metric_params={"sakoe_chiba_radius": 10})
```
Applied to **Stage 2a** (blink S vs O), on the z-scored frontal waveform (mean of Fp1, Fp2, Fz).

**Critical sub-finding:** DTW *barycenter templates* failed (50.5%) — because the contaminated single class has no meaningful average shape. **KNN exemplar voting** is what survives it: a noisy single window lands nearest to *some* single exemplar even when it can't be averaged or counted.

**Results (LOSO):**

| Model | Overall | macroF1 | S | O |
|-------|---------|---------|---|---|
| Riemann hybrid | 89.2% | 0.888 | 0.742 | 0.778 |
| **DTW hybrid** | **91.3%** | **0.913** | **0.806** | **0.841** |

**Latency:** 14 ms/window — well under the 200ms step, real-time confirmed.

---

## 12. Final Architecture

The production model is a **three-way hybrid**, each branch using the method matched to its signal physiology:

```
                    Window (2s)
                        │
                  Activity Gate
                        │
        Stage 1: blink vs muscle (features)
                        │
            ┌───────────┴───────────┐
          blink                   muscle
            │                       │
   Stage 2a: S vs O          Stage 2b: C vs L vs R
   DTW-KNN on waveform       Riemannian covariance
   (shape > count)           (covariance > amplitude)
            │                       │
            └───────────┬───────────┘
                        │
                  Confidence gate (>0.60)
                        │
                  FSM (3 consecutive)
                        │
              Arduino serial (S/O/C/L/R)
```

### 12.1 Why Each Method Fits Its Branch

| Branch | Method | Physiological rationale |
|--------|--------|------------------------|
| Stage 1 | Hand-crafted features | EOG vs EMG separation is easy (98-100%) |
| Stage 2a (blink) | DTW shape-matching | temporal pattern (bump count) survives contamination |
| Stage 2b (muscle) | Riemannian covariance | spatial structure survives amplitude drift |

---

## 13. Final Results

### 13.1 Performance Progression (LOSO)

| Architecture | Overall | macro-F1 |
|--------------|---------|----------|
| Flat RandomForest | 85.1% | 0.837 |
| Hierarchical | 85.1% | 0.839 |
| + Riemannian muscle | 89.2% | 0.888 |
| **+ DTW blinks (final)** | **91.3%** | **0.913** |

### 13.2 Final Per-Class F1

| Command | Class | F1 |
|---------|-------|-----|
| S | double_blink | 0.806 |
| O | single_blink | 0.841 |
| C | clinch | 0.952 |
| L | bruxism_left | 0.984 |
| R | bruxism_right | 0.983 |

### 13.3 Real-Time Characteristics
- Per-window latency: 14 ms (DTW Stage 2a), well under 200ms step
- Activity gate: 20µV threshold (rest 7-13µV, active 30-200µV)
- Confidence threshold: 0.60
- FSM confirmation: 3 consecutive identical predictions

---

## 14. Key Scientific Contributions

1. **Architecture over features:** When gesture classes have fundamentally different signal types (EOG vs EMG), a single flat classifier cannot apply features conditionally. Routing each gesture to a physiology-matched method outperforms any monolithic model.

2. **Covariance survives amplitude drift:** For cross-session muscle classification, Riemannian geometry (inter-channel covariance) robustly beats amplitude-based features (TKEO), which fail to generalize across recording days.

3. **Shape survives contamination:** For blink sub-classification with contaminated labels, DTW shape-matching with exemplar (KNN) voting succeeds where five event-counting methods failed. Barycenter templates fail because contaminated classes have no meaningful average shape.

4. **Rigorous leakage methodology:** Epoch-overlap leakage inflated accuracy by 8-10 points; the shuffle test (chance-level with permuted labels) and recording-grouped cross-validation are essential for honest BCI evaluation.

---

## 15. Limitations & Future Work

### 15.1 Limitations
- **Single subject** — the model is subject-specific (standard for BCIs requiring calibration). Cross-subject transfer would require multi-subject data.
- **Single-blink contamination** — the recorded single-blink data contains multi-blink clusters; cleaner recordings with deliberate pauses would likely lift S/O further.
- **Hardware mismatch** — training data is from a 19-channel medical device; the deployment target (Emotiv EPOC X, 14 channels, 45Hz hardware filter) has different channels. Channel mapping (T3/T4 → T7/T8; Fp1/Fp2 → AF3/AF4) is partial; the safest path is re-calibration on the Emotiv directly.

### 15.2 Future Work
1. **Clean blink re-recording** with deliberate 1.5s pauses between gestures — the event-locked DTW harness is ready to exploit this.
2. **Transfer learning:** build a general multi-subject model, then fine-tune per user with 5-10 minutes of calibration data.
3. **Emotiv deployment:** re-record/calibrate on the target hardware; raw access via CyKit (bypassing Cortex).
4. **Synchronized markers:** record event markers on the EEG device itself for clean ground-truth validation.

---

## 16. Reproducibility — Codebase

```
eeg_bci/
├── config.py              All parameters, label/command maps
├── loader.py              Auto-scans sessions, assigns labels
├── preprocessing.py       crop→notch→bandpass→CAR→epoch→reject
├── features.py            93-feature superset, channel-aware
├── activity_gate.py       Energy-based window filtering
├── riemann.py             TS+SVM and MDM builders
├── hierarchical.py        Flat, Hierarchical, RiemannHybrid, DtwRiemannHybrid
├── train.py               Flat model training
├── train_hierarchical.py  Hierarchical training
├── train_hybrid.py        Riemann hybrid training
├── train_dtw_hybrid.py    DTW hybrid training (production)
├── inference.py           Real-time: --model dtw|hybrid|hierarchical|flat
├── eval_loso.py           Leave-One-Session-Out evaluation
├── eval_riemann.py        Riemannian benchmark
└── (experiment scripts kept as reproducible record)

models/
├── dtw_hybrid_model.pkl   PRODUCTION (91.3% LOSO)
├── hybrid_model.pkl       Riemann hybrid (89.2%)
├── hierarchical_model.pkl (85.1%)
└── best_model.pkl         Flat (85.1%)
```

**Dependencies:** mne, numpy, scipy, scikit-learn, imbalanced-learn, pyriemann, tslearn, pywavelets, pyserial, pandas.

---

## Appendix A — Complete Experiment Log

| Phase | Experiment | Outcome |
|-------|-----------|---------|
| Taxonomy | 5→6 class split | +3.0% |
| Taxonomy | 6→5 class (drop triple) | cleaner, robust |
| Epoching | Activity gating | +3.1% |
| Epoching | Session-simulating augmentation | −1.1% (rejected) |
| Features | DWT full | −14.4% (rejected) |
| Features | DWT rel-energy only | break-even (rejected) |
| Features | TKEO | −5.7% (rejected) |
| Features | EMG descriptors | helps muscle, kept for Stage 2b |
| Architecture | Hierarchical (flat→2-stage) | +5.0% (GroupKFold) |
| Muscle | Riemannian Stage 2b | +4.1% (LOSO) |
| Muscle | tsupdate=True | rejected (collapses on GKF) |
| Blink | Raw peak-count | rejected |
| Blink | µV peak-count | rejected |
| Blink | Sliding-window count | rejected |
| Blink | Event-locked epoching | rejected (contamination diagnosed) |
| Blink | DTW-KNN shape-matching | +2.1% (LOSO) — FINAL |
| Blink | DTW barycenter templates | rejected (50.5%) |

---

## Appendix B — Honest Numbers Reference

| Protocol | What it measures | Number |
|----------|-----------------|--------|
| Random StratifiedKFold | inflated (overlap leakage) | ~85% — DO NOT cite |
| Shuffle test | pipeline integrity | 21% (≈chance) ✓ clean |
| GroupKFold (recording) | development metric | 88.0% (final hybrid) |
| **LOSO (final, honest)** | **cross-session deployment** | **91.3%** ✓ cite this |

---

*This documentation captures the complete development history of the project for academic publication. All numbers are from the honest LOSO protocol unless otherwise noted.*
