/* global L */
// The whole city on one map: each section shaded by the share of its 90 m squares that get water in the model at the
// flood size on show. Squares, not businesses: the model covers every square, where the public map misses many shops.
// The six classes take the squares' own ramp (cells.js), so a pale section reads like a pale square. One path per
// section, on the map's shared canvas: no element each, out of the tab order. The sortable table (section-table.js)
// is the same information for the keyboard and screen readers, and the map's description points to it. The shading
// shows a metric {value, class, classes, tooltip, heading}: the river model's squares (DEPTH_METRIC) by default.
import { SQUARE_RAMP } from "./cells.js";
import { h } from "./dom.js";
import { dataWord, t } from "./i18n.js";
import { FLASH_RAMP, SCORE_RAMP, highShare, oneDecimal, scoreClass, scoreOf, swatchStyle } from "./susceptibility.js";

const OUTLINE = "#46d3ff";   // --brand in tokens.css
const LIFTED = "#ffb14a";    // --marker: the section under the pointer, as a picked place is
const STREET_ZOOM = 15;     // from here in, a point's own squares show: the shading steps back to a wash
const STREET_WASH = 0.25;
const REVEAL_STAGGER_MS = 18;   // the wettest section first, the next a moment later: about a second for a city of 56
const REVEAL_FADE_MS = 520;
const NO_SHARE = Object.freeze({ upTo: 0, color: OUTLINE, opacity: 0, words: () => t("choropleth.none") });
const BOUNDS = [0.05, 0.15, 0.3, 0.5, Infinity];   // each class's top: under 5%, 5-15, 15-30, 30-50 (50 included), over 50
const WORDS = [
  () => t("choropleth.under", { pct: 5 }), () => t("choropleth.range", { from: 5, to: 15 }), () => t("choropleth.range", { from: 15, to: 30 }),
  () => t("choropleth.range", { from: 30, to: 50 }), () => t("choropleth.over", { pct: 50 }),
];

/** [none, then one per step of the squares' ramp]: {upTo, color, opacity, words()}. */
export const SHARE_CLASSES = Object.freeze([NO_SHARE, ...SQUARE_RAMP.map((step, i) => Object.freeze({
  upTo: BOUNDS[i], color: step.color, opacity: step.opacity, words: WORDS[i],
}))]);

/** The share of a section's squares with water at flood size `rp`: 0 when it has no squares, or no counts. */
export function shareOf(section, rp) {
  const cells = section?.counts?.cells ?? 0;
  return cells > 0 ? (section.counts.wet_cells?.[rp] ?? 0) / cells : 0;
}

/** The class of a share: 0 for none, else 1 to 5. A share on a class's lower edge goes to that class; 50% to "30-50%". */
export function shareClass(share) {
  if (!(share > 0)) return 0;
  const index = BOUNDS.findIndex((top, i) => (i === 3 ? share <= top : share < top));
  return index + 1;
}

/** A share in whole percent; one under 1% says so, not 0%. */
export const shareText = (share) => (share > 0 && share < 0.005 ? t("choropleth.underOne") : `${Math.round(share * 100)}%`);

/** What the tooltip says, a line each: the section, its squares, its businesses, and that a tap opens it. */
export function tooltipLines(section, rp) {
  const { businesses = 0, wet_businesses: wet = {} } = section.counts ?? {};
  return [section.name, t("choropleth.tipSquares", { share: shareText(shareOf(section, rp)) }),
    t("choropleth.tipBusinesses", { wet: wet[rp] ?? 0, total: businesses }), t("choropleth.tipOpen")];
}

const tooltipNode = (lines) => {
  const [name, ...rest] = lines;
  return h("div", { class: "choro-tip" }, h("strong", {}, name), rest.map((line, i) => h("span", { class: i === rest.length - 1 ? "choro-tip-open" : null }, line)));
};

export const DEPTH_METRIC = Object.freeze({
  value: shareOf, class: shareClass, classes: SHARE_CLASSES, tooltip: tooltipLines, heading: (word) => t("choropleth.heading", { word }),
});

const FLASH_TOPS = [0.1, 0.25, 0.5];   // under 10%, 10-25, 25-50 (50 included), over 50
const FLASH_WORDS = [() => t("choropleth.under", { pct: 10 }), () => t("choropleth.range", { from: 10, to: 25 }),
  () => t("choropleth.range", { from: 25, to: 50 }), () => t("choropleth.over", { pct: 50 })];
const SCORE_WORDS = ["very_low", "low", "moderate", "high", "very_high"].map((id, i) => () => `${i + 1} · ${t(`score.${id}`)}`);
const tip = (section, value, none, text) => [section.name, value === null ? t(none) : text(value), t("choropleth.tipOpen")];

/** The share of a section's ground at high or extreme flash flood potential, in the warm ramp; a share of 0 is "under
 *  10%", and only a section with no figures is "not worked out" (outlined only). */
