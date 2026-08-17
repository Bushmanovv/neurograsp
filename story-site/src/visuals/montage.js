import { gsap, stepsFrom } from '../lib/motion.js';
import { svg, el, group, text, token, primeDraw } from '../lib/svg.js';
import { MONTAGE, COMMANDS } from '../content/data.js';

/* Figure 1 — where the five commands physically live.
   Drawn from above, nose at the top, which is the conventional
   projection and the only one that shows left/right honestly. */

export default {
  id: 'montage',
  label: 'Fig. 1 — Command sites',
  provenance: 'Montage per 10–20 system · Ch. 3–4',
  caption:
    'The system reads four electrodes out of nineteen. Blinks appear as ocular potentials at the frontal poles; jaw gestures appear as muscle potentials at the temporal sites, where the electrodes sit directly over the temporalis muscles.',
  steps: ['Montage', 'Ocular', 'Muscular'],

  build(stage) {
    const s = svg('0 0 1000 500');
    stage.appendChild(s);

    const CX = 250, CY = 250, R = 195;
    const c = {
      rule: token('--rule'),
      ink: token('--ink'),
      faint: token('--ink-faint'),
      eog: token('--eog'),
      emg: token('--emg'),
      paper: token('--paper-raised'),
    };

    /* --- head outline ------------------------------------------------ */
    const head = group(s, { opacity: 0 });
    el('circle', { cx: CX, cy: CY, r: R, fill: 'none', stroke: c.rule, 'stroke-width': 1.5 }, head);
    // nose
    el('path', {
      d: `M ${CX - 22} ${CY - R + 5} L ${CX} ${CY - R - 26} L ${CX + 22} ${CY - R + 5}`,
      fill: 'none', stroke: c.rule, 'stroke-width': 1.5, 'stroke-linejoin': 'round',
    }, head);
    // ears
    el('path', { d: `M ${CX - R + 2} ${CY - 34} q -20 34 0 68`, fill: 'none', stroke: c.rule, 'stroke-width': 1.5 }, head);
    el('path', { d: `M ${CX + R - 2} ${CY - 34} q 20 34 0 68`, fill: 'none', stroke: c.rule, 'stroke-width': 1.5 }, head);
    // midlines
    el('line', { x1: CX, y1: CY - R, x2: CX, y2: CY + R, stroke: c.rule, 'stroke-width': 0.75, 'stroke-dasharray': '2 5' }, head);
    el('line', { x1: CX - R, y1: CY, x2: CX + R, y2: CY, stroke: c.rule, 'stroke-width': 0.75, 'stroke-dasharray': '2 5' }, head);
    text(head, 'ANTERIOR', { x: CX, y: CY - R - 38, 'text-anchor': 'middle', class: 't-axis' });
    text(head, 'L', { x: CX - R - 20, y: CY + 4, 'text-anchor': 'middle', class: 't-axis' });
    text(head, 'R', { x: CX + R + 20, y: CY + 4, 'text-anchor': 'middle', class: 't-axis' });

    /* --- electrodes -------------------------------------------------- */
    const nodes = {};
    const ctxG = group(s, { opacity: 0 });
    const liveG = group(s);

    MONTAGE.forEach((e) => {
      const x = CX + e.x * R * 0.9;
      const y = CY + e.y * R * 0.9;
      const active = e.role !== 'context';
      const parent = active ? liveG : ctxG;
      const colour = e.role === 'eog' ? c.eog : e.role === 'emg' ? c.emg : c.faint;
      const g = group(parent, { opacity: active ? 0 : 1 });

      if (active) {
        const halo = el('circle', { cx: x, cy: y, r: 11, fill: colour, opacity: 0.16 }, g);
        g.dataset.halo = '1';
        nodes[e.name] = { g, halo, x, y, colour };
      }
      el('circle', {
        cx: x, cy: y, r: active ? 7 : 4.5,
        fill: active ? colour : c.paper,
        stroke: active ? colour : c.rule, 'stroke-width': 1.25,
      }, g);
      text(g, e.name, {
        x, y: y - (active ? 16 : 11),
        'text-anchor': 'middle',
        class: active ? 't-label' : 't-axis',
        fill: active ? colour : undefined,
      });
    });

    /* --- command rows ------------------------------------------------ */
    const LX = 560;
    const rows = COMMANDS.map((cmd, i) => {
      const y = 110 + i * 62;
      const colour = cmd.family === 'eog' ? c.eog : c.emg;
      const g = group(s, { opacity: 0 });

      el('line', { x1: LX, y1: y + 20, x2: 968, y2: y + 20, stroke: c.rule, 'stroke-width': 1 }, g);

      // code chip
      el('rect', { x: LX, y: y - 12, width: 26, height: 26, rx: 3, fill: colour }, g);
      text(g, cmd.code, {
        x: LX + 13, y: y + 6, 'text-anchor': 'middle',
        fill: token('--paper-raised'), 'font-size': 13, 'font-weight': 600,
      });

      text(g, cmd.label, { x: LX + 40, y: y + 5, class: 't-value' });
      text(g, cmd.sites.join(' · '), { x: LX + 40, y: y - 10, class: 't-axis', fill: colour });
      text(g, cmd.action.toUpperCase(), { x: 968, y: y + 5, 'text-anchor': 'end', class: 't-axis' });

      // connector from the relevant electrode
      const src = nodes[cmd.sites[0]];
      const path = el('path', {
        d: `M ${src.x + 14} ${src.y} C ${src.x + 150} ${src.y}, ${LX - 90} ${y}, ${LX - 12} ${y}`,
        fill: 'none', stroke: colour, 'stroke-width': 1.25, opacity: 0.45,
      }, g);
      primeDraw(path);

      return { g, path, family: cmd.family };
    });

    text(s, 'FIVE VOLUNTARY GESTURES → FIVE DISCRETE COMMANDS', {
      x: LX, y: 66, class: 't-axis', 'letter-spacing': '0.12em',
    });

    /* --- timeline ---------------------------------------------------- */
    const tl = gsap.timeline();
    tl.addLabel('montage', 0)
      .to(head, { opacity: 1, duration: 0.5 })
      .to(ctxG, { opacity: 1, duration: 0.5 }, '-=0.25');

    [['eog', 'ocular'], ['emg', 'muscular']].forEach(([fam, mark]) => {
      const sites = fam === 'eog' ? ['Fp1', 'Fp2'] : ['T3', 'T4'];
      tl.addLabel(mark, '+=0.15');
      tl.to(sites.map((n) => nodes[n].g), { opacity: 1, duration: 0.4, stagger: 0.08 }, mark);
      tl.to(
        sites.map((n) => nodes[n].halo),
        { attr: { r: 17 }, opacity: 0.28, duration: 0.5, stagger: 0.08 },
        '<'
      );
      const famRows = rows.filter((r) => r.family === fam);
      tl.to(famRows.map((r) => r.g), { opacity: 1, duration: 0.4, stagger: 0.1 }, '-=0.3');
      tl.to(
        famRows.map((r) => r.path),
        { strokeDashoffset: 0, duration: 0.7, stagger: 0.1, ease: 'power2.out' },
        '<'
      );
    });

    return { timeline: tl, stepAt: stepsFrom(tl, ['montage', 'ocular', 'muscular']) };
  },
};
