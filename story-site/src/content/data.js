/* ============================================================
   DATA — every number the diagrams draw.
   All values transcribed from ENCS5300-Section21-Report.pdf.
   Each block notes the table it came from so you can check it.
   Edit here; the charts rebuild from these values.
   ============================================================ */

/* The five commands. Ch. 6 §6.3, Ch. 3 §3.2–3.4 */
export const COMMANDS = [
  { key: 'single_blink',  code: 'O', label: 'Single blink',  family: 'eog', sites: ['Fp1', 'Fp2'], action: 'Open hand',    f1: 0.828 },
  { key: 'double_blink',  code: 'S', label: 'Double blink',  family: 'eog', sites: ['Fp1', 'Fp2'], action: 'Confirm',      f1: 0.843 },
  { key: 'clinch',        code: 'C', label: 'Jaw clinch',    family: 'emg', sites: ['T3', 'T4'],   action: 'Close hand',   f1: 0.953 },
  { key: 'bruxism_left',  code: 'L', label: 'Left bruxism',  family: 'emg', sites: ['T3'],         action: 'Rotate left',  f1: 0.987 },
  { key: 'bruxism_right', code: 'R', label: 'Right bruxism', family: 'emg', sites: ['T4'],         action: 'Rotate right', f1: 0.981 },
];

/* Acquisition. Ch. 4, Ch. 6, Ch. 7 */
export const RIG = {
  channels: 19,
  samplingHz: 200,
  sessions: 3,
  recordings: 15,
  epochSeconds: 2.0,
  epochSamples: 400,
  offlineStepSeconds: 0.5,
  offlineStepSamples: 100,
  overlapPercent: 75,
  sharedSamples: 300,
  realtimeStepSeconds: 0.2,
  realtimeStepSamples: 40,
  notchHz: 50,
  bandpass: [1, 45],
};

/* Dataset size before/after the activity gate. Table 6.4 */
export const GATE_RETENTION = [
  { key: 'double_blink',  before: 536, after: 255, pct: 47.6 },
  { key: 'single_blink',  before: 589, after: 262, pct: 44.5 },
  { key: 'clinch',        before: 490, after: 165, pct: 33.7 },
  { key: 'bruxism_left',  before: 415, after: 239, pct: 57.6 },
  { key: 'bruxism_right', before: 534, after: 325, pct: 60.9 },
];
export const GATE_TOTALS = { before: 2564, after: 1246, pct: 48.6, accuracyGain: 3.1 };

/* Extended feature experiments. Table 8.5 — GroupKFold, vs a 77.2% baseline.
   `split` records the class-specific effect where the report gives one. */
export const FEATURE_LEDGER = [
  {
    name: 'DWT, full',
    detail: '108 features',
    delta: -14.4,
    verdict: 'rejected',
    split: 'Amplitude-scaled wavelet coefficients act as noise, not signal.',
  },
  {
    name: 'DWT, relative energy',
    detail: '36 features',
    delta: 0.1,
    verdict: 'rejected',
    split: 'Helps the blink classes, costs clinch. Nets to nothing.',
  },
  {
    name: 'Teager–Kaiser energy',
    detail: 'TKEO',
    delta: -5.7,
    verdict: 'rejected',
    split: 'A squared-amplitude measure. Does not survive cross-session drift.',
  },
  {
    name: 'EMG descriptors',
    detail: 'WL, SSC, WAMP, CV',
    delta: -3.1,
    verdict: 'kept for the muscle branch only',
    split: 'clinch F1 +0.06 and bruxism_left F1 +0.06 — while hurting the blinks.',
  },
];
export const FEATURE_BASELINE = { protocol: 'GroupKFold', accuracy: 77.2 };

/* The four-test leakage audit. Table 9.1, Table 9.3 */
export const PROTOCOLS = [
  {
    name: 'Random StratifiedKFold',
    value: 85.0,
    display: '~80–85%',
    status: 'leaks',
    note: 'Adjacent epochs share 300 of 400 samples. Documented as a negative example — never cited.',
  },
  {
    name: 'GroupKFold (recording-level)',
    value: 88.0,
    display: '88.0%',
    status: 'clean',
    note: 'No overlap leakage, but training and test can still come from the same recording day.',
  },
  {
    name: 'Leave-One-Session-Out',
    value: 91.3,
    display: '91.3%',
    status: 'headline',
    note: 'An entire unseen recording day. The only figure the report cites as the accuracy of the system.',
  },
];
export const SHUFFLE_TEST = { observed: 21, chance: 20, classes: 5 };

