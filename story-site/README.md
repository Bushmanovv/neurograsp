# The signal everyone throws away

A scrollytelling page built from `ENCS5300-Section21-Report.pdf`.

Vite + vanilla JS + GSAP/ScrollTrigger. All diagrams are SVG drawn as code
from the report's own tables. No three.js — see "Why no 3D" below. No CDNs:
GSAP and both typefaces are npm packages, bundled at build time.

## Run

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # → dist/
npm run preview  # serve the build
```

## The four files you'll actually touch

| File | What's in it |
|---|---|
| `src/content/story.js` | **All prose**, in reading order. Headings, paragraphs, the two pull-quotes, the limitations list. |
| `src/content/data.js` | **Every number** the diagrams draw, each block tagged with the report table it came from. |
| `src/styles/tokens.css` | **All colour and type.** Changing a hex here also restyles every SVG, because the visual modules read the tokens at build time. |
| `src/visuals/*.js` | One file per figure. Self-contained: builds its own SVG and returns a GSAP timeline. |

### Changing wording
Edit `story.js`. Inline data mentions use `<span class="num">91.3%</span>`,
with `num--eog` (blink/blue), `num--emg` (jaw/amber) and `num--bad`
(failure/oxide red) as modifiers.

### Changing a number
Edit `data.js` only. Charts rescale themselves; don't hand-edit anything in
`visuals/`.

### Reordering, dropping or adding a figure
Sections live in the `SECTIONS` array in `story.js`. Each has a `visual:`
key naming a module in `src/visuals/index.js`. Set it to `null` to drop the
figure; reorder the array to reorder the page. To add a figure, write a
module exporting `{ id, label, provenance, caption, steps, build(stage) }`
where `build` returns `{ timeline, stepAt }`, then register it in
`visuals/index.js`.

**Step markers.** The dashes under a figure caption whatever it is drawing
at that moment, so they have to agree with the timeline. Don't hand-write
progress fractions — mark the phases with `tl.addLabel()` as you build, one
per entry in `steps`, and return
`stepAt: stepsFrom(tl, ['first', 'second', …])`. `stepsFrom` reads the label
positions back off the finished timeline, so retiming any tween moves the
markers with it instead of leaving them behind. It warns to the console if a
named label is missing.

**Text.** The figure faces are monospace, so a character count is an exact
width budget: at the 11px axis size one character is 7.04 user units, at the
12px label size 7.68. Use `wrap(str, max)` from `lib/svg.js` where a label
has to fit a column.

## Design notes

**The provenance tag.** Every figure carries a label on the right of its rule
saying where its numbers came from. Where a drawing is illustrative rather
than measured, that tag turns oxide red and says so. Three figures are
flagged this way: the waveform morphologies (Fig. 2), the manifold sketch
(Fig. 5) and the example window sequence (Fig. 8). This is the page's
signature device, and it exists because the report's own central argument is
about honest reporting.

**Palette.** Two load-bearing colours matching the report's figure
convention — ink blue for the ocular/blink family, burnt amber for the
muscular/jaw family — plus an oxide red used *only* for failure: rejected
experiments, the retracted accuracy figure, the two hot cells in the
confusion matrix. If something on the page is red, it failed.

**Type.** Newsreader (variable, with its optical-size axis actually used
across the range) for narrative; IBM Plex Mono for every label, axis, number
and caption. The serif carries the argument, the mono carries the
instrumentation.

## Why no 3D

The subject isn't spatial. The electrode montage is conventionally drawn
top-down because that's the projection that shows left/right honestly —
which is the entire basis of the bruxism distinction. The Riemannian tangent
space is high-dimensional and any 3D render of it would be a cartoon of a
metaphor rather than a picture of the data, so it's a flagged 2D schematic.

The one place 3D would genuinely earn its keep is the prosthetic hand:
rotate-left vs rotate-right is a real rotation about a real axis. That needs
the actual InMoov mesh (STL or GLB) to be worth doing — a hand built from
primitives would look worse than good SVG. Drop a mesh in and it's a
worthwhile addition; without one it isn't.

## Motion policy

- `prefers-reduced-motion: reduce` → every timeline is completed instantly
  and no ScrollTrigger is created at all. The page renders as static
  finished diagrams.
- Narrow viewport or coarse pointer → figures play through once on entry
  instead of scrubbing, and nothing is pinned. Scrubbed pinning is where
  scroll animation gets janky on phones. Timelines are authored anywhere
  between 2.8s and 9s, which is invisible under scrub but not when they
  play themselves, so the long ones are time-scaled to a common ~2.8s.
- Scroll triggers are anchored to the **drawing**, not to the figure block.
  The block opens with a label row and a caption — 158–203px of text — so
  triggering on it started every figure animating while the drawing was
  still below the fold, and the length of a caption silently decided how
  much of it happened unseen.
- **Figures reveal at a fixed line and never un-draw.** `start` and `end`
  use the same percentage, which pins the moment of appearance to one
  height on screen instead of dragging it across the viewport as the
  figure plays (see the note in `lib/motion.js`). And the scrub drives a
  proxy, passing only forward motion to the timeline, so scrolling back up
  to re-read a diagram leaves it standing rather than rewinding it to a
  blank stage.
- Wide diagrams pan horizontally on small screens rather than shrinking
  their labels to four pixels.

## Known gaps

1. **Fig. 2 traces are schematic.** They're generated to the morphology the
   report describes, not from recordings. To make them real, export five
   representative epochs (one per class, Fp1/Fp2 and T3/T4, 400 samples at
   200 Hz) and add a `sample` array to each trace in `SIGNATURES`; the
   renderer already prefers real data when it finds it.
2. **Fig. 8's window sequence is illustrative.** The thresholds, run length
   and latency are the report's; the specific seven windows are drawn to
   demonstrate the rules.
3. No cover image or author credit — add to `HERO` in `story.js`.
