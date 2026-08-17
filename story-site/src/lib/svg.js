/* Small SVG helpers. No dependencies. */

const NS = 'http://www.w3.org/2000/svg';

export function svg(viewBox, attrs = {}) {
  const el = document.createElementNS(NS, 'svg');
  el.setAttribute('viewBox', viewBox);
  el.setAttribute('xmlns', NS);
  el.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

export function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    node.setAttribute(k, v);
  }
  if (parent) parent.appendChild(node);
  return node;
}

export function group(parent, attrs = {}) {
  return el('g', attrs, parent);
}

export function text(parent, str, attrs = {}) {
  const node = el('text', attrs, parent);
  node.textContent = str;
  return node;
}

/** Greedy word wrap to a character budget.
    The figure type is monospace throughout, so a character count is an
    exact width budget: at the 11px axis size one character is 7.04 user
    units, at the 12px label size 7.68. Divide the space available by
    those to get `max`. */
export function wrap(str, max) {
  const out = [];
  let line = '';
  for (const w of str.split(' ')) {
    if ((line + ' ' + w).trim().length > max) { out.push(line.trim()); line = w; }
    else line += ' ' + w;
  }
  if (line.trim()) out.push(line.trim());
  return out;
}

/** Read a CSS custom property off :root so SVGs follow tokens.css. */
export function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Catmull–Rom-ish smooth path through points [[x,y],…]. */
export function smoothPath(points, tension = 0.35) {
  if (points.length < 2) return '';
  let d = `M ${points[0][0]} ${points[0][1]}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const c1x = p1[0] + ((p2[0] - p0[0]) / 6) * tension * 2;
    const c1y = p1[1] + ((p2[1] - p0[1]) / 6) * tension * 2;
    const c2x = p2[0] - ((p3[0] - p1[0]) / 6) * tension * 2;
    const c2y = p2[1] - ((p3[1] - p1[1]) / 6) * tension * 2;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return d;
}

/** Deterministic pseudo-random in [-1,1], so schematic traces are stable. */
export function noise(seed) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s / 2147483647) * 2 - 1;
  };
}

/** Prepare a path for a draw-on animation. Returns its length.
    Only dependable once the path is in the document and laid out. */
export function primeDraw(path) {
  const len = path.getTotalLength ? path.getTotalLength() : 0;
  path.style.strokeDasharray = len;
  path.style.strokeDashoffset = len;
  return len;
}