/* Cumulative architecture progression under LOSO. Table 9.11 */
export const PROGRESSION = [
  { name: 'Flat Random Forest',        accuracy: 85.1, macroF1: 0.837, delta: null, note: 'baseline' },
  { name: 'Hierarchical routing',      accuracy: 85.1, macroF1: 0.839, delta: 0.0,  note: 'same accuracy, better macro-F1, cleaner routing' },
  { name: '+ Riemannian muscle branch', accuracy: 89.2, macroF1: 0.888, delta: 4.1, note: 'covariance survives amplitude drift' },
  { name: '+ DTW blink branch',        accuracy: 91.3, macroF1: 0.913, delta: 2.1,  note: 'shape survives label contamination' },
];

/* Per-fold LOSO accuracy. Table 10.1 */
export const FOLDS = [
  { session: 'Session 1', epochs: 368, flat: 84.8, hierarchical: 85.3, hybrid: 90.2 },
  { session: 'Session 2', epochs: 369, flat: 83.5, hierarchical: 82.7, hybrid: 88.1 },
  { session: 'Session 3', epochs: 509, flat: 87.0, hierarchical: 87.2, hybrid: 95.7 },
];

/* Per-class performance, pooled across all 3 LOSO folds. Table 10.2 */
export const PER_CLASS = [
  { key: 'single_blink',  precision: 0.867, recall: 0.792, f1: 0.828, support: 255 },
  { key: 'double_blink',  precision: 0.808, recall: 0.882, f1: 0.843, support: 262 },
  { key: 'clinch',        precision: 0.931, recall: 0.976, f1: 0.953, support: 165 },
  { key: 'bruxism_left',  precision: 1.000, recall: 0.975, f1: 0.987, support: 239 },
  { key: 'bruxism_right', precision: 0.988, recall: 0.975, f1: 0.981, support: 325 },
];

/* Confusion matrix, pooled, 1246 predictions. Table 10.3
   Row = true class, column = predicted class, in COMMANDS order. */
export const CONFUSION = {
  order: ['single_blink', 'double_blink', 'clinch', 'bruxism_left', 'bruxism_right'],
  rows: [
    [202,  52,   1,   0,   0],
    [ 30, 231,   0,   0,   1],
    [  0,   2, 161,   0,   2],
    [  1,   1,   3, 233,   1],
    [  0,   0,   8,   0, 317],
  ],
  total: 1246,
  correct: 1144,
  errors: 102,
  blinkConfusion: 82,
  blinkConfusionShare: 80.4,
  crossFamilyErrors: 2,
};

/* Headline. Ch. 10 §10.1 — two aggregations of the same model. */
export const HEADLINE = {
  unweighted: { accuracy: 91.3, macroF1: 0.913, basis: 'unweighted mean of the 3 LOSO folds' },
  pooled:     { accuracy: 91.8, macroF1: 0.918, basis: 'pooled over all 1,246 held-out predictions' },
  baseline:   { accuracy: 85.1, name: 'flat Random Forest' },
};

/* The five blink attempts. Table 9.7 */
export const BLINK_ATTEMPTS = [
  { n: 1, method: 'Raw peak count',        outcome: 'failed',  why: 'Counts compress together — single looks like double.' },
  { n: 2, method: 'Microvolt peak count',  outcome: 'failed',  why: 'Z-scoring breaks the absolute amplitude threshold it relies on.' },
  { n: 3, method: 'Sliding-window count',  outcome: 'failed',  why: '2 s windows are not event-locked to individual blinks.' },
  { n: 4, method: 'Event-locked epoching', outcome: 'failed',  why: 'Failed at the validation gate — and diagnosed the real problem.' },
  { n: 5, method: 'DTW shape-matching',    outcome: 'kept',    why: 'Shape survives the contamination that counting cannot.' },
];

/* The contamination diagnostic. Table 9.8 */
export const CONTAMINATION = [
  { key: 'single_blink', expected: 1, detected: 2.60, clean: 39, note: '45% are clusters of three or more blinks over ≥1 s' },
  { key: 'double_blink', expected: 2, detected: 2.07, clean: 55, note: 'broadly as intended' },
];

/* T3–T4 normalised asymmetry index. Ch. 8 §8.6 */
export const ASYMMETRY = {
  formula: '(A_T4 − A_T3) / (A_T4 + A_T3)',
  bands: [
    { key: 'bruxism_left',  position: -0.55, reading: 'T3 dominant' },
    { key: 'clinch',        position:  0.0,  reading: 'bilateral' },
    { key: 'bruxism_right', position:  0.55, reading: 'T4 dominant' },
  ],
  gain: { class: 'bruxism_left', from: 0.609, to: 0.737, delta: 0.128 },
};

