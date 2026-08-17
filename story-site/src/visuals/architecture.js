import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token, primeDraw } from '../lib/svg.js';
import { PROGRESSION, FOLDS, HEADLINE } from '../content/data.js';

/* Figure 6 — the finished architecture, and what each piece of it was
   worth under the honest protocol. The waterfall is the reveal. */

export default {
  id: 'architecture',
  label: 'Fig. 6 — Routing, and what it bought',
  provenance: 'Fig. 9.2 · Tables 9.11 and 10.1 · LOSO',
  caption:
    'Each stage trains only on its own subset of epochs and selects its own feature columns by name. Note where the accuracy came from: the routing scaffold on its own was worth nothing, and both gains belong to the specialised branches.',
  steps: ['Router', 'Branches', 'Progression', 'Per fold'],

  build(stage) {
    const W = 1000, H = 660;
    const s = svg(`0 0 ${W} ${H}`);
    stage.appendChild(s);

    const c = {
      rule: token('--rule'), ink: token('--ink'), faint: token('--ink-faint'),
      eog: token('--eog'), emg: token('--emg'), paper: token('--paper-raised'),
    };

    const box = (parent, x, y, w, h, title, sub, colour) => {
      const g = group(parent, { opacity: 0 });
      el('rect', { x, y, width: w, height: h, rx: 2, fill: c.paper, stroke: colour || c.rule, 'stroke-width': 1.25 }, g);
      text(g, title, { x: x + 14, y: y + 24, class: 't-value', 'font-size': 12.5, fill: colour || c.ink });
      if (sub) text(g, sub, { x: x + 14, y: y + 42, class: 't-axis', 'font-size': 10 });
      return g;
    };

    const arrow = (parent, x1, y1, x2, y2, colour) => {
      const p = el('path', {
        d: `M ${x1} ${y1} L ${x2} ${y2}`, fill: 'none',
        stroke: colour || c.rule, 'stroke-width': 1.25,
      }, parent);
      primeDraw(p);
      return p;
    };

    /* ---------- the tree -------------------------------------------- */
    const tree = group(s);
    const win = box(tree, 0, 20, 200, 58, 'Window · 2.0 s', '400 samples, 19 channels');
    const gate = box(tree, 0, 100, 200, 58, 'Activity gate', 'rest windows discarded');
    /* 240 wide, not 220: the sub-label is 218 units and was spilling
       12 units past its own border. */
    const router = box(tree, 250, 60, 240, 58, 'Stage 1 · router', 'hand-crafted features · 98–100%');

    const branchA = box(tree, 540, 8, 230, 62, 'Stage 2a · blinks', 'DTW-KNN on waveform shape', c.eog);
    const branchB = box(tree, 540, 108, 230, 62, 'Stage 2b · muscle', 'Riemannian covariance', c.emg);

    const outA = box(tree, 810, 8, 180, 62, 'O · S', 'single / double blink', c.eog);
    const outB = box(tree, 810, 108, 180, 62, 'C · L · R', 'clinch / left / right', c.emg);

    const a1 = arrow(tree, 100, 78, 100, 100);
    const a2 = arrow(tree, 200, 129, 250, 95);
    const a3 = arrow(tree, 490, 82, 540, 44, c.eog);
    const a4 = arrow(tree, 490, 96, 540, 139, c.emg);
    const a5 = arrow(tree, 770, 39, 810, 39, c.eog);
    const a6 = arrow(tree, 770, 139, 810, 139, c.emg);

    const lblA = text(tree, 'blink', { x: 500, y: 56, class: 't-axis', fill: c.eog, opacity: 0 });
    const lblB = text(tree, 'muscle', { x: 500, y: 128, class: 't-axis', fill: c.emg, opacity: 0 });

    /* ---------- the waterfall --------------------------------------- */
    const WY = 240;
    const BX = 300, BW = 520;
    const lo = 82, hi = 93;
    const sx = (v) => BX + ((v - lo) / (hi - lo)) * BW;

    const wfHead = group(s, { opacity: 0 });
    el('line', { x1: 0, y1: WY - 26, x2: W, y2: WY - 26, stroke: c.ink, 'stroke-width': 1 }, wfHead);
    text(wfHead, 'CUMULATIVE ACCURACY UNDER LEAVE-ONE-SESSION-OUT', { x: 0, y: WY - 6, class: 't-label', 'letter-spacing': '0.08em' });
    [85, 87, 89, 91, 93].forEach((v) => {
      el('line', { x1: sx(v), y1: WY + 10, x2: sx(v), y2: WY + 214, stroke: c.rule, 'stroke-width': 0.6, 'stroke-dasharray': '2 5' }, wfHead);
      text(wfHead, `${v}%`, { x: sx(v), y: WY + 232, 'text-anchor': 'middle', class: 't-axis' });
    });

    const steps = PROGRESSION.map((p, i) => {
      const y = WY + 30 + i * 48;
      const final = i === PROGRESSION.length - 1;
      const colour = final ? c.eog : c.faint;
      const g = group(s, { opacity: 0 });

      text(g, p.name, { x: 0, y: y + 4, class: 't-value', 'font-size': 12, fill: final ? c.eog : c.ink });
      text(g, p.note, { x: 0, y: y + 20, class: 't-axis', 'font-size': 9.5 });

      const rect = el('rect', { x: BX, y: y - 10, width: 0, height: 20, fill: colour, opacity: final ? 1 : 0.45 }, g);
      const val = text(g, `${p.accuracy}%`, { x: sx(p.accuracy) + 10, y: y + 5, class: 't-value', fill: final ? c.eog : c.ink, opacity: 0 });
      const f1 = text(g, `macro-F1 ${p.macroF1.toFixed(3)}`, { x: sx(p.accuracy) + 10, y: y + 20, class: 't-axis', 'font-size': 9.5, opacity: 0 });

      let delta = null;
      if (p.delta !== null && p.delta > 0) {
        delta = text(g, `+${p.delta}`, {
          x: sx(PROGRESSION[i - 1].accuracy) + (sx(p.accuracy) - sx(PROGRESSION[i - 1].accuracy)) / 2,
          y: y - 16, 'text-anchor': 'middle', class: 't-axis',
          fill: i === 2 ? c.emg : c.eog, opacity: 0, 'font-weight': 600,
        });
      }
      return { g, rect, val, f1, delta, target: sx(p.accuracy) - BX };
    });

    /* ---------- per-fold strip -------------------------------------- */
    const FY = WY + 268;
    const fold = group(s, { opacity: 0 });
    el('line', { x1: 0, y1: FY - 20, x2: W, y2: FY - 20, stroke: c.rule, 'stroke-width': 1 }, fold);
    text(fold, 'BETTER ON EVERY FOLD, NOT JUST ON AVERAGE', { x: 0, y: FY, class: 't-label', 'letter-spacing': '0.08em' });

    /* Columns start at 360, not 300: the heading to their left is 315
       units wide and was running into the first session label. */
    FOLDS.forEach((f, i) => {
      const x = 360 + i * 200;
      text(fold, f.session, { x, y: FY, class: 't-axis' });
      text(fold, `${f.hybrid}%`, { x, y: FY + 26, class: 't-big', fill: c.eog });
      text(fold, `flat ${f.flat}% · ${f.epochs} epochs`, { x, y: FY + 44, class: 't-axis', 'font-size': 9.5 });
    });
    text(fold, `Pooled over all ${HEADLINE.pooled.basis.match(/[\d,]+/)[0]} held-out predictions: ${HEADLINE.pooled.accuracy}%, macro-F1 ${HEADLINE.pooled.macroF1}.`, {
      x: 0, y: FY + 62, class: 't-axis', 'font-size': 9.5,
    });

    /* ---------- timeline -------------------------------------------- */
    const tl = gsap.timeline();
    tl.addLabel('router', 0)
      .to([win, gate], { opacity: 1, duration: 0.3, stagger: 0.12 })
      .to(a1, { strokeDashoffset: 0, duration: 0.3 }, '-=0.15')
      .to(router, { opacity: 1, duration: 0.3 }, '+=0.05')
      .to(a2, { strokeDashoffset: 0, duration: 0.3 }, '-=0.2')
      .addLabel('branches', '+=0.05')
      .to([lblA, lblB], { opacity: 1, duration: 0.25 }, 'branches')
      .to([a3, a4], { strokeDashoffset: 0, duration: 0.4, stagger: 0.08 }, '-=0.15')
      .to([branchA, branchB], { opacity: 1, duration: 0.35, stagger: 0.1 }, '-=0.2')
      .to([a5, a6], { strokeDashoffset: 0, duration: 0.3, stagger: 0.08 }, '+=0.05')
      .to([outA, outB], { opacity: 1, duration: 0.3, stagger: 0.1 }, '-=0.15')
      .addLabel('progression', '+=0.25')
      .to(wfHead, { opacity: 1, duration: 0.35 }, 'progression');

    steps.forEach((st) => {
      tl.to(st.g, { opacity: 1, duration: 0.25 }, '+=0.05');
      tl.to(st.rect, { attr: { width: st.target }, duration: 0.65, ease: 'power2.out' }, '-=0.12');
      tl.to([st.val, st.f1], { opacity: 1, duration: 0.25 }, '-=0.25');
      if (st.delta) tl.to(st.delta, { opacity: 1, duration: 0.3 }, '-=0.15');
    });
    tl.addLabel('folds', '+=0.15');
    tl.to(fold, { opacity: 1, duration: 0.4 }, 'folds');

    return {
      timeline: tl,
      stepAt: stepsFrom(tl, ['router', 'branches', 'progression', 'folds']),
    };
  },
};