export const FLASH_METRIC = Object.freeze({
  value: highShare,
  class: (share) => (Number.isFinite(share) ? FLASH_TOPS.filter((top, i) => (i === 2 ? share > top : share >= top)).length + 1 : 0),
  classes: [{ ...NO_SHARE, words: () => t("choropleth.metricNone") }, ...FLASH_RAMP.map((step, i) => ({ ...step, words: FLASH_WORDS[i] }))],
  tooltip: (section) => tip(section, highShare(section), "choropleth.metricTipFlashNone", (share) => t("choropleth.metricTipFlash", { share: shareText(share) })),
  heading: (word) => t("choropleth.metricFlashHeading", { word }),
});

/** Our score, 1 to 5, in its own ramp; none is outlined only. */
export const SCORE_METRIC = Object.freeze({
  value: scoreOf, class: scoreClass,
  classes: [{ ...NO_SHARE, words: () => t("choropleth.metricNone") }, ...SCORE_RAMP.map((step, i) => ({ ...step, words: SCORE_WORDS[i] }))],
  tooltip: (section) => tip(section, scoreOf(section), "choropleth.metricTipScoreNone", (score) => t("choropleth.metricTipScore", { score: oneDecimal(score) })),
  heading: (word) => t("choropleth.metricScoreHeading", { word }),
});

const paint = (metric, section, rp, wash = 1) => {
  const step = metric.classes[metric.class(metric.value(section, rp))];
  return { fill: true, fillColor: step.color, fillOpacity: step.opacity * wash };
};
const outline = (isLifted) => ({ color: isLifted ? LIFTED : OUTLINE, weight: isLifted ? 3 : 1, opacity: isLifted ? 0.9 : 0.55 });

const keySwatch = (metric, step, i) => (metric === DEPTH_METRIC
  ? h("span", { class: `choro-swatch sq-${i}` }) : h("span", { class: "choro-swatch", style: swatchStyle(step) }));

/** The key: a heading in the area's own word for a section, a swatch per class of `metric` (the river model's are the
 *  squares' steps), and `extra`, one more item of the map's (the relief centre's pin), when given. */
export function choroplethKey(word, extra = null, metric = DEPTH_METRIC) {
  return h("li", { class: "legend-group" },
    h("p", { class: "legend-heading" }, metric.heading(dataWord(word, { lower: true }))),
    h("ul", { class: "legend-items choro-key" }, metric.classes.map((step, i) =>
      h("li", {}, keySwatch(metric, step, i), step.words())), extra));
}

/** Draws `sections` (each with its GeoJSON `outline` and `counts`) on `renderer`, the map's canvas. onOpen(id) opens a
 *  section, from a click, except while isAiming() says a point is being aimed at (a tap there moves the map). show(rp)
 *  shades them for a flood size, setMetric(metric) by what; highlight(id) lifts one outline (null for none), as
 *  hovering one does. Zoomed in to street level, where a checked point's own squares are drawn, the shading steps back
 *  to a wash. */
export function createChoropleth(map, renderer, sections, { onOpen, isAiming = () => false }) {
  let rp = null;
  let metric = DEPTH_METRIC;
  let lifted = null;
  const wash = () => ((map.getZoom?.() ?? 0) >= STREET_ZOOM ? STREET_WASH : 1);
  const paths = new Map(sections.map((section) => {
    const path = L.geoJSON(section.outline, { renderer, interactive: true, bubblingMouseEvents: false });
    path.setStyle({ ...outline(false), ...paint(metric, section, rp) })
      .bindTooltip(() => tooltipNode(metric.tooltip(section, rp)), { sticky: true, direction: "top", className: "choro-tooltip", opacity: 1 })
      .on("click", () => { if (!isAiming()) onOpen(section.id); })
      .on("mouseover", () => highlight(section.id))
      .on("mouseout", () => highlight(null))
      .addTo(map);
    return [section.id, { section, path }];
  }));

  function highlight(id) {
    if (lifted === id) return;
    paths.get(lifted)?.path.setStyle(outline(false));
    lifted = paths.has(id) ? id : null;
    paths.get(lifted)?.path.setStyle(outline(true)).bringToFront();
  }

  let frame = 0;
  const repaint = () => {
    globalThis.cancelAnimationFrame?.(frame);
    for (const { section, path } of paths.values()) path.setStyle(paint(metric, section, rp, wash()));
  };

  /** The water comes in: each section's shading fades up, the wettest first. Once, as the page opens; a new flood size
   *  or metric repaints them all at once. */
  function reveal() {
    const order = [...paths.values()].sort((a, b) => (metric.value(b.section, rp) ?? 0) - (metric.value(a.section, rp) ?? 0));
    for (const { section, path } of order) path.setStyle(paint(metric, section, rp, 0));   // so no frame shows them full first
    const start = performance.now();
    const step = (now) => {
      let isDone = true;
      order.forEach(({ section, path }, i) => {
        const k = Math.min(1, Math.max(0, (now - start - i * REVEAL_STAGGER_MS) / REVEAL_FADE_MS));
        if (k < 1) isDone = false;
        path.setStyle(paint(metric, section, rp, wash() * k));
      });
      if (!isDone) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
  }
  map.on?.("zoomend", repaint);

  return {
    show(next) {
      rp = next;
      repaint();
    },
    setMetric(next) {
      metric = next;
      repaint();
    },
    highlight,
    reveal,
  };
}
