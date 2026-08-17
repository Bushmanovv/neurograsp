/* ============================================================
   STORY — all prose, in reading order.
   Edit freely. `visual` names a module in src/visuals/index.js;
   set it to null to drop a figure, or reorder sections at will.

   House style used below:
   <span class="num">91.3%</span>        — instrument voice, neutral
   <span class="num num--eog">…</span>   — blink / ocular family
   <span class="num num--emg">…</span>   — jaw / muscular family
   <span class="num num--bad">…</span>   — a failure or a retracted figure
   ============================================================ */

export const HERO = {
  eyebrow: 'Birzeit University · Faculty of Engineering &amp; Technology · ENCS5300',
  title: 'The signal everyone <em>throws away</em>',
  dek: 'Blinks and jaw clenches are what EEG researchers spend their careers filtering out. This project used them to drive a prosthetic hand — and then spent most of its effort proving the result was real.',
  strip: [
    '<b>19</b> channels · 200 Hz',
    '<b>5</b> commands',
    '<b>3</b> sessions · 1,246 gated epochs',
    '<b>Single subject</b> · offline validation',
  ],
  cue: 'Scroll',
};

export const SECTIONS = [
  /* ---------------------------------------------------------- 01 */
  {
    id: 'noise',
    eyebrow: 'The problem',
    title: 'Everything here begins with damage the signal has to route around',
    body: [
      'A myoelectric prosthesis listens to the muscles left in the residual limb. It is an elegant idea that assumes those muscles, and the nerves that drive them, survived. In conflict-affected regions, that assumption often fails: traumatic amputation tends to arrive together with extensive tissue trauma and peripheral nerve damage, which is precisely what leaves myoelectric control ineffective for a substantial share of the people who need it most. Meanwhile the advanced commercial systems cost tens of thousands of dollars and expect clinical infrastructure for fitting and maintenance.',
      'So the control signal has to come from somewhere the damage did not reach. And it has to be cheap enough to actually exist — consumer hardware, open-source software, a printed hand.',
    ],
    visual: null,
  },

  /* ---------------------------------------------------------- 02 */
  {
    id: 'obvious',
    eyebrow: 'The obvious answer',
    title: 'Imagine moving your hand. Now do it reliably, on a Tuesday, with a headset you put on yourself.',
    body: [
      'Motor imagery is the dominant paradigm in EEG-based control, and its appeal is obvious: think about the movement, and the sensorimotor rhythm shifts. Representative systems in the literature report roughly <span class="num">70–85%</span> accuracy on two- to four-class problems, often using considerably more sophisticated machinery than anything here — CSP with LDA, deep CNNs, EEGNet.',
      'The trouble is what the paradigm asks of a person. It rests on subtle rhythm modulations that many users struggle to produce consistently even after extended training, with wide variability between users and a well-documented gap between offline accuracy and anything resembling real-world reliability.',
      'The pivot: stop trying to read the cortex, and start reading the things the cortex reliably produces on request. A voluntary blink registers at the frontal poles as an ocular potential one to two orders of magnitude larger than a motor-imagery modulation. A jaw clench registers at the temporal electrodes as a broadband muscle burst. Neither is a cortical signal, and the report says so on its first page — the blinks are <span class="num num--eog">EOG</span>, the jaw is <span class="num num--emg">EMG</span>, both captured by a scalp EEG montage and processed by a BCI pipeline, but ocular and muscular in origin.',
      'What makes them usable is anatomy rather than neuroscience. The blink runs on the facial nerve; jaw clenching and grinding run on the trigeminal. Both are cranial nerves that leave the brainstem directly and never pass through the brachial plexus or the peripheral nerves of the arm. An amputation at any level of the upper limb leaves them completely untouched.',
    ],
    visual: 'montage',
  },

  /* ---------------------------------------------------------- 03 */
  {
    id: 'vocabulary',
    eyebrow: 'The command set',
    title: 'Five gestures, chosen because they look different from each other',
    body: [
      'The vocabulary is small on purpose. Prosthetic control does not need a rich channel; it needs a handful of commands that are never confused. Two blink gestures at the frontal poles, three jaw gestures at the temporal sites — and within the jaw group, the left/right distinction comes from a single anatomical fact.',
      'The temporalis muscles on either side of the head sit directly beneath T3 and T4. Grinding the jaw leftward preferentially recruits the left one; grinding rightward recruits the right. A symmetric clench recruits both about equally. That three-way pattern collapses into one bounded number — the normalised difference between the two amplitudes — which is the direct algorithmic expression of which muscle is working harder.',
      'This asymmetry index is one of the project\'s claimed contributions, and it earned it: introducing it lifted <span class="num num--emg">bruxism_left</span> F1 from <span class="num">0.609</span> to <span class="num">0.737</span>.',
    ],
    visual: 'signatures',
  },

  /* ---------------------------------------------------------- 04 */
  {
    id: 'features',
    eyebrow: 'First attempt',
    title: 'The engineer\'s instinct is to add features. It failed four times in a row.',
    body: [
      'The base pipeline is conventional and works: notch and bandpass filtering, common average reference, epochs of two seconds, then a channel-aware feature set of 93 values — time-domain statistics, band powers, peak descriptors, the asymmetry index — grouped by the electrodes that physically matter for each artifact type.',
      'Then came the search for more. A full discrete wavelet decomposition. A relative-energy variant of the same. The Teager–Kaiser energy operator, a classical choice for EMG onset detection. Four classical surface-EMG descriptors straight out of the prosthetics literature. Every one of them was implemented, evaluated, and documented.',
      'Read the aggregate numbers and it looks like a run of bad luck. Read the class-by-class breakdown and something else appears: each family helped one half of the taxonomy and damaged the other. The EMG descriptors that lifted clinch and left bruxism by <span class="num num--emg">+0.06</span> F1 each were pure interference for the blinks, which have no muscle-fibre recruitment pattern to describe. The wavelet variant that helped the blinks cost the clench.',
      'A single flat classifier has no mechanism for this. It must make a feature globally available or globally absent; it cannot apply one conditionally to the half of the taxonomy where it means something.',
    ],
    visual: 'ledger',
    turn: 'The bottleneck was never the feature count. It was the shape of the model.',
  },

  /* ---------------------------------------------------------- 05 */
  {
    id: 'leakage',
    eyebrow: 'The reversal',
    title: 'Then the measuring instrument turned out to be broken',
    body: [
      'Every number above was produced by a pipeline that was, at that point, being evaluated by random cross-validation. It was reporting somewhere around <span class="num num--bad">80–85%</span>, and it was wrong.',
      'Epochs are extracted with a half-second step across a two-second window — <span class="num">75%</span> overlap, which the project wanted for a good reason: gestures near a window boundary still land near-centred in some neighbouring window. But it means two adjacent epochs share <span class="num">300</span> of their <span class="num">400</span> samples. Split those randomly into train and test, and the classifier is graded on data it has very nearly already seen.',
      'Rather than assert the leak, the project audited it. Four independent tests, each isolating a different route by which the answer could reach the model. A strict cross-session check, to see whether the underlying signal was real at all. A check that scaler and feature-selection statistics were only ever fitted on training folds. A direct check for same-recording epochs appearing on both sides of a split. And a label-permutation shuffle test.',
      'That last one is worth pausing on, because it is cheap and it is general. Permute the class labels, change nothing else, and rerun. If accuracy stays above chance, something other than genuine feature content is carrying the answer. Chance for five classes is <span class="num">20%</span>. The pipeline scored <span class="num">21%</span>.',
      'So: no implementation leak, no preprocessing leak, and a headline protocol that leaked badly through epoch overlap. The <span class="num num--bad">80–85%</span> figure was retired — retained in the report only as a documented negative example, with an instruction never to cite it. Everything after this point is reported Leave-One-Session-Out: train on two recording days, test on a third the model has never seen in any form, which is the question deployment actually asks. You put the headset on tomorrow. Does the model still work?',
    ],
    visual: 'leakage',
  },

  /* ---------------------------------------------------------- 06 */
  {
    id: 'representations',
    eyebrow: 'The chase',
    title: 'Two problems, two changes of representation',
    body: [
      'With honest measurement in place, the two halves of the taxonomy failed in two entirely different ways.',
      '<strong>The muscle classes were defeated by drift.</strong> Absolute amplitude is not stable across recording days — electrode placement, impedance, scalp moisture and physiological state all move it. Which is exactly why TKEO underperformed by <span class="num num--bad">−5.7%</span>: it is a squared-amplitude measure, and squared-amplitude measures do not survive a new day. The fix was not a better amplitude feature. It was to stop describing amplitude. Inter-channel covariance matrices, projected into a Riemannian tangent space, encode the spatial structure between channels rather than how large the signal happened to be. The muscle branch gained <span class="num num--emg">+4.1</span> points and pushed all three muscle F1 scores past <span class="num">0.95</span>.',
      '<strong>The blink classes were defeated by their own labels.</strong> Four separate methods were built to tell one blink from two: raw peak counting, microvolt-threshold counting, a sliding-window moving-standard-deviation count, and event-locked epoching. All four failed. The fourth failed usefully — its validation gate ran a blink detector across each nominally labelled recording and found that the recordings themselves were wrong. In trials labelled <em>single blink</em>, the detector found on average <span class="num num--eog">2.60</span> blinks. Only <span class="num num--eog">39%</span> of those recordings were clean; roughly <span class="num num--bad">45%</span> contained clusters of three or more blinks spread over a second or more. Double-blink recordings were substantially better behaved at <span class="num num--eog">55%</span> clean.',
      'When one class\'s recordings physically contain instances of another class, no counting method can separate them, however carefully engineered. That is not a hypothesis — four independently designed counters demonstrated it.',
      'The fifth attempt stopped counting events and started comparing shapes. Dynamic time warping finds an elastic alignment between two waveforms, so a contaminated single-blink window still lands nearest to some genuinely clean single-blink exemplar even when a peak counter would be fooled. One detail mattered enormously: averaged templates failed outright at <span class="num num--bad">50.5%</span>, because a contaminated class has no meaningful average shape — averaging a clean single bump with a triple-bump trial produces a template resembling neither. Nearest-neighbour voting against stored exemplars is what survived. <span class="num num--eog">+2.1</span> points.',
    ],
    visual: 'representations',
  },

  /* ---------------------------------------------------------- 07 */
  {
    id: 'architecture',
    eyebrow: 'The finding',
    title: 'Route each gesture family to the method its physiology deserves',
    body: [
      'The final architecture is a router and two specialists. Hand-crafted features make the easy call first — blink or muscle, a separation that runs at <span class="num">98–100%</span> and effectively eliminates cross-family confusion. Windows routed to <em>blink</em> go to DTW shape-matching. Windows routed to <em>muscle</em> go to Riemannian covariance. Each stage trains only on its own subset of epochs and selects its own columns by name, so muscle features can never reach a blink decision.',
      'Under Leave-One-Session-Out, the finished system reaches <span class="num num--eog">91.3%</span> accuracy with a macro-F1 of <span class="num">0.913</span>, against <span class="num">85.1%</span> for the flat Random Forest baseline. Pooling every held-out prediction rather than averaging the three folds equally gives <span class="num">91.8%</span> and <span class="num">0.918</span> — the same model and the same protocol, differing only in how the folds are aggregated.',
      'Two things about that number deserve emphasis over the number itself. First, the hybrid beats both simpler architectures on <em>every individual fold</em>, not merely on average, so it is not an artefact of one favourable session. Second, look at where the gains came from: the routing scaffold on its own bought nothing in accuracy at all. Every point came from the two specialised sub-classifiers.',
      'This comparison should be read carefully rather than as a claim of a generally superior method. The reason an artifact-based system can outrun motor imagery here is architectural to the problem: voluntary blinks and jaw contractions are large, deliberate, and physiologically distinct from each other. The result is evidence that trading generality for specificity is a good trade <em>for prosthetic control</em> — not that these classifiers would carry the same advantage into a motor-imagery problem. A user with reliable voluntary control of eye and jaw is a good match for this system. A user without it is not.',
    ],
    visual: 'architecture',
    turn: 'When classes have different underlying physiology, no amount of feature engineering on one flat classifier will resolve it. Change the representation instead — once per branch.',
    turnKind: 'found',
  },

  /* ---------------------------------------------------------- 08 */
  {
    id: 'errors',
    eyebrow: 'Where it breaks',
    title: 'The model\'s remaining errors are a portrait of the data problem',
    body: [
      'Of <span class="num">1,246</span> held-out predictions, <span class="num">1,144</span> are correct and <span class="num">102</span> are not. The interesting part is that those 102 are not scattered.',
      '<span class="num num--bad">82</span> of them — <span class="num num--bad">80.4%</span> of all error in the system — are a single blink being called a double, or the reverse. And the asymmetry within that confusion matches the contamination finding precisely: 52 single blinks misread as doubles against 30 the other way, which is what you would expect when the single-blink recordings are the contaminated ones.',
      'Everywhere else the matrix is close to empty. Exactly <span class="num">2</span> epochs out of 1,246 cross the blink/muscle boundary in either direction, confirming the router. Among the muscle classes the small residual confusion is with clinch, which shares electrodes with both bruxism classes and is separated from them only by lateral balance — while left and right bruxism are confused with each other <span class="num num--emg">zero</span> times in either direction, because they sit on opposite signs of the same asymmetry signal.',
      'So the remaining error is not really a classifier problem. It is a recording problem, showing up faithfully in the confusion matrix.',
    ],
    visual: 'errors',
  },

  /* ---------------------------------------------------------- 09 */
  {
    id: 'realtime',
    eyebrow: 'Live operation',
    title: 'Deliberately hard to make the hand do something you did not ask for',
    body: [
      'The deployed pipeline loads the offline-trained model unmodified — same features, same preprocessing, same two branches — and wraps it in machinery whose entire purpose is refusing to act. A rolling two-second buffer is re-classified every 200 ms, five predictions per second. A window whose energy falls below a fixed 20 µV threshold is discarded as rest. A prediction below <span class="num">0.60</span> confidence is discarded as a guess. And nothing reaches the hand until three consecutive surviving predictions agree.',
      'A window that fails the gate or the threshold is treated as no information rather than as a competing vote: it neither advances the run nor resets it, so a brief pause mid-gesture does not force the count back to zero. Only a confident disagreement resets it.',
      'The whole per-window computation costs <span class="num">14 ms</span> against a 200 ms budget — about <span class="num">7%</span> utilisation, dominated by the DTW distance computation against stored exemplars. That headroom is what makes the three-window confirmation practical: three agreeing predictions can arrive within roughly 0.6 seconds of a gesture\'s onset, comfortably inside what reads as responsive.',
      'The philosophy behind every one of those refusals is stated plainly in the report: a missed or delayed command is a minor usability problem, while an incorrectly executed one, on a powered hand near the user\'s own face, is a safety concern.',
    ],
    visual: 'realtime',
  },

  /* ---------------------------------------------------------- 10 */
  {
    id: 'open',
    eyebrow: 'What we still do not know',
    title: 'Five things this project has not earned the right to claim',
    body: [
      'The report is unusually willing to enumerate its own unfinished business, and the honest version of this story ends there rather than on the accuracy figure.',
    ],
    visual: null,
    openList: [
      {
        title: 'It has only ever worked for one person',
        text: 'Every result describes a model calibrated to, and evaluated on, a single subject. This is standard for per-user BCI systems, and Leave-One-Session-Out is the right generalisation target for that design — but nothing here is evidence of cross-subject accuracy. A new user would need to collect their own multi-session dataset and retrain before any of these numbers applied to them.',
      },
      {
        title: 'The blink recordings are still contaminated',
        text: 'DTW resolved the architectural ceiling that four counting methods could not. It did not retroactively clean the tapes. Roughly 45% of single-blink recordings still physically contain multi-blink clusters, and that residue is still the dominant error in the finished model. The highest-leverage improvement available is not another classifier — it is re-recording the single-blink class with deliberate, verified pauses between blinks.',
      },
      {
        title: 'The data and the target hardware are not the same device',
        text: 'Everything was recorded on a 19-channel research-grade amplifier at 200 Hz. The intended deployment target is a 14-channel consumer headset with a different electrode layout and an on-device 45 Hz filter. The channel correspondence is only approximate — T3/T4 map roughly to T7/T8, Fp1/Fp2 roughly to AF3/AF4 — and no data has been collected on the target device at all. This is the single largest piece of unfinished validation in the project, and the accuracy figures should not be assumed to transfer without it.',
      },
      {
        title: 'The hand is built, but not yet driven end to end',
        text: 'The classification pipeline is validated offline. The prosthetic hand is physically fabricated and the control application works in mock mode, but only the firmware scaffold is verified running on the ESP32 — servo control and the device\'s own WiFi access point are still to be built. Closed-loop actuation from a live scalp signal remains future work, and the report does not pretend otherwise.',
      },
      {
        title: 'The live activity gate is a fixed number',
        text: 'Offline, the gate is recording-relative: each epoch is judged against its own recording\'s activity level, which is possible because the whole recording exists in advance. A live stream has no such context, so deployment falls back to a fixed 20 µV threshold sitting in the gap between typical rest and typical gesture amplitudes. It works, and it is fragile in a way the offline gate is not.',
      },
    ],
  },

  /* ---------------------------------------------------------- 11 */
  {
    id: 'close',
    eyebrow: 'In closing',
    title: 'A number is worth exactly as much as the protocol that produced it',
    body: [
      'This is engineering proof-of-concept work, scoped that way from the outset: no amputee trials, no usability study, no regulatory review. What it provides is a complete path from a voluntary blink or jaw contraction, through a classifier that has been audited rather than merely tuned, to a physical hand.',
      'And the thing most worth taking from it is not <span class="num num--eog">91.3%</span>. It is that the same project also produced an <span class="num num--bad">80–85%</span> figure, went looking for the reason it was too good, found it, and threw the number away. The shuffle test that made that possible costs almost nothing to run and belongs in any evaluation pipeline built on overlapping sliding windows.',
    ],
    visual: null,
  },
];

export const COLOPHON = [
  'ENCS5300 · Graduation Project · Section 21',
  'Birzeit University · Faculty of Engineering &amp; Technology',
  'All figures rebuilt from the report\'s own tables. Waveform morphologies in Fig. 2 are schematic.',
];
