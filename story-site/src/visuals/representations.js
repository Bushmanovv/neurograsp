import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token, smoothPath, noise, primeDraw } from '../lib/svg.js';
import { BLINK_ATTEMPTS, CONTAMINATION, PROGRESSION } from '../content/data.js';

/* Figure 5 — the two fixes, and why neither is a feature.
   Act A: amplitude drifts across sessions; covariance structure does not.
   Act B: counting fails on contaminated labels; shape does not.

   The manifold sketch in Act A is a schematic of the idea. The real
   tangent space is high-dimensional and cannot be drawn honestly. */

export default {
  id: 'representations',
  label: 'Fig. 5 — Two changes of representation',
  provenance: 'Tables 9.6–9.9 · manifold panel is a schematic of the method',
  schematic: true,
  caption:
    'Left panels state the failure, right panels the fix. Neither fix is an added feature: in both cases the quantity being compared was replaced. The gains shown are cumulative LOSO improvements from Table 9.11.',
  steps: ['Drift', 'Covariance', 'Counting', 'Shape'],

  build(stage) {
    const W = 1000, H = 720;
    const s = svg(`0 0 ${W} ${H}`);
    stage.appendChild(s);

    const c = {
      rule: token('--rule'), ink: token('--ink'), faint: token('--ink-faint'),
      eog: token('--eog'), emg: token('--emg'), oxide: token('--oxide'),
      paper: token('--paper-raised'),
    };
    const MID = 500;

    const heading = (parent, y, n, str, colour) => {
      el('line', { x1: 0, y1: y - 26, x2: W, y2: y - 26, stroke: c.ink, 'stroke-width': 1 }, parent);
      text(parent, n, { x: 0, y: y, class: 't-axis', fill: colour, 'letter-spacing': '0.14em' });
      text(parent, str, { x: 38, y: y, class: 't-label', 'letter-spacing': '0.06em' });
    };

    /* ============================ ACT A ============================ */
    const actA = group(s, { opacity: 0 });
    heading(actA, 34, 'A', 'THE MUSCLE CLASSES WERE DEFEATED BY DRIFT', c.emg);

    /* left: three sessions, same gesture, different amplitude */
    text(actA, 'SAME GESTURE, THREE RECORDING DAYS', { x: 0, y: 66, class: 't-axis' });
    const driftG = group(actA);
    const sessions = [
      { name: 'Session 1', amp: 0.92 },
      { name: 'Session 2', amp: 0.54 },
      { name: 'Session 3', amp: 1.0 },
    ];
    const driftBars = sessions.map((ses, i) => {
      const y = 100 + i * 52;
      const g = group(driftG);
      text(g, ses.name, { x: 0, y: y + 14, class: 't-axis' });
      el('line', { x1: 96, y1: y + 9, x2: 400, y2: y + 9, stroke: c.rule, 'stroke-width': 0.6, 'stroke-dasharray': '2 4' }, g);
      const rand = noise(97 * (i + 3));
      const pts = [];
      for (let k = 0; k < 120; k++) {
        const t = k / 119;
        const env = t > 0.2 && t < 0.8 ? Math.sin(((t - 0.2) / 0.6) * Math.PI) : 0;
        pts.push([96 + t * 304, y + 9 - rand() * env * 20 * ses.amp]);
      }
      const p = el('path', { d: smoothPath(pts, 0.15), fill: 'none', stroke: c.emg, 'stroke-width': 1.3 }, g);
      primeDraw(p);
      return p;
    });

    const tkeo = group(actA, { opacity: 0 });
    text(tkeo, 'TKEO — a squared-amplitude measure', { x: 0, y: 274, class: 't-axis' });
    text(tkeo, '−5.7', { x: 330, y: 276, class: 't-value', fill: c.oxide, 'text-anchor': 'end' });
    el('line', { x1: 0, y1: 270, x2: 340, y2: 270, stroke: c.oxide, 'stroke-width': 1.5 }, tkeo);

    /* right: the tangent space sketch */
    const manifold = group(actA, { opacity: 0, transform: `translate(${MID + 40}, 0)` });
    text(manifold, 'COMPARE STRUCTURE, NOT SIZE', { x: 0, y: 66, class: 't-axis' });
    text(manifold, 'Inter-channel covariance in a Riemannian tangent space', { x: 0, y: 84, class: 't-axis', 'font-size': 10 });

    const arc = el('path', {
      d: 'M 10 240 C 90 250, 200 210, 300 130',
      fill: 'none', stroke: c.rule, 'stroke-width': 2,
    }, manifold);
    text(manifold, 'manifold of covariance matrices', { x: 12, y: 262, class: 't-axis', 'font-size': 9.5 });

    // tangent line touching near the middle
    const tan = el('line', { x1: 60, y1: 258, x2: 300, y2: 168, stroke: c.emg, 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }, manifold);
    text(manifold, 'tangent space — flat, linearly separable', {
      x: 300, y: 160, class: 't-axis', 'text-anchor': 'end', fill: c.emg, 'font-size': 9.5,
    });

    const dots = [
      { x: 118, y: 236, tx: 122, ty: 235 },
      { x: 176, y: 219, tx: 186, ty: 212 },
      { x: 236, y: 178, tx: 248, ty: 187 },
    ].map((d) => {
      const g = group(manifold, { opacity: 0 });
      el('circle', { cx: d.x, cy: d.y, r: 4.5, fill: c.emg }, g);
      el('line', { x1: d.x, y1: d.y, x2: d.tx, y2: d.ty, stroke: c.emg, 'stroke-width': 1, opacity: 0.5 }, g);
      el('circle', { cx: d.tx, cy: d.ty, r: 3, fill: 'none', stroke: c.emg, 'stroke-width': 1.25 }, g);
      return g;
    });

    const gainA = group(actA, { opacity: 0, transform: `translate(${MID + 40}, 0)` });
    text(gainA, '+4.1', { x: 0, y: 300, class: 't-big', fill: c.emg });
    text(gainA, 'points. All three muscle F1 scores now above 0.95.', { x: 62, y: 300, class: 't-axis' });

    /* ============================ ACT B ============================ */
    const actB = group(s, { opacity: 0, transform: 'translate(0, 366)' });
    heading(actB, 34, 'B', 'THE BLINK CLASSES WERE DEFEATED BY THEIR LABELS', c.eog);

    /* left: five attempts */
    const attempts = BLINK_ATTEMPTS.map((a, i) => {
      const y = 76 + i * 40;
      const g = group(actB, { opacity: 0 });
      const failed = a.outcome === 'failed';
      const colour = failed ? c.oxide : c.eog;
      text(g, String(a.n), { x: 0, y: y + 4, class: 't-axis', fill: colour });
      text(g, a.method, { x: 22, y: y + 4, class: 't-value', fill: failed ? c.faint : c.eog, 'font-size': 12 });
      text(g, a.why, { x: 22, y: y + 19, class: 't-axis', 'font-size': 9.5 });
      const strike = el('line', {
        x1: 20, y1: y, x2: 20, y2: y, stroke: c.oxide, 'stroke-width': 1.25, opacity: failed ? 1 : 0,
      }, g);
      return { g, strike, failed, y, width: Math.min(420, a.method.length * 8 + 20) };
    });

    const contam = group(actB, { opacity: 0 });
    el('line', { x1: 0, y1: 286, x2: 440, y2: 286, stroke: c.oxide, 'stroke-width': 1 }, contam);
    text(contam, 'WHAT ATTEMPT 4 ACTUALLY FOUND', { x: 0, y: 306, class: 't-label', fill: c.oxide, 'letter-spacing': '0.08em' });
    CONTAMINATION.forEach((row, i) => {
      const y = 328 + i * 34;
      text(contam, row.key, { x: 0, y, class: 't-axis' });
      text(contam, `expected ${row.expected} · detected ${row.detected.toFixed(2)} · ${row.clean}% clean`, {
        x: 0, y: y + 14, class: 't-axis', 'font-size': 9.5, fill: i === 0 ? c.oxide : c.faint,
      });
    });

    /* right: DTW alignment */
    const dtw = group(actB, { opacity: 0, transform: `translate(${MID + 40}, 0)` });
    text(dtw, 'COMPARE SHAPE, NOT COUNT', { x: 0, y: 66, class: 't-axis' });
    text(dtw, 'Elastic alignment inside a Sakoe–Chiba band', { x: 0, y: 84, class: 't-axis', 'font-size': 10 });

    const TW = 380;
    const mkBlink = (yBase, peaks, seed) => {
      const rand = noise(seed);
      const pts = [];
      for (let k = 0; k < 160; k++) {
        const t = k / 159;
        let v = rand() * 0.05;
        for (const p of peaks) {
          const d = t - p.at;
          v += p.amp * (Math.exp(-Math.pow(d / 0.03, 2)) * 0.8 + (d > 0 ? Math.exp(-d / 0.07) * Math.exp(-Math.pow(d / 0.16, 2)) * 0.4 : 0));
        }
        pts.push([t * TW, yBase - v * 30]);
      }
      return pts;
    };

    // a contaminated "single blink" (three bumps) and a clean single exemplar
    const qPts = mkBlink(160, [{ at: 0.3, amp: 0.9 }, { at: 0.45, amp: 0.55 }, { at: 0.6, amp: 0.4 }], 613);
    const rPts = mkBlink(268, [{ at: 0.42, amp: 1.0 }], 811);

    text(dtw, 'query — a contaminated single blink', { x: 0, y: 112, class: 't-axis', 'font-size': 9.5, fill: c.oxide });
    text(dtw, 'exemplar — a clean single blink', { x: 0, y: 292, class: 't-axis', 'font-size': 9.5, fill: c.eog });

    const qPath = el('path', { d: smoothPath(qPts, 0.18), fill: 'none', stroke: c.oxide, 'stroke-width': 1.5 }, dtw);
    const rPath = el('path', { d: smoothPath(rPts, 0.18), fill: 'none', stroke: c.eog, 'stroke-width': 1.5 }, dtw);
    [qPath, rPath].forEach(primeDraw);

    const warpG = group(dtw);
    const warps = [];
    for (let i = 0; i <= 14; i++) {
      const t = i / 14;
      const qi = Math.min(159, Math.round(t * 159));
      // deliberately non-linear correspondence — that is the point of DTW
      const rt = Math.min(1, Math.max(0, 0.5 + (t - 0.45) * 0.75));
      const ri = Math.min(159, Math.round(rt * 159));
      const line = el('line', {
        x1: qPts[qi][0], y1: qPts[qi][1] + 4,
        x2: rPts[ri][0], y2: rPts[ri][1] - 4,
        stroke: c.faint, 'stroke-width': 0.75, opacity: 0,
      }, warpG);
      warps.push(line);
    }

    const gainB = group(actB, { opacity: 0, transform: `translate(${MID + 40}, 0)` });
    text(gainB, '+2.1', { x: 0, y: 332, class: 't-big', fill: c.eog });
    text(gainB, 'points. Averaged templates failed at 50.5% —', { x: 62, y: 326, class: 't-axis' });
    text(gainB, 'a contaminated class has no meaningful average shape.', { x: 62, y: 342, class: 't-axis' });

    /* ---------- timeline -------------------------------------------- */
    const tl = gsap.timeline();
    tl.addLabel('drift', 0)
      .to(actA, { opacity: 1, duration: 0.35 })
      .to(driftBars, { strokeDashoffset: 0, duration: 0.8, stagger: 0.15, ease: 'none' }, '-=0.1')
      .to(tkeo, { opacity: 1, duration: 0.35 }, '+=0.1')
      .addLabel('covariance', '+=0.15')
      .to(manifold, { opacity: 1, duration: 0.4 }, 'covariance')
      .to(dots, { opacity: 1, duration: 0.35, stagger: 0.12 }, '-=0.1')
      .to(gainA, { opacity: 1, duration: 0.35 }, '-=0.1')
      .addLabel('counting', '+=0.3')
      .to(actB, { opacity: 1, duration: 0.35 }, 'counting');

    attempts.forEach((a) => {
      tl.to(a.g, { opacity: 1, duration: 0.22 }, '+=0.04');
      if (a.failed) tl.to(a.strike, { attr: { x2: a.width }, duration: 0.35, ease: 'power2.out' }, '-=0.06');
    });
    tl.to(contam, { opacity: 1, duration: 0.4 }, '+=0.1')
      .addLabel('shape', '+=0.1')
      .to(dtw, { opacity: 1, duration: 0.35 }, 'shape')
      .to([qPath, rPath], { strokeDashoffset: 0, duration: 0.9, stagger: 0.15, ease: 'none' }, '-=0.15')
      .to(warps, { opacity: 0.85, duration: 0.5, stagger: 0.035 }, '-=0.35')
      .to(gainB, { opacity: 1, duration: 0.35 }, '-=0.1');

    return {
      timeline: tl,
      stepAt: stepsFrom(tl, ['drift', 'covariance', 'counting', 'shape']),
    };
  },
};
