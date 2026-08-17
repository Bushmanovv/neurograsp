import gsap from 'gsap';
import ScrollTrigger from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

/* ------------------------------------------------------------------
   Policy, decided once and read everywhere.

   reduced  — the visitor asked for no motion. Timelines are built
              and then jumped to their end state. Nothing scrubs.
   compact  — narrow viewport or coarse pointer. We do not pin or
              scrub on phones: scrubbed pinning is where scroll
              animation gets janky on mobile, so figures instead
              play through once on entry, which is cheap and smooth.
   ------------------------------------------------------------------ */

export const reduced =
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export const compact =
  window.matchMedia('(max-width: 860px)').matches ||
  window.matchMedia('(pointer: coarse)').matches;

export { gsap, ScrollTrigger };

/* How long a figure should take to play itself through when it is not
   being scrubbed. Timelines are authored at whatever length reads well
   under scrub — from under 3s to nearly 9s — and that spread does not
   matter when scroll position is driving them. It matters a great deal
   on a phone, where a 9s play-through finishes long after the reader
   has scrolled away. Longer timelines are time-scaled down to this;
   shorter ones are left alone rather than padded out. */
const PLAY_SECONDS = 2.8;

/* Where a scrubbed figure starts and finishes, in ScrollTrigger terms.

   Measured against the drawing, not the whole figure block — see the
   trigger passed by main.js. The block opens with a label row and a
   caption, 158–203px of text, so triggering on it started the timeline
   while the drawing was still below the fold and let the length of a
   caption silently decide how much played unseen.

   The two percentages are equal, and that is the whole trick. Given
   `start: top A` and `end: bottom B`, an element drawn partway down the
   figure animates at screen fraction A + f(B − A) — the reveal point
   slides from A to B as the figure plays. Any A ≠ B therefore drags the
   moment of appearance across the screen: at 85% → 55% content was
   surfacing at the very bottom edge, sometimes below the fold, and had
   already scrolled past the middle by the time it could be read.

   Holding A = B pins the reveal to one fixed line instead. Every
   element in every figure now appears at the same height, a little
   below centre, and rises through the reading zone afterwards — the
   figure develops through a stationary horizontal seam. It also makes
   the scrub range exactly the drawing's own height, so a figure scrolls
   past at the same rate it draws itself.

   55 rather than a round 50 because the figures do not draw in strict
   top-to-bottom order, which biases where content actually surfaces.
   Measuring the real appearance height of every element across all
   eight figures put the best value at 54–55; at 50 the later phases
   start landing above centre instead. */
const REVEAL_LINE = 55;
const SCRUB_START = `top ${REVEAL_LINE}%`;
const SCRUB_END = `bottom ${REVEAL_LINE}%`;

/**
 * Attach a timeline to an element's scroll range. Pass the drawing
 * itself as `element`, not its surrounding chrome.
 *
 * mode 'scrub'  — timeline position follows scroll position (desktop).
 * mode 'play'   — timeline plays once when the element enters.
 *
 * Under reduced motion the timeline is completed immediately and no
 * ScrollTrigger is created at all.
 */
export function bind(element, timeline, { mode = 'scrub', onUpdate } = {}) {
  if (!timeline) return null;

  if (reduced) {
    timeline.progress(1).pause();
    if (onUpdate) onUpdate(1);
    return null;
  }

  const useScrub = mode === 'scrub' && !compact;

  if (useScrub) {
    /* A figure never un-draws.
       Handing the timeline straight to `animation:` ties it to scroll in
       both directions, so scrolling back up rewinds a finished diagram to
       a blank stage — the reader loses the thing they scrolled back to
       look at. So the scrub drives a proxy instead, and only forward
       motion is passed through to the timeline. Scroll down and the
       figure draws; scroll back up and it stays exactly as drawn.

       ScrollTrigger still owns the proxy, so its 0.6s smoothing is
       intact — this changes which way the drawing can move, not how it
       feels while it moves. */
    timeline.pause();

    const scrubbed = { p: 0 };
    const advance = () => {
      if (scrubbed.p <= timeline.progress()) return;
      timeline.progress(scrubbed.p);
      if (onUpdate) onUpdate(scrubbed.p);
    };

    return ScrollTrigger.create({
      trigger: element,
      start: SCRUB_START,
      end: SCRUB_END,
      scrub: 0.6,
      animation: gsap.to(scrubbed, { p: 1, ease: 'none', onUpdate: advance }),
    });
  }

  timeline.pause();
  timeline.timeScale(Math.max(1, timeline.duration() / PLAY_SECONDS));

  /* Registered before play(), or the first frames of the run go by
     without the step markers hearing about them. */
  if (onUpdate) {
    timeline.eventCallback('onUpdate', () => onUpdate(timeline.progress()));
  }

  return ScrollTrigger.create({
    trigger: element,
    start: 'top 88%',
    once: true,
    onEnter: () => timeline.play(),
  });
}

/**
 * Build a figure's `stepAt(progress)` from the timeline's own labels.
 *
 * The step markers under a figure are a caption for what is currently
 * being drawn above them, so they have to agree with it. Hand-written
 * progress thresholds cannot: they are fractions of a total duration
 * that changes whenever any tween in the figure is retimed, so they
 * drift silently. Reading the label positions back off the finished
 * timeline means the markers are correct by construction.
 *
 * Call after the timeline is fully built — the duration has to be final.
 */
export function stepsFrom(timeline, names) {
  const duration = timeline.duration() || 1;

  const at = names.map((name) => {
    const t = timeline.labels[name];
    if (t === undefined) {
      console.warn(`[motion] timeline has no label "${name}" — that step marker will not track`);
      return 0;
    }
    return t / duration;
  });

  return (p) => {
    let i = 0;
    for (let k = 1; k < at.length; k += 1) if (p >= at[k]) i = k;
    return i;
  };
}

/** Simple fade-up reveal for prose blocks. */
export function revealOnEnter(nodes) {
  nodes.forEach((node) => {
    if (reduced) {
      node.classList.add('is-in');
      return;
    }
    ScrollTrigger.create({
      trigger: node,
      start: 'top 88%',
      once: true,
      onEnter: () => node.classList.add('is-in'),
    });
  });
}

export function refresh() {
  ScrollTrigger.refresh();
}
