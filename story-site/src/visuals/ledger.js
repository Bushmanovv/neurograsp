import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token, wrap } from '../lib/svg.js';
import { FEATURE_LEDGER, FEATURE_BASELINE } from '../content/data.js';

/* Figure 3 — every extended feature family, and the split underneath
   the aggregate. This is the figure that earns the architecture. */

export default {
  id: 'ledger',
  label: 'Fig. 3 — What more features bought',
  provenance: `Table 8.5 · GroupKFold, vs a ${FEATURE_BASELINE.accuracy}% baseline`,
  caption:
    'Accuracy change against the 93-feature baseline. These were measured under GroupKFold, the development protocol — the stricter cross-session protocol arrives later in the story, and the ranking here is not affected by it. The right-hand column is the part the aggregate hides.',
  steps: ['Aggregate', 'The split'],

  build(stage) {
    const W = 1000, ROW = 96, H = FEATURE_LEDGER.length * ROW + 120;
    const s = svg(`0 0 ${W} ${H}`);
    stage.appendChild(s);

    const c = {
      rule: token('--rule'),
      ink: token('--ink'),
      faint: token('--ink-faint'),
      oxide: token('--oxide'),
      eog: token('--eog'),
      emg: token('--emg'),
    };

    const ZERO = 470;
    const PPP = 21; // px per percentage point
    const clampX = (v) => ZERO + v * PPP;

    /* axis */
    const axis = group(s, { opacity: 0 });
    el('line', { x1: ZERO, y1: 54, x2: ZERO, y2: H - 46, stroke: c.ink, 'stroke-width': 1 }, axis);
    text(axis, '0', { x: ZERO, y: 44, 'text-anchor': 'middle', class: 't-axis' });
    [-15, -10, -5, 5].forEach((v) => {
      const x = clampX(v);
      el('line', { x1: x, y1: 54, x2: x, y2: H - 46, stroke: c.rule, 'stroke-width': 0.6, 'stroke-dasharray': '2 5' }, axis);
      text(axis, `${v > 0 ? '+' : ''}${v}`, { x, y: 44, 'text-anchor': 'middle', class: 't-axis' });
    });
    text(axis, 'ACCURACY CHANGE, PERCENTAGE POINTS', {
      x: ZERO, y: H - 24, 'text-anchor': 'middle', class: 't-axis', 'letter-spacing': '0.12em',
    });

    const rows = FEATURE_LEDGER.map((f, i) => {
      const y = 84 + i * ROW;
      const neg = f.delta < 0;
      const colour = neg ? c.oxide : c.faint;
      const g = group(s, { opacity: 0 });

      el('line', { x1: 0, y1: y - 20, x2: W, y2: y - 20, stroke: c.rule, 'stroke-width': 1 }, g);
      text(g, f.name, { x: 0, y: y + 6, class: 't-value' });
      text(g, f.detail, { x: 0, y: y + 24, class: 't-axis' });

      const rect = el('rect', {
        x: neg ? ZERO : ZERO, y: y - 10, width: 0, height: 22,
        fill: colour, opacity: neg ? 0.85 : 0.6,
      }, g);

      const label = text(g, `${f.delta > 0 ? '+' : ''}${f.delta}`, {
        x: clampX(f.delta) + (neg ? -10 : 10), y: y + 6,
        'text-anchor': neg ? 'end' : 'start',
        class: 't-value', fill: neg ? c.oxide : c.ink, opacity: 0,
      });

      /* the split — the class-specific reality under the aggregate */
      const split = group(g, { opacity: 0 });
      el('line', { x1: 620, y1: y - 6, x2: 620, y2: y + 30, stroke: c.rule, 'stroke-width': 1 }, split);
      const words = wrap(f.split, 46);
      words.forEach((line, j) => {
        text(split, line, { x: 636, y: y + 2 + j * 15, class: 't-axis', 'font-size': 10.5 });
      });
      text(split, f.verdict.toUpperCase(), {
        x: 636, y: y + 2 + words.length * 15 + 4,
        class: 't-axis', 'letter-spacing': '0.1em',
        fill: f.verdict.startsWith('kept') ? c.emg : c.oxide,
      });

      return { g, rect, label, split, target: Math.abs(f.delta) * PPP, neg };
    });

    /* the conclusion line */
    const CY = H - 62;
    const concl = group(s, { opacity: 0 });
    el('line', { x1: 0, y1: CY - 22, x2: W, y2: CY - 22, stroke: c.ink, 'stroke-width': 1 }, concl);
    text(concl, 'EVERY FAMILY HELPED ONE HALF OF THE TAXONOMY AND HURT THE OTHER.', {
      x: 0, y: CY, class: 't-label', 'letter-spacing': '0.08em',
    });
    text(concl, 'A flat classifier cannot apply a feature conditionally.', {
      x: 0, y: CY + 20, class: 't-axis',
    });

    /* timeline */
    const tl = gsap.timeline();
    tl.addLabel('aggregate', 0);
    tl.to(axis, { opacity: 1, duration: 0.4 });
    rows.forEach((r) => {
      tl.to(r.g, { opacity: 1, duration: 0.25 }, '+=0.05');
      tl.to(r.rect, {
        attr: { width: r.target, x: r.neg ? ZERO - r.target : ZERO },
        duration: 0.6, ease: 'power2.out',
      }, '-=0.1');
      tl.to(r.label, { opacity: 1, duration: 0.25 }, '-=0.25');
    });
    tl.addLabel('split', '+=0.2');
    tl.to(rows.map((r) => r.split), { opacity: 1, duration: 0.4, stagger: 0.1 }, 'split');
    tl.to(concl, { opacity: 1, duration: 0.4 }, '+=0.15');

    return { timeline: tl, stepAt: stepsFrom(tl, ['aggregate', 'split']) };
  },
};
