import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token, smoothPath, noise, primeDraw, wrap } from '../lib/svg.js';
import { SIGNATURES, COMMANDS, ASYMMETRY } from '../content/data.js';

/* Figure 2 — what each gesture looks like at its own electrodes,
   resolving into the asymmetry index that separates the jaw classes.

   The traces are SCHEMATIC. They are generated to the morphology the
   report describes (peak counts, inter-blink interval, bilateral vs
   lateralised jaw activation) and are not recorded data. If real epoch
   arrays become available, feed them in as `trace.sample` — an array of
   400 numbers normalised to roughly [-1, 1] — and buildTrace uses them
   instead of synthesising. */

const W = 1000;
const ROW_H = 122;
const TRACE_W = 470;
const TRACE_X = 300;

function buildTrace(trace, height) {
  const pts = [];
  const N = 200;
  const mid = height / 2;
  const rand = noise(trace.site.charCodeAt(1) * 977 + (trace.kind === 'burst' ? 31 : 7));

  if (trace.sample && trace.sample.length) {
    const step = trace.sample.length / N;
    for (let i = 0; i < N; i++) {
      const v = trace.sample[Math.floor(i * step)];
      pts.push([(i / (N - 1)) * TRACE_W, mid - v * mid * 0.85]);
    }
    return smoothPath(pts, 0.2);
  }

  for (let i = 0; i < N; i++) {
    const t = i / (N - 1);
    let v = rand() * 0.045; // baseline EEG

    if (trace.kind === 'blink') {
      for (const p of trace.peaks) {
        // fast rise, slower decay — the shape the report describes
        const d = t - p.at;
        const rise = Math.exp(-Math.pow(d / 0.022, 2));
        const decay = d > 0 ? Math.exp(-d / 0.055) * Math.exp(-Math.pow(d / 0.13, 2)) : 0;
        v += p.amp * (rise * 0.75 + decay * 0.45);
      }
    } else if (trace.kind === 'burst') {
      if (t > trace.start && t < trace.end) {
        const inside = (t - trace.start) / (trace.end - trace.start);
        const env = Math.min(1, Math.sin(inside * Math.PI) * 1.6);
        v += rand() * trace.amp * env * 0.95;
      }
    }
    pts.push([t * TRACE_W, mid - v * mid * 0.82]);
  }
  return smoothPath(pts, 0.18);
}

