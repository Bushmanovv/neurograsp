import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token } from '../lib/svg.js';
import { PROTOCOLS, SHUFFLE_TEST, RIG } from '../content/data.js';

/* Figure 4 — why the first number had to be thrown away.
   Top: two adjacent epochs and the 300 samples they share.
   Bottom: the same data scored under three protocols. */

export default {
  id: 'leakage',
  label: 'Fig. 4 — The evaluation audit',
  provenance: 'Tables 9.1–9.3 · four-test leakage audit',
  caption:
    'Two-second epochs stepped every half second overlap by 75%. Split randomly, a test epoch shares 300 of its 400 samples with a training epoch. The audit found no implementation or preprocessing leak — the shuffle test lands at chance — but the random protocol leaks through overlap alone.',
  steps: ['Overlap', 'Shared', 'Protocols'],

  build(stage) {
    const W = 1000, H = 600;
    const s = svg(`0 0 ${W} ${H}`);
    stage.appendChild(s);

    const c = {
      rule: token('--rule'),
      ink: token('--ink'),
      faint: token('--ink-faint'),
      eog: token('--eog'),
      emg: token('--emg'),
      oxide: token('--oxide'),
      paper: token('--paper-raised'),
    };

    /* hatch pattern for the shared region */
    const defs = el('defs', {}, s);
    const pat = el('pattern', {
      id: 'sharedHatch', width: 7, height: 7,
      patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)',
    }, defs);
    el('line', { x1: 0, y1: 0, x2: 0, y2: 7, stroke: c.oxide, 'stroke-width': 2.5 }, pat);

    /* ---------- top: the recording strip ---------------------------- */
    const SX = 40, SW = 800, SY = 78, SH = 46;
    const strip = group(s, { opacity: 0 });

    text(strip, 'ONE RECORDING, SAMPLE INDEX →', { x: SX, y: SY - 34, class: 't-axis', 'letter-spacing': '0.12em' });
    el('rect', { x: SX, y: SY, width: SW, height: SH, fill: c.paper, stroke: c.rule }, strip);
    for (let i = 1; i < 10; i++) {
      el('line', { x1: SX + (SW / 10) * i, y1: SY, x2: SX + (SW / 10) * i, y2: SY + SH, stroke: c.rule, 'stroke-width': 0.6 }, strip);
    }

    // two epochs: width = 400 samples, offset = 100 samples
    const unit = SW / 1000;           // strip represents 1000 samples
    const epW = RIG.epochSamples * unit;
    const off = RIG.offlineStepSamples * unit;
    const e1x = SX + 120 * unit;
    const e2x = e1x + off;

    /* Shared region callout. Drawn before the epochs, not after: the
       hatch spans the whole overlap, and the second epoch's label sits
       inside that span — painted afterwards, the hatch ruled straight
       through the lettering and made it unreadable. Behind the epoch
       boxes it still reads clearly, because their fills are only 14%. */
    const shared = group(s, { opacity: 0 });
    const shX = e2x, shW = e1x + epW - e2x;
    el('rect', {
      x: shX, y: SY - 4, width: shW, height: SH * 2 + 16,
      fill: 'url(#sharedHatch)', opacity: 0.3,
    }, shared);
    el('rect', {
      x: shX, y: SY - 4, width: shW, height: SH * 2 + 16,
      fill: 'none', stroke: c.oxide, 'stroke-width': 1.5,
    }, shared);
    text(shared, '300 SAMPLES IN COMMON — 75% OVERLAP', {
      x: shX + shW / 2, y: SY + SH * 2 + 34, 'text-anchor': 'middle',
      class: 't-label', fill: c.oxide, 'letter-spacing': '0.08em',
    });
    text(shared, 'Split these at random and the test set is nearly the training set.', {
      x: shX + shW / 2, y: SY + SH * 2 + 54, 'text-anchor': 'middle', class: 't-axis',
    });

    const mkEpoch = (x, y, colour, label) => {
      const g = group(s, { opacity: 0 });
      el('rect', { x, y, width: epW, height: SH, fill: colour, opacity: 0.14 }, g);
      el('rect', { x, y, width: epW, height: SH, fill: 'none', stroke: colour, 'stroke-width': 1.5 }, g);
      /* The lower label lands inside the hatched overlap, where diagonal
         rules run straight through the lettering. A plate under it is
         what makes it readable; z-order alone is not enough. 7.04 units
         per character is the measured advance of the mono axis face. */
      el('rect', {
        x: x + 4, y: y - 20, width: label.length * 7.04 + 8, height: 17,
        fill: c.paper,
      }, g);
      text(g, label, { x: x + 8, y: y - 8, class: 't-axis', fill: colour, 'letter-spacing': '0.1em' });
      return g;
    };
    const ep1 = mkEpoch(e1x, SY - 4, c.eog, 'EPOCH k · 400 SAMPLES');
    const ep2 = mkEpoch(e2x, SY + SH + 12, c.eog, 'EPOCH k+1 · STEPPED 100 SAMPLES');

    /* ---------- bottom: protocols ----------------------------------- */
    const PY = 290;
    const BX = 300, BW = 560;
    const scaleX = (v) => BX + (v / 100) * BW;

    const protoHead = group(s, { opacity: 0 });
    el('line', { x1: 0, y1: PY - 34, x2: W, y2: PY - 34, stroke: c.ink, 'stroke-width': 1 }, protoHead);
    text(protoHead, 'THE SAME MODEL, SCORED THREE WAYS', { x: 0, y: PY - 12, class: 't-label', 'letter-spacing': '0.1em' });

    const bars = PROTOCOLS.map((p, i) => {
      const y = PY + 24 + i * 62;
      const colour = p.status === 'leaks' ? c.oxide : p.status === 'headline' ? c.eog : c.faint;
      const g = group(s, { opacity: 0 });

      text(g, p.name, { x: 0, y: y + 4, class: 't-value', fill: p.status === 'leaks' ? c.oxide : c.ink });
      text(g, p.note, { x: 0, y: y + 22, class: 't-axis', 'font-size': 9.5 });

      el('line', { x1: BX, y1: y + 10, x2: BX + BW, y2: y + 10, stroke: c.rule, 'stroke-width': 0.75 }, g);
      const rect = el('rect', {
        x: BX, y: y - 8, width: 0, height: 18, fill: colour, opacity: p.status === 'leaks' ? 0.5 : 1,
      }, g);
      if (p.status === 'leaks') {
        el('line', {
          x1: BX, y1: y + 1, x2: scaleX(p.value), y2: y + 1,
          stroke: c.oxide, 'stroke-width': 2, class: 'strike', opacity: 0,
        }, g);
      }
      const val = text(g, p.display, {
        x: scaleX(p.value) + 12, y: y + 6, class: 't-value',
        fill: colour, opacity: 0,
      });
      if (p.status === 'headline') {
        text(g, 'CITE THIS', { x: scaleX(p.value) + 12, y: y + 22, class: 't-axis', fill: c.eog, 'letter-spacing': '0.1em' });
      }
      if (p.status === 'leaks') {
        text(g, 'DO NOT CITE', { x: scaleX(p.value) + 12, y: y + 22, class: 't-axis', fill: c.oxide, 'letter-spacing': '0.1em' });
      }
      return { g, rect, val, target: scaleX(p.value) - BX, strike: g.querySelector('.strike') };
    });

    /* shuffle test footer */
    const SFY = PY + 24 + PROTOCOLS.length * 62 + 26;
    const shuffle = group(s, { opacity: 0 });
    el('line', { x1: 0, y1: SFY - 18, x2: W, y2: SFY - 18, stroke: c.rule, 'stroke-width': 1 }, shuffle);
    /* The heading runs to 373 units, past the BX column the numbers sit
       in, so the result goes on its own line underneath rather than
       through the middle of the caption. */
    text(shuffle, 'INTEGRITY CHECK · LABELS PERMUTED, PIPELINE UNCHANGED', {
      x: 0, y: SFY + 4, class: 't-axis', 'letter-spacing': '0.1em',
    });
    text(shuffle, `${SHUFFLE_TEST.observed}%`, { x: BX, y: SFY + 40, class: 't-big' });
    text(shuffle, `chance for ${SHUFFLE_TEST.classes} classes is ${SHUFFLE_TEST.chance}% — the pipeline manufactures no signal`, {
      x: BX + 52, y: SFY + 36, class: 't-axis',
    });

    /* ---------- timeline -------------------------------------------- */
    const tl = gsap.timeline();
    tl.addLabel('overlap', 0)
      .to(strip, { opacity: 1, duration: 0.4 })
      .to(ep1, { opacity: 1, duration: 0.4 }, '+=0.1')
      .to(ep2, { opacity: 1, duration: 0.4 }, '+=0.1')
      .addLabel('shared', '+=0.15')
      .to(shared, { opacity: 1, duration: 0.5 }, 'shared')
      .addLabel('protocols', '+=0.25')
      .to(protoHead, { opacity: 1, duration: 0.35 }, 'protocols');

    bars.forEach((b) => {
      tl.to(b.g, { opacity: 1, duration: 0.3 }, '+=0.05');
      tl.to(b.rect, { attr: { width: b.target }, duration: 0.7, ease: 'power2.out' }, '-=0.15');
      tl.to(b.val, { opacity: 1, duration: 0.3 }, '-=0.2');
      if (b.strike) tl.to(b.strike, { opacity: 1, duration: 0.3 }, '-=0.05');
    });
    tl.to(shuffle, { opacity: 1, duration: 0.4 }, '+=0.1');

    return { timeline: tl, stepAt: stepsFrom(tl, ['overlap', 'shared', 'protocols']) };
  },
};
