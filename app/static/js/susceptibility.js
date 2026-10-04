// Flash flood potential (the index of Smith 2003, as Yassin et al. 2023 use it; four classes) and our score for a
// section (1 to 5, weights after Leeonis et al. 2024): how readily a place floods from heavy rain, which the river model
// leaves out. Never a depth or a chance, in any word here. The server sends a place's `flash_flood` {score, class} |
// null, a section's `indexes`, the area's `index_method` and `layers.flash_flood`; a field it never sent hides its part.
import { h, icon } from "./dom.js";
import { dataWord, formatNumber, t } from "./i18n.js";

export const FLASH_CLASSES = Object.freeze(["low", "medium", "high", "extreme"]);
export const LAYER_OPACITY = 0.7;   // the contract's palette is pale: at 0.6 low and medium blur on the map

// The PNG's own palette (the index contract's legend: OKLCH hue 50), apart from the squares' and dots' blues, so the
// layer does not read as water. Our score's orchid ramp (hue about 330) shows only on the whole city's map, which has
// no dots. tests/palette.test.mjs holds both to hue, lightness and spacing.
const FLASH_STEPS = ["#fbd9c7", "#f2ab83", "#da7738", "#a44c06"];
const SCORE_STEPS = [["#ebc7e9", 0.45], ["#cd83ca", 0.5], ["#ad57ab", 0.56], ["#853484", 0.62], ["#571a56", 0.68]];
export const FLASH_RAMP = Object.freeze(FLASH_CLASSES.map((key, i) => Object.freeze({ key, color: FLASH_STEPS[i], opacity: LAYER_OPACITY })));
export const SCORE_RAMP = Object.freeze(SCORE_STEPS.map(([color, opacity]) => Object.freeze({ color, opacity })));
const SCORE_BREAKS = [1.5, 2.5, 3.5, 4.5];

/** A class in words; null for one the page does not know. */
export const flashWord = (key) => (FLASH_CLASSES.includes(key) ? t(`flash.${key}`) : null);

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

/** A section's share of ground at high or extreme (0 to 1); null when not worked out. */
export function highShare(section) {
  const share = section?.indexes?.flash?.share;
  return share && isNumber(share.high) && isNumber(share.extreme) ? share.high + share.extreme : null;
}

export const scoreOf = (section) => (isNumber(section?.indexes?.score?.value) ? section.indexes.score.value : null);

/** 1 to 5, a value on a break going up; 0 for none. */
export const scoreClass = (value) => (isNumber(value) ? SCORE_BREAKS.filter((edge) => value >= edge).length + 1 : 0);

/** Our score shows only once the data says so: the user reviews its comparison with past floods first. */
export const showsScore = (method) => method?.show_score === true;

/** A note from the data: text, or {en, ms}. */
export const textOf = (note) => (typeof note === "string" ? note : dataWord(note));

/** The area's own example (area.json flash_flood_example, a section id) as a note, when its record names that section. */
const exampleNote = (area) => {
  const name = textOf(area?.history?.section_names?.[area.flash_flood_example]);
  return name ? t("flash.example", { section: name }) : null;
};

/** A colour at its opacity, for .ramp-swatch and .choro-swatch to lay on the map's ground. */
export function swatchStyle({ color, opacity }) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  return `--sw: rgb(${r} ${g} ${b} / ${opacity})`;
}

export const rampSwatch = (step) => h("span", { class: "ramp-swatch", style: swatchStyle(step), "aria-hidden": "true" });

export const oneDecimal = (value) => formatNumber(value, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** My business's fact: "High (7.2 of 10)", what it measures, the example of `area` (the page's, for a place in it), and
 *  that it is not a depth. null: not worked out; no field (an older server) or an unknown class: no fact. */
export function flashFact(place, area = null) {
  const value = place.flash_flood;
  if (value === undefined || (value && !flashWord(value.class))) return null;
  const step = value && FLASH_RAMP[FLASH_CLASSES.indexOf(value.class)];
  const example = value && exampleNote(area);
  return h("section", { class: "fact flash-fact" },
    h("h2", { class: "fact-label" }, icon("rain"), t("flash.label")),
    h("p", { class: "fact-value" }, step && rampSwatch(step),
      value ? t("flash.value", { level: flashWord(value.class), score: oneDecimal(value.score) }) : t("flash.notWorkedOut")),
    h("p", { class: "fact-note" }, value ? t("flash.note") : t("flash.notWorkedOutNote")),
    example && h("p", { class: "fact-note" }, example),
    h("p", { class: "fineprint" }, t("flash.fineprint")));
}

const METRIC_WORDS = { depth: "choropleth.metricDepth", flash: "choropleth.metricFlash", score: "choropleth.metricScore" };

/** Under the map: the layer's checkbox (off at first) when `hasLayer`, and a radio per metric key when there are two or
 *  more, the first chosen. onLayer(isOn) and onMetric(key) hear the choices. */
export function mapControls({ hasLayer, metrics = [], word = null, onLayer = () => {}, onMetric = () => {} }) {
  return [
    hasLayer && h("label", { class: "layer-toggle" },
      h("input", { type: "checkbox", onchange: (event) => onLayer(Boolean(event.target.checked)) }), t("flash.toggle")),
    metrics.length > 1 && h("fieldset", { class: "metric-choice" },
      h("legend", {}, t("choropleth.metricLegend", { word: dataWord(word, { lower: true }) })),
      metrics.map((key, i) => h("label", {},
        h("input", { type: "radio", name: "section-metric", value: key, checked: i === 0, onchange: () => onMetric(key) }), t(METRIC_WORDS[key])))),
  ].filter(Boolean);
}

const sourceItem = (source) => (typeof source === "string" ? h("li", {}, source) : h("li", {}, source?.url
  ? h("a", { href: source.url, target: "_blank", rel: "noopener noreferrer" }, source.text ?? source.title) : source?.text ?? source?.title));

const listPart = (heading, items, item) => (items?.length ? [h("h3", { class: "small-heading" }, heading), h("ul", {}, items.map(item))] : []);

const both = (method, key, showScore) => [...(method?.flash?.[key] ?? []), ...((showScore && method?.score?.[key]) || [])];

/** "How these are worked out", from the area's `index_method` {flash, score, validation} (null: our words only). */
export function methodBody(method, { showScore, word = null, credit = null }) {
  return [
    h("p", {}, t("flash.method")),
    showScore && h("p", {}, t("score.method", { word: dataWord(word, { lower: true }) }), " ", textOf(method?.validation?.wording ?? "")),
    ...listPart(t("flash.deviations"), both(method, "deviations", showScore), (text) => h("li", {}, textOf(text))),
    credit && h("p", { class: "fineprint" }, credit),
    ...listPart(t("flash.sources"), both(method, "citations", showScore), sourceItem),
  ].filter(Boolean);
}