export default {
  id: 'signatures',
  label: 'Fig. 2 — Gesture signatures',
  provenance: 'Schematic — drawn to described morphology, not recorded data',
  schematic: true,
  caption:
    'Shapes follow the descriptions in Ch. 3 and Ch. 6: one deflection for a single blink, two separated by 200–400 ms for a double, a sustained broadband burst for the jaw. Amplitudes are normalised per panel — the point is the shape and the left/right balance, not the scale.',
  steps: ['Blinks', 'Jaw', 'Asymmetry'],

  build(stage) {
    const H = SIGNATURES.length * ROW_H + 190;
    const s = svg(`0 0 ${W} ${H}`);
    stage.appendChild(s);

    const c = {
      rule: token('--rule'),
      faint: token('--ink-faint'),
      eog: token('--eog'),
      emg: token('--emg'),
      ink: token('--ink'),
    };
    const byKey = Object.fromEntries(COMMANDS.map((x) => [x.key, x]));

    const panels = SIGNATURES.map((sig, i) => {
      const cmd = byKey[sig.key];
      const colour = cmd.family === 'eog' ? c.eog : c.emg;
      const top = i * ROW_H + 20;
      const g = group(s, { opacity: 0 });

      el('line', { x1: 0, y1: top, x2: W, y2: top, stroke: c.rule, 'stroke-width': 1 }, g);

      text(g, cmd.label, { x: 0, y: top + 30, class: 't-value' });
      text(g, cmd.code, { x: 0, y: top + 52, class: 't-axis', fill: colour, 'letter-spacing': '0.14em' });
      text(g, sig.reading, { x: 0, y: top + 74, class: 't-axis', fill: c.faint });

      /* The left column runs out at the site label, which sits at
         TRACE_X - 14 anchored end — so about 264 units, or 37 mono
         characters. The longest scale notes overrun that and land on
         top of the "Fp2"/"T4" label, so they wrap instead. */
      wrap(sig.scaleNote, 37).forEach((line, k) => {
        text(g, line, { x: 0, y: top + 92 + k * 13, class: 't-axis', fill: c.faint, opacity: 0.75 });
      });

      const paths = sig.traces.map((tr, j) => {
        const tg = group(g, { transform: `translate(${TRACE_X}, ${top + 16 + j * 46})` });
        el('line', { x1: 0, y1: 21, x2: TRACE_W, y2: 21, stroke: c.rule, 'stroke-width': 0.75, 'stroke-dasharray': '2 4' }, tg);
        text(tg, tr.site, { x: -14, y: 25, 'text-anchor': 'end', class: 't-axis', fill: colour });
        const p = el('path', {
          d: buildTrace(tr, 42),
          fill: 'none', stroke: colour, 'stroke-width': 1.5,
          'stroke-linecap': 'round', 'stroke-linejoin': 'round',
        }, tg);
        primeDraw(p);
        return p;
      });

      text(g, cmd.action.toUpperCase(), {
        x: W, y: top + 40, 'text-anchor': 'end', class: 't-axis',
      });

      return { g, paths, family: cmd.family };
    });

    /* --- asymmetry index band --------------------------------------- */
    const AY = SIGNATURES.length * ROW_H + 100;
    const axis = group(s, { opacity: 0 });
    const AX0 = 300, AX1 = 770, AMID = (AX0 + AX1) / 2;

    el('line', { x1: 0, y1: AY - 46, x2: W, y2: AY - 46, stroke: c.ink, 'stroke-width': 1 }, axis);
    text(axis, 'T3–T4 ASYMMETRY INDEX', { x: 0, y: AY - 22, class: 't-label', 'letter-spacing': '0.1em' });
    text(axis, ASYMMETRY.formula, { x: 0, y: AY + 2, class: 't-axis' });
    text(axis, `bruxism_left F1 ${ASYMMETRY.gain.from} → ${ASYMMETRY.gain.to}`, {
      x: 0, y: AY + 24, class: 't-axis', fill: c.emg,
    });

    el('line', { x1: AX0, y1: AY, x2: AX1, y2: AY, stroke: c.rule, 'stroke-width': 1.5 }, axis);
    [['−1', AX0], ['0', AMID], ['+1', AX1]].forEach(([lab, x]) => {
      el('line', { x1: x, y1: AY - 6, x2: x, y2: AY + 6, stroke: c.rule, 'stroke-width': 1.5 }, axis);
      text(axis, lab, { x, y: AY + 24, 'text-anchor': 'middle', class: 't-axis' });
    });

    const marks = ASYMMETRY.bands.map((b) => {
      const cmd = byKey[b.key];
      const x = AMID + b.position * ((AX1 - AX0) / 2);
      const g = group(axis, { opacity: 0 });
      el('circle', { cx: x, cy: AY, r: 7, fill: c.emg }, g);
      text(g, cmd.label, { x, y: AY - 20, 'text-anchor': 'middle', class: 't-label', fill: c.emg });
      text(g, b.reading, { x, y: AY - 36, 'text-anchor': 'middle', class: 't-axis' });
      return g;
    });

    /* --- timeline ----------------------------------------------------
       Marked off the panels themselves rather than by index, so
       reordering SIGNATURES moves the 'jaw' mark with the first muscle
       panel instead of stranding it. */
    const tl = gsap.timeline();
    let markedJaw = false;
    panels.forEach((p, i) => {
      let pos = '+=0.05';
      if (i === 0) {
        tl.addLabel('blinks', 0);
        pos = 'blinks';
      } else if (p.family === 'emg' && !markedJaw) {
        markedJaw = true;
        tl.addLabel('jaw', '+=0.05');
        pos = 'jaw';
      }
      tl.to(p.g, { opacity: 1, duration: 0.3 }, pos);
      tl.to(p.paths, { strokeDashoffset: 0, duration: 1.0, stagger: 0.12, ease: 'none' }, '-=0.15');
    });
    tl.addLabel('asymmetry', '+=0.1');
    tl.to(axis, { opacity: 1, duration: 0.4 }, 'asymmetry');
    tl.to(marks, { opacity: 1, duration: 0.35, stagger: 0.12 }, '-=0.1');

    return { timeline: tl, stepAt: stepsFrom(tl, ['blinks', 'jaw', 'asymmetry']) };
  },
};