/* Real-time operating characteristics. Ch. 10 §10.6, Ch. 12 */
export const REALTIME = {
  latencyMs: 14,
  budgetMs: 200,
  utilisationPercent: 7,
  predictionsPerSecond: 5,
  gateThresholdUv: 20,
  restRangeUv: [7, 13],
  activeRangeUv: [30, 200],
  confidenceThreshold: 0.60,
  fsmRun: 3,
  confirmSeconds: [0.6, 1.0],
  baud: 115200,
  stepSeconds: 0.2,
};

/* Schematic waveform shapes for Figure 2.
   NOT MEASURED DATA. These are drawn to the morphology the report
   describes in Ch. 3 §3.2–3.3 and Ch. 6 §6.3 — peak counts, the
   200–400 ms inter-blink interval, bilateral vs lateralised jaw
   activation. Replace `sample` with real epoch arrays (400 samples,
   one per class) if you export them; the renderer takes either. */
export const SIGNATURES = [
  {
    key: 'single_blink',
    traces: [
      { site: 'Fp1', kind: 'blink', peaks: [{ at: 0.42, amp: 1.0 }] },
      { site: 'Fp2', kind: 'blink', peaks: [{ at: 0.42, amp: 0.94 }] },
    ],
    reading: 'One deflection. Rapid onset, slower return.',
    scaleNote: '50–300 µV peak-to-peak after bandpass',
  },
  {
    key: 'double_blink',
    traces: [
      { site: 'Fp1', kind: 'blink', peaks: [{ at: 0.34, amp: 0.96 }, { at: 0.50, amp: 1.0 }] },
      { site: 'Fp2', kind: 'blink', peaks: [{ at: 0.34, amp: 0.9 }, { at: 0.50, amp: 0.95 }] },
    ],
    reading: 'Two deflections, 200–400 ms apart.',
    scaleNote: 'inter-blink interval varies trial to trial',
  },
  {
    key: 'clinch',
    traces: [
      { site: 'T3', kind: 'burst', start: 0.28, end: 0.72, amp: 0.92 },
      { site: 'T4', kind: 'burst', start: 0.28, end: 0.72, amp: 0.90 },
    ],
    reading: 'Sustained broadband burst. Both sides, equal.',
    scaleNote: 'bilateral — asymmetry index ≈ 0',
  },
  {
    key: 'bruxism_left',
    traces: [
      { site: 'T3', kind: 'burst', start: 0.32, end: 0.62, amp: 0.95 },
      { site: 'T4', kind: 'burst', start: 0.32, end: 0.62, amp: 0.34 },
    ],
    reading: 'Left temporalis dominates. T3 above T4.',
    scaleNote: 'asymmetry index < 0',
  },
  {
    key: 'bruxism_right',
    traces: [
      { site: 'T3', kind: 'burst', start: 0.32, end: 0.62, amp: 0.33 },
      { site: 'T4', kind: 'burst', start: 0.32, end: 0.62, amp: 0.95 },
    ],
    reading: 'Right temporalis dominates. T4 above T3.',
    scaleNote: 'asymmetry index > 0',
  },
];

/* 10–20 electrode positions used by Figure 1, as fractions of a unit
   circle drawn from above, nose at top. Only the sites the system
   actually reads are labelled; the rest are drawn as context. */
export const MONTAGE = [
  { name: 'Fp1', x: -0.30, y: -0.78, role: 'eog' },
  { name: 'Fp2', x:  0.30, y: -0.78, role: 'eog' },
  { name: 'F7',  x: -0.66, y: -0.46, role: 'context' },
  { name: 'F3',  x: -0.34, y: -0.40, role: 'context' },
  { name: 'Fz',  x:  0.00, y: -0.38, role: 'context' },
  { name: 'F4',  x:  0.34, y: -0.40, role: 'context' },
  { name: 'F8',  x:  0.66, y: -0.46, role: 'context' },
  { name: 'T3',  x: -0.82, y:  0.00, role: 'emg' },
  { name: 'C3',  x: -0.40, y:  0.00, role: 'context' },
  { name: 'Cz',  x:  0.00, y:  0.00, role: 'context' },
  { name: 'C4',  x:  0.40, y:  0.00, role: 'context' },
  { name: 'T4',  x:  0.82, y:  0.00, role: 'emg' },
  { name: 'T5',  x: -0.66, y:  0.46, role: 'context' },
  { name: 'P3',  x: -0.34, y:  0.40, role: 'context' },
  { name: 'Pz',  x:  0.00, y:  0.38, role: 'context' },
  { name: 'P4',  x:  0.34, y:  0.40, role: 'context' },
  { name: 'T6',  x:  0.66, y:  0.46, role: 'context' },
  { name: 'O1',  x: -0.30, y:  0.78, role: 'context' },
  { name: 'O2',  x:  0.30, y:  0.78, role: 'context' },
];
