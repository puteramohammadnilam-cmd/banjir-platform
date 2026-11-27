// The map's extra layers on the new map (map.html), in its layers card: the flash flood potential picture and the low
// ground picture (the area's `layers`) and, on a city split into sections, what the sections' shading shows (the river
// model's share of wet squares, the flash flood potential, or our score). The old interface's choices, words and
// colours (susceptibility.js mapControls, choropleth.js metrics, lowground.js), drawn with map-gl-eng.js's picture
// drawer under the sections and squares, low ground under flash.
import { FLASH_METRIC, SCORE_METRIC } from "./choropleth.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { DEFAULT_LEVEL, LOW_OPACITY, levelUrl, levelsOf, lowGroundKey } from "./lowground.js";
import { FLASH_RAMP, LAYER_OPACITY, flashWord, indexMetrics, mapControls, rampSwatch } from "./susceptibility.js";

const METRICS = { flash: FLASH_METRIC, score: SCORE_METRIC };

/** The sections' fill for `metric` ("flash" or "score"), as MapLibre expressions by section id: each section's class in
 *  the old map's ramp, and its opacity. */
export function metricPaint(sections, metric) {
  const of = (section) => {
    const step = METRICS[metric].classes[METRICS[metric].class(METRICS[metric].value(section))];
    return { color: step.color, opacity: step.opacity };
  };
  const match = (pick, none) => ["match", ["get", "id"], ...sections.flatMap((section) => [section.id, pick(of(section))]), none];
  return { color: match((step) => step.color, "rgba(0,0,0,0)"), opacity: match((step) => step.opacity, 0) };
}

/** A key of swatches and words, in the old map's legend's look. */
const swatches = (steps) => h("ul", { class: "legend-items ramp-key" }, steps.map(([step, words]) => h("li", {}, rampSwatch(step), words)));

/** `area` is the area's data, `sections` a city's (else []); `drawer` a picture drawer (map-gl-eng.js glDrawer) and
 *  onMetric(metric) is told when the sections' shading changes ("depth", "flash" or "score"). Gives {nodes} for the
 *  layers card (none when the area has no layer and one shading) and metric(). */
export function createMapLayers({ area, sections, drawer, onMetric }) {
  const flash = area.layers?.flash_flood?.url ? area.layers.flash_flood : null;
  const low = area.layers?.low_ground ?? null;
  const levels = levelsOf(low);
  const st = { isFlashOn: false, isLowOn: false, level: levels.includes(DEFAULT_LEVEL) ? DEFAULT_LEVEL : levels[0], metric: "depth" };
  const key = h("div", { class: "mg-layer-key" });
  const drawKey = () => key.replaceChildren(...[
    st.isFlashOn && swatches(FLASH_RAMP.map((step) => [step, flashWord(step.key)])),
    st.metric !== "depth" && swatches(METRICS[st.metric].classes.slice(1).map((step) => [step, step.words()])),
    st.isLowOn && h("ul", {}, lowGroundKey(st.level)),
  ].filter(Boolean));
  const showLow = () => {
    drawer.drop("low");
    if (st.isLowOn) drawer.picture("low", levelUrl(low, st.level), low.bounds, LOW_OPACITY);
    choice.hidden = !st.isLowOn;
    drawKey();
  };
  const choice = h("fieldset", { class: "metric-choice lowground-levels", hidden: true }, h("legend", {}, t("lowground.levelLegend")),
    levels.map((value) => h("label", {}, h("input", { type: "radio", name: "mg-low-level", value, checked: value === st.level,
      onchange: () => { st.level = value; showLow(); } }), t("lowground.level", { m: value }))));
  const lowNodes = levels.length ? [h("label", { class: "layer-toggle" }, h("input", { type: "checkbox",
    onchange: (event) => { st.isLowOn = Boolean(event.target.checked); showLow(); } }), t("lowground.toggle")), choice] : [];
  const controls = mapControls({
    hasLayer: Boolean(flash), metrics: sections.length ? indexMetrics(sections, area.index_method) : [], word: area.section_word ?? null,
    validation: area.index_method?.validation ?? null,
    onLayer: (isOn) => {
      st.isFlashOn = isOn;
      if (isOn) drawer.picture("flash", flash.url, flash.bounds, LAYER_OPACITY);
      else drawer.drop("flash");
      drawKey();
    },
    onMetric: (metric) => {
      st.metric = metric;
      onMetric(metric);
      drawKey();
    },
  });
  const nodes = [...controls, ...lowNodes];
  return { nodes: nodes.length ? [h("div", { class: "mg-layer-extra" }, ...nodes, key)] : [], metric: () => st.metric };
}
