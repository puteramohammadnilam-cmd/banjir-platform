/* global L */
// The whole city on one map: each section shaded by the share of its 90 m squares that get water in the model at the
// flood size on show. Squares, not businesses: the model covers every square, where the public map misses many shops.
// The six classes take the squares' own ramp (cells.js), so a pale section reads like a pale square. One path per
// section, on the map's shared canvas: no element each, out of the tab order. The sortable table (section-table.js)
// is the same information for the keyboard and screen readers, and the map's description points to it.
import { SQUARE_RAMP } from "./cells.js";
import { h } from "./dom.js";
import { dataWord, t } from "./i18n.js";

const OUTLINE = "#0c447c";   // --brand in tokens.css
const LIFTED = "#0d1b2a";    // --ink
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

const tooltipNode = (section, rp) => {
  const [name, ...rest] = tooltipLines(section, rp);
  return h("div", { class: "choro-tip" }, h("strong", {}, name), rest.map((line, i) => h("span", { class: i === rest.length - 1 ? "choro-tip-open" : null }, line)));
};

const paint = (share) => {
  const step = SHARE_CLASSES[shareClass(share)];
  return { fill: true, fillColor: step.color, fillOpacity: step.opacity };
};
const outline = (isLifted) => ({ color: isLifted ? LIFTED : OUTLINE, weight: isLifted ? 3 : 1, opacity: isLifted ? 0.9 : 0.55 });

/** The key: a heading in the area's own word for a section, a swatch per class (the same steps as the squares'), and
 *  `extra`, one more item of the map's (the relief centre's pin), when given. */
export function choroplethKey(word, extra = null) {
  return h("li", { class: "legend-group" },
    h("p", { class: "legend-heading" }, t("choropleth.heading", { word: dataWord(word, { lower: true }) })),
    h("ul", { class: "legend-items choro-key" }, SHARE_CLASSES.map((step, i) =>
      h("li", {}, h("span", { class: `choro-swatch sq-${i}` }), step.words())), extra));
}

/** Draws `sections` (each with its GeoJSON `outline` and `counts`) on `renderer`, the map's canvas. onOpen(id) opens a
 *  section, from a click, except while isAiming() says a point is being aimed at (a tap there moves the map). show(rp)
 *  shades them for a flood size; highlight(id) lifts one outline (null for none), as hovering one does. */
export function createChoropleth(map, renderer, sections, { onOpen, isAiming = () => false }) {
  let rp = null;
  let lifted = null;
  const paths = new Map(sections.map((section) => {
    const path = L.geoJSON(section.outline, { renderer, interactive: true, bubblingMouseEvents: false });
    path.setStyle({ ...outline(false), ...paint(0) })
      .bindTooltip(() => tooltipNode(section, rp), { sticky: true, direction: "top", className: "choro-tooltip", opacity: 1 })
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

  return {
    show(next) {
      rp = next;
      for (const { section, path } of paths.values()) path.setStyle(paint(shareOf(section, rp)));
    },
    highlight,
  };
}
