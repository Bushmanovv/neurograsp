import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token } from '../lib/svg.js';
import { REALTIME } from '../content/data.js';

/* Figure 8 — the three refusals between a prediction and the hand,
   and how much of the time budget the model actually uses. */

/* A scripted second and a half of live operation. Each entry is one
   200 ms window. `pass` records which gate it clears. */
const STREAM = [
  { conf: 0.31, cls: null, gate: false, note: 'rest' },
  { conf: 0.44, cls: 'C',  gate: true,  note: 'low confidence' },
  { conf: 0.71, cls: 'C',  gate: true,  note: '' },
  { conf: 0.83, cls: 'C',  gate: true,  note: '' },
  { conf: 0.52, cls: 'L',  gate: true,  note: 'low confidence' },
  { conf: 0.88, cls: 'C',  gate: true,  note: 'confirmed' },
  { conf: 0.79, cls: 'C',  gate: true,  note: '' },
];

export default {
  id: 'realtime',
  label: 'Fig. 8 — Live operation',
  provenance: 'Ch. 12 · window sequence is illustrative of the stated rules',
  schematic: true,
  caption:
    'Five predictions per second. A window below the energy gate or the confidence threshold is treated as no information — it neither advances the confirmation run nor resets it. Only a confident disagreement resets. The rules and thresholds are the report\'s; this particular sequence is drawn to demonstrate them.',
  steps: ['Stream', 'Gates', 'Budget'],

  build(stage) {
    const W = 1000, H = 470;
    const s = svg(`0 0 ${W} ${H}`);
    stage.appendChild(s);

    const c = {
      rule: token('--rule'), ink: token('--ink'), faint: token('--ink-faint'),
      eog: token('--eog'), emg: token('--emg'), oxide: token('--oxide'),
      paper: token('--paper-raised'),
    };

    /* ---------- the stream ------------------------------------------ */
    const SX = 130, SW = 820, COL = SW / STREAM.length;
    const head = group(s, { opacity: 0 });
    text(head, `${REALTIME.predictionsPerSecond} PREDICTIONS PER SECOND · ${REALTIME.stepSeconds}s STEP`, {
      x: 0, y: 24, class: 't-label', 'letter-spacing': '0.08em',
    });
    ['prediction', `confidence ≥ ${REALTIME.confidenceThreshold.toFixed(2)}`, `run of ${REALTIME.fsmRun}`].forEach((lab, i) => {
      text(head, lab, { x: 0, y: 74 + i * 62, class: 't-axis' });
      el('line', { x1: 0, y1: 84 + i * 62, x2: W, y2: 84 + i * 62, stroke: c.rule, 'stroke-width': 0.6 }, head);
    });

    let run = 0, last = null, confirmedAt = -1;
    const windows = STREAM.map((w, i) => {
      const x = SX + i * COL;
      const g = group(s, { opacity: 0 });
      const passes = w.gate && w.conf >= REALTIME.confidenceThreshold;

      /* row 1 — the raw prediction */
      const colour = w.cls === 'C' ? c.emg : w.cls === 'L' ? c.emg : c.faint;
      el('rect', { x, y: 48, width: COL - 10, height: 30, rx: 2, fill: c.paper, stroke: w.gate ? c.rule : c.faint, 'stroke-dasharray': w.gate ? null : '3 3' }, g);
      text(g, w.cls || '—', { x: x + (COL - 10) / 2, y: 68, 'text-anchor': 'middle', class: 't-value', fill: w.gate ? colour : c.faint });

      /* row 2 — confidence */
      const barW = (COL - 10) * w.conf;
      el('rect', { x, y: 110, width: COL - 10, height: 30, fill: c.ink, opacity: 0.05 }, g);
      el('rect', { x, y: 110, width: barW, height: 30, fill: passes ? c.emg : c.oxide, opacity: passes ? 0.7 : 0.35 }, g);
      text(g, w.conf.toFixed(2), { x: x + 6, y: 130, class: 't-axis', 'font-size': 10 });

      /* row 3 — the FSM run counter */
      if (passes) {
        if (w.cls === last) run += 1; else { run = 1; last = w.cls; }
      }
      const confirmed = passes && run >= REALTIME.fsmRun && confirmedAt < 0;
      if (confirmed) confirmedAt = i;
      const shown = passes ? Math.min(run, REALTIME.fsmRun) : null;

      el('rect', {
        x, y: 172, width: COL - 10, height: 30, rx: 2,
        fill: confirmed ? c.emg : c.paper,
        stroke: confirmed ? c.emg : c.rule,
        'stroke-dasharray': passes ? null : '3 3',
      }, g);
      text(g, shown === null ? '·' : String(shown), {
        x: x + (COL - 10) / 2, y: 192, 'text-anchor': 'middle',
        class: 't-value', fill: confirmed ? c.paper : passes ? c.ink : c.faint,
      });

      if (w.note) {
        text(g, w.note.toUpperCase(), {
          x: x + (COL - 10) / 2, y: 218, 'text-anchor': 'middle',
          class: 't-axis', 'font-size': 8.5,
          fill: w.note === 'confirmed' ? c.emg : c.oxide,
          'letter-spacing': '0.08em',
        });
      }
      return g;
    });

    /* The emitted command. STREAM is hand-written to demonstrate the
       rules, so it is possible to edit it into a sequence that never
       reaches a run of three — in which case there is no command to
       draw, and drawing one anyway would put the callout off-canvas. */
    const emit = group(s, { opacity: 0 });
    if (confirmedAt < 0) {
      console.warn('[realtime] STREAM never reaches a confirmed run — no command emitted');
    } else {
      const ex = SX + confirmedAt * COL + (COL - 10) / 2;
      el('path', { d: `M ${ex} 232 L ${ex} 258`, stroke: c.emg, 'stroke-width': 1.25 }, emit);
      el('rect', { x: ex - 90, y: 258, width: 180, height: 34, rx: 2, fill: c.emg }, emit);
      text(emit, 'clinch → UART', {
        x: ex, y: 280, 'text-anchor': 'middle', class: 't-value', fill: c.paper,
      });
      text(emit, `${REALTIME.baud} baud · newline-terminated label`, {
        x: ex, y: 306, 'text-anchor': 'middle', class: 't-axis', 'font-size': 9.5,
      });
    }

    /* ---------- latency budget -------------------------------------- */
    const LY = 366;
    const budget = group(s, { opacity: 0 });
    el('line', { x1: 0, y1: LY - 26, x2: W, y2: LY - 26, stroke: c.ink, 'stroke-width': 1 }, budget);
    text(budget, 'PER-WINDOW COMPUTE AGAINST THE REAL-TIME BUDGET', { x: 0, y: LY - 6, class: 't-label', 'letter-spacing': '0.08em' });

    const LBX = 0, LBW = 820;
    el('rect', { x: LBX, y: LY + 14, width: LBW, height: 34, fill: c.ink, opacity: 0.05 }, budget);
    el('line', { x1: LBX + LBW, y1: LY + 8, x2: LBX + LBW, y2: LY + 54, stroke: c.ink, 'stroke-width': 1.25 }, budget);
    text(budget, `${REALTIME.budgetMs} ms — next window due`, {
      x: LBX + LBW - 8, y: LY + 68, 'text-anchor': 'end', class: 't-axis',
    });

    const usedW = (REALTIME.latencyMs / REALTIME.budgetMs) * LBW;
    const used = el('rect', { x: LBX, y: LY + 14, width: 0, height: 34, fill: c.emg }, budget);
    text(budget, `${REALTIME.latencyMs} ms`, { x: LBX + usedW + 12, y: LY + 36, class: 't-value', fill: c.emg });
    text(budget, `${REALTIME.utilisationPercent}% of the available time — DTW against stored exemplars dominates`, {
      x: LBX + usedW + 12, y: LY + 52, class: 't-axis', 'font-size': 9.5,
    });

    /* ---------- timeline -------------------------------------------- */
    const tl = gsap.timeline();
    tl.addLabel('stream', 0)
      .to(head, { opacity: 1, duration: 0.35 })
      .to(windows, { opacity: 1, duration: 0.28, stagger: 0.12 }, '-=0.1')
      .addLabel('gates', '+=0.1')
      .to(emit, { opacity: 1, duration: 0.4 }, 'gates')
      .addLabel('budget', '+=0.2')
      .to(budget, { opacity: 1, duration: 0.35 }, 'budget')
      .to(used, { attr: { width: usedW }, duration: 0.7, ease: 'power2.out' }, '-=0.15');

    return { timeline: tl, stepAt: stepsFrom(tl, ['stream', 'gates', 'budget']) };
  },
};
