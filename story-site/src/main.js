import '@fontsource-variable/newsreader';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/600.css';
import './styles/base.css';

import { HERO, SECTIONS, COLOPHON } from './content/story.js';
import { VISUALS } from './visuals/index.js';
import { bind, revealOnEnter, refresh, reduced } from './lib/motion.js';

const app = document.getElementById('app');

/* ------------------------------------------------------------------
   Hero
   ------------------------------------------------------------------ */
function renderHero() {
  const header = document.createElement('header');
  header.className = 'hero';
  header.innerHTML = `
    <div class="col">
      <p class="hero__eyebrow">${HERO.eyebrow}</p>
      <h1 class="hero__title">${HERO.title}</h1>
      <p class="hero__dek">${HERO.dek}</p>
      <div class="provenance-strip">
        ${HERO.strip.map((s) => `<span>${s}</span>`).join('')}
      </div>
      <p class="scroll-cue">${HERO.cue}</p>
    </div>
  `;
  app.appendChild(header);
}

/* ------------------------------------------------------------------
   Figures — chrome first, then the module draws into the stage.
   ------------------------------------------------------------------ */
/* Chrome is created up front; the drawing itself is deferred until the
   figure is in the document, because path.getTotalLength() is only
   dependable on elements that have actually been laid out. */
const pending = [];

function renderFigure(key) {
  const mod = VISUALS[key];
  if (!mod) {
    console.warn(`[story] no visual registered as "${key}"`);
    return null;
  }

  const fig = document.createElement('figure');
  fig.className = 'figure';
  fig.id = `fig-${mod.id}`;

  const provClass = mod.schematic ? 'figure__prov figure__prov--schematic' : 'figure__prov';
  fig.innerHTML = `
    <div class="figure__head">
      <span class="figure__label">${mod.label}</span>
      <span class="${provClass}">${mod.provenance}</span>
    </div>
    <figcaption class="figure__caption">${mod.caption}</figcaption>
    <div class="figure__stage"></div>
    ${mod.steps ? `<div class="figure__steps">${mod.steps.map((s) => `<span></span><i>${s}</i>`).join('')}</div>` : ''}
  `;

  pending.push({ mod, fig });
  return fig;
}

function buildPendingFigures() {
  pending.forEach(({ mod, fig }) => {
    const stage = fig.querySelector('.figure__stage');
    let built;
    try {
      built = mod.build(stage);
    } catch (err) {
      console.error(`[story] figure "${mod.id}" failed to build`, err);
      return;
    }

    const markers = [...fig.querySelectorAll('.figure__steps span')];
    const onUpdate = built.stepAt
      ? (p) => {
          const i = built.stepAt(p);
          markers.forEach((m, k) => m.classList.toggle('on', k <= i));
        }
      : null;

    /* Bound to the stage rather than the whole figure: the scrub range
       should be the drawing's transit through the viewport, not the
       block's, which starts a caption's height earlier. */
    bind(stage, built.timeline, { mode: 'scrub', onUpdate });
  });
}

/* ------------------------------------------------------------------
   Sections
   ------------------------------------------------------------------ */
function renderSection(sec) {
  const el = document.createElement('section');
  el.className = 'section';
  el.id = sec.id;

  const col = document.createElement('div');
  col.className = 'col reveal';
  col.innerHTML = `
    <p class="section__eyebrow">${sec.eyebrow}</p>
    <h2 class="section__title">${sec.title}</h2>
    ${sec.body.map((p) => `<p>${p}</p>`).join('')}
  `;
  el.appendChild(col);

  if (sec.visual) {
    const fig = renderFigure(sec.visual);
    if (fig) el.appendChild(fig);
  }

  if (sec.turn) {
    const q = document.createElement('div');
    q.className = 'col';
    q.innerHTML = `<blockquote class="turn ${sec.turnKind === 'found' ? 'turn--found' : ''} reveal">${sec.turn}</blockquote>`;
    el.appendChild(q);
  }

  if (sec.openList) {
    const list = document.createElement('div');
    list.className = 'col';
    list.innerHTML = `<ol class="open-list">${sec.openList
      .map((o) => `<li class="reveal"><h3>${o.title}</h3><p>${o.text}</p></li>`)
      .join('')}</ol>`;
    el.appendChild(list);
  }

  return el;
}

/* ------------------------------------------------------------------
   Boot
   ------------------------------------------------------------------ */
renderHero();
SECTIONS.forEach((sec) => app.appendChild(renderSection(sec)));

const foot = document.createElement('footer');
foot.className = 'colophon';
foot.innerHTML = `<div class="col">${COLOPHON.map((l) => `<div>${l}</div>`).join('')}</div>`;
app.appendChild(foot);

buildPendingFigures();
revealOnEnter([...document.querySelectorAll('.reveal')]);

/* Fonts change metrics, which changes every trigger position. */
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => refresh());
}
window.addEventListener('load', () => refresh());

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(refresh, 180);
});

if (reduced) document.documentElement.setAttribute('data-motion', 'reduced');
