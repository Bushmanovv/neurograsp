import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token } from '../lib/svg.js';
import { PER_CLASS, CONFUSION, COMMANDS } from '../content/data.js';

/* Figure 7 — where the remaining 102 errors actually are.
   Two tiers of F1, then the matrix that explains the split. */

export default {
  id: 'errors',
  label: 'Fig. 7 — Per-class performance and confusion',
  provenance: `Tables 10.2–10.3 · LOSO, pooled over ${CONFUSION.total.toLocaleString()} predictions`,
  caption:
    'Rows are the true class, columns the prediction. The diagonal is correct. Almost all remaining error sits in two cells — the direct signature of the contaminated single-blink recordings — while the blink/muscle boundary is crossed exactly twice and the two bruxism classes are never confused with each other.',
  steps: ['Two tiers', 'The matrix', 'The two cells'],

  build(stage) {
    const W = 1000, H = 620;
    const s = svg(`0 0 ${W} ${H}`);
    stage.appendChild(s);

    const c = {
      rule: token('--rule'), ink: token('--ink'), faint: token('--ink-faint'),
      eog: token('--eog'), emg: token('--emg'), oxide: token('--oxide'),
      paper: token('--paper-raised'),
    };
    const byKey = Object.fromEntries(COMMANDS.map((x) => [x.key, x]));

    /* ---------- per-class F1 ---------------------------------------- */
    const BX = 250, BW = 420, BY = 40;
    const f1x = (v) => BX + ((v - 0.75) / 0.25) * BW;

    const head = group(s, { opacity: 0 });
    text(head, 'PER-CLASS F1', { x: 0, y: BY - 12, class: 't-label', 'letter-spacing': '0.1em' });
    [0.8, 0.85, 0.9, 0.95, 1.0].forEach((v) => {
      el('line', { x1: f1x(v), y1: BY, x2: f1x(v), y2: BY + 230, stroke: c.rule, 'stroke-width': 0.6, 'stroke-dasharray': '2 5' }, head);
      text(head, v.toFixed(2), { x: f1x(v), y: BY + 248, 'text-anchor': 'middle', class: 't-axis' });
    });

    const bars = PER_CLASS.map((p, i) => {
      const cmd = byKey[p.key];
      const y = BY + 24 + i * 44;
      const colour = cmd.family === 'eog' ? c.eog : c.emg;
      const g = group(s, { opacity: 0 });
      text(g, cmd.label, { x: 0, y: y + 4, class: 't-value', 'font-size': 12 });
      text(g, `n = ${p.support} · P ${p.precision.toFixed(3)} · R ${p.recall.toFixed(3)}`, { x: 0, y: y + 19, class: 't-axis', 'font-size': 9.5 });
      const rect = el('rect', { x: BX, y: y - 9, width: 0, height: 18, fill: colour, opacity: 0.9 }, g);
      const val = text(g, p.f1.toFixed(3), { x: f1x(p.f1) + 10, y: y + 5, class: 't-value', fill: colour, opacity: 0 });
      return { g, rect, val, target: f1x(p.f1) - BX };
    });

    const tiers = group(s, { opacity: 0 });
    el('line', { x1: 700, y1: BY + 20, x2: 700, y2: BY + 108, stroke: c.eog, 'stroke-width': 2 }, tiers);
    text(tiers, 'BLINK TIER', { x: 712, y: BY + 56, class: 't-axis', fill: c.eog, 'letter-spacing': '0.1em' });
    text(tiers, 'DTW branch', { x: 712, y: BY + 72, class: 't-axis', 'font-size': 9.5 });
    el('line', { x1: 700, y1: BY + 112, x2: 700, y2: BY + 244, stroke: c.emg, 'stroke-width': 2 }, tiers);
    text(tiers, 'MUSCLE TIER', { x: 712, y: BY + 172, class: 't-axis', fill: c.emg, 'letter-spacing': '0.1em' });
    text(tiers, 'Riemannian branch · all above 0.95', { x: 712, y: BY + 188, class: 't-axis', 'font-size': 9.5 });

    /* ---------- confusion matrix ------------------------------------ */
    const MX = 250, MY = 350, CELL = 62;
    const matrix = group(s, { opacity: 0 });
    el('line', { x1: 0, y1: MY - 60, x2: W, y2: MY - 60, stroke: c.ink, 'stroke-width': 1 }, matrix);
    text(matrix, 'CONFUSION MATRIX', { x: 0, y: MY - 40, class: 't-label', 'letter-spacing': '0.1em' });
    text(matrix, 'true class ↓', { x: 0, y: MY - 18, class: 't-axis' });
    text(matrix, 'predicted →', { x: 0, y: MY - 2, class: 't-axis' });

    const cells = [];
    CONFUSION.order.forEach((rowKey, r) => {
      const cmd = byKey[rowKey];
      const colour = cmd.family === 'eog' ? c.eog : c.emg;
      text(matrix, cmd.code, {
        x: MX - 14, y: MY + r * CELL + CELL / 2 + 4,
        'text-anchor': 'end', class: 't-label', fill: colour,
      });
      text(matrix, cmd.code, {
        x: MX + r * CELL + CELL / 2, y: MY - 14,
        'text-anchor': 'middle', class: 't-label', fill: colour,
      });

      const rowTotal = CONFUSION.rows[r].reduce((a, b) => a + b, 0);
      CONFUSION.order.forEach((colKey, k) => {
        const v = CONFUSION.rows[r][k];
        const diag = r === k;
        const share = v / rowTotal;
        const g = group(matrix, { opacity: 0 });
        const x = MX + k * CELL, y = MY + r * CELL;
        const isHot = (r === 0 && k === 1) || (r === 1 && k === 0);

        el('rect', {
          x, y, width: CELL - 3, height: CELL - 3,
          fill: diag ? colour : isHot ? c.oxide : c.ink,
          opacity: v === 0 ? 0.03 : diag ? 0.14 + share * 0.5 : isHot ? 0.16 + share * 0.6 : 0.05 + share * 0.5,
        }, g);
        if (isHot) {
          el('rect', {
            x, y, width: CELL - 3, height: CELL - 3,
            fill: 'none', stroke: c.oxide, 'stroke-width': 1.5, class: 'hot', opacity: 0,
          }, g);
        }
        text(g, String(v), {
          x: x + (CELL - 3) / 2, y: y + (CELL - 3) / 2 + 5,
          'text-anchor': 'middle',
          class: v > 0 ? 't-value' : 't-axis',
          'font-size': v > 0 ? 13 : 10,
          fill: v === 0 ? c.faint : diag ? c.ink : isHot ? c.oxide : c.ink,
        }, g);
        cells.push({ g, isHot, order: r * 5 + k });
      });
    });

    /* ---------- the readout ----------------------------------------- */
    const RX = MX + 5 * CELL + 40;
    const readout = group(s, { opacity: 0 });
    text(readout, `${CONFUSION.errors}`, { x: RX, y: MY + 26, class: 't-big', fill: c.ink });
    text(readout, `errors out of ${CONFUSION.total.toLocaleString()}`, { x: RX, y: MY + 44, class: 't-axis' });

    text(readout, `${CONFUSION.blinkConfusion}`, { x: RX, y: MY + 100, class: 't-big', fill: c.oxide });
    text(readout, `of them are single ↔ double blink`, { x: RX, y: MY + 118, class: 't-axis', fill: c.oxide });
    text(readout, `${CONFUSION.blinkConfusionShare}% of all error in the system`, { x: RX, y: MY + 134, class: 't-axis', 'font-size': 9.5 });

    text(readout, `${CONFUSION.crossFamilyErrors}`, { x: RX, y: MY + 190, class: 't-big', fill: c.faint });
    text(readout, 'epochs cross the blink/muscle boundary', { x: RX, y: MY + 208, class: 't-axis' });

    text(readout, '0', { x: RX, y: MY + 264, class: 't-big', fill: c.emg });
    text(readout, 'left ↔ right bruxism confusions', { x: RX, y: MY + 282, class: 't-axis', fill: c.emg });

    /* ---------- timeline -------------------------------------------- */
    const tl = gsap.timeline();
    tl.addLabel('tiers', 0);
    tl.to(head, { opacity: 1, duration: 0.35 });
    bars.forEach((b) => {
      tl.to(b.g, { opacity: 1, duration: 0.22 }, '+=0.04');
      tl.to(b.rect, { attr: { width: b.target }, duration: 0.6, ease: 'power2.out' }, '-=0.12');
      tl.to(b.val, { opacity: 1, duration: 0.22 }, '-=0.25');
    });
    tl.to(tiers, { opacity: 1, duration: 0.4 }, '+=0.1')
      .addLabel('matrix', '+=0.2')
      .to(matrix, { opacity: 1, duration: 0.35 }, 'matrix')
      .to(cells.map((c2) => c2.g), { opacity: 1, duration: 0.35, stagger: 0.018 }, '-=0.1')
      .to(readout, { opacity: 1, duration: 0.4 }, '+=0.1')
      .addLabel('hot', '-=0.3')
      .to(matrix.querySelectorAll('.hot'), { opacity: 1, duration: 0.4 }, 'hot');

    return { timeline: tl, stepAt: stepsFrom(tl, ['tiers', 'matrix', 'hot']) };
  },
};
