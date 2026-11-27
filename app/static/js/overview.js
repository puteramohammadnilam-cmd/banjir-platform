// The "Area overview" tab: the area chooser, headline figures, the map, past floods and the area's businesses in one list.
// A city split into sections has two kinds of page: a section's, which is an area's page for the section, and the whole
// city's, where the map shades each section (choropleth.js), a table ranks them (section-table.js) and the list of
// businesses waits for a name, as the city has thousands. Under the map: flash flood potential's checkbox, on the
// whole city's map what the sections are shaded by (susceptibility.js), and the low ground layer's (lowground.js).
import { SQUARE_RAMP } from "./cells.js";
import { DEPTH_METRIC, FLASH_METRIC, SCORE_METRIC, choroplethKey, createChoropleth } from "./choropleth.js";
import { BANDS, SCENARIOS, band, h, renderPicker } from "./dom.js";
import { createEvacuation } from "./evacuation.js";
import { createTide } from "./tide.js";
import { createOutlook } from "./outlook.js";
import { renderHistory } from "./history.js";
import { dataWord, t } from "./i18n.js";
import { createKpis } from "./kpis.js";
import { createLowGround } from "./lowground.js";
import { createMap, createPictureLayer } from "./map.js";
import { createScopeBar } from "./scope.js";
import { renderStamp, scenarioSentence } from "./stamp.js";
import { createSectionTable } from "./section-table.js";
import { createCityDirectory, createDirectory } from "./directory.js";
import { listNotes, renderLosses, renderMethod } from "./reference-cards.js";
import {
  FLASH_RAMP, LAYER_OPACITY, flashWord, indexMetrics, mapControls, rampSwatch, showsScore,
} from "./susceptibility.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_SIZE = SCENARIOS.at(-1);   // the biggest flood size shown, as pick.js DEFAULT_RP

/** One group of the key: a heading over what it explains. */
const legendGroup = (heading, content) => h("li", { class: "legend-group" }, h("p", { class: "legend-heading" }, heading), content);

/** The dots: the five depth classes, a pale dot for no water, and the relief centre's pin when the area has one. */
const dotKey = (hasShelters) => h("ul", { class: "legend-items" },
  BANDS.map((b, i) => h("li", {}, h("span", { class: `swatch band-${i + 1}` }), b.words, h("span", { class: "muted" }, b.range))),
  h("li", {}, h("span", { class: "swatch swatch-dry" }), t("overview.legendDry")),
  hasShelters && h("li", {}, h("span", { class: "shelter-pin" }), t("common.relief")));

/** The squares: a strip of the ramp's five steps, shallowest to deepest, with the depths at its two ends. */
const squareKey = () => h("div", { class: "square-key" },
  h("span", { class: "muted" }, BANDS[0].range),
  h("span", { class: "square-strip", "aria-hidden": "true" }, SQUARE_RAMP.map((_, i) => h("span", { class: `sq-${i + 1}` }))),
  h("span", { class: "muted" }, BANDS[BANDS.length - 1].range));

const flashKey = (credit) => legendGroup(t("flash.legend"), [h("ul", { class: "legend-items ramp-key" },
  FLASH_RAMP.map((step) => h("li", {}, rampSwatch(step), flashWord(step.key)))), credit && h("p", { class: "fineprint" }, credit)]);

/** The map's key. On the whole city's map (`city` given, with the area's `word` for a section) the sections' shading
 *  by `metric` takes the dots' place, as no business is drawn there. With the flash flood layer on, its classes and the
 *  layer's data `credit` too; `lowKey` is the low ground layer's group (lowground.js), while that is on. */
export function renderLegend(element, hasShelters, city = null, { metric = DEPTH_METRIC, isFlashOn = false, credit = null, lowKey = null, isDay = false } = {}) {
  const first = city
    ? choroplethKey(city.word, hasShelters ? h("li", {}, h("span", { class: "shelter-pin" }), t("common.relief")) : null, metric)
    : legendGroup(t("legend.dots"), dotKey(hasShelters));
  element.replaceChildren(...[first, legendGroup(t(isDay ? "legend.squaresDay" : "legend.squares"), squareKey()), isFlashOn && flashKey(credit), lowKey].filter(Boolean));
}

const METRICS = { depth: DEPTH_METRIC, flash: FLASH_METRIC, score: SCORE_METRIC };
const METRIC_LEADS = { depth: "city.mapLead", flash: "choropleth.metricFlashLead", score: "choropleth.metricScoreLead" };

export { indexMetrics } from "./susceptibility.js";   // tests and older callers read it here

/** The controls under the map in `slot` (susceptibility.js mapControls) for a `layer` ({url, bounds, credit}, fetched
 *  once ticked) and `metrics`; onChange({isFlashOn, metric}) hears each change. A layer that fails unticks and says so.
 *  `extra` are more controls to show after these (the low ground layer's). */
export function createIndexControls(slot, { map, layer, metrics, word = null, validation = null, onChange, extra = [] }) {
  let state = { isFlashOn: false, metric: metrics[0] ?? "depth" };
  const alert = h("p", { class: "alert alert-inline layer-error", role: "alert", hidden: true });
  const set = (change) => { state = { ...state, ...change }; onChange(state); };
  const failed = () => {
    slot.querySelector('[type="checkbox"]').checked = false;
    alert.textContent = t("flash.layerError");
    alert.hidden = false;
    set({ isFlashOn: false });
  };
  const picture = layer?.url ? map.addOverlay(({ map: leaflet }) =>
    createPictureLayer(leaflet, layer, { opacity: LAYER_OPACITY, className: "flash-overlay", onError: failed })) : null;
  const nodes = mapControls({
    hasLayer: Boolean(picture), metrics, word, validation, onMetric: (metric) => set({ metric }),
    onLayer: (isOn) => { alert.hidden = true; picture.show(isOn); set({ isFlashOn: isOn }); },
  });
  slot.replaceChildren(...(nodes.length ? [...nodes, alert] : []), ...extra);
  slot.hidden = nodes.length + extra.length === 0;
}


/** The area's data notes, each folded under a short heading of what it tells ([key, text] pairs; a note the area does
 *  not have is left out). Long and needed by few, so they are there to open, not to wade through. */
function foldNotes(element, notes) {
  const shown = notes.filter(([, text]) => text);
  element.replaceChildren(...shown.map(([key, text]) => h("details", { class: "area-note" }, h("summary", {}, t(key)), h("p", { class: "fineprint" }, text))));
  element.hidden = !shown.length;
}

/** The page's words that name the area come from its config: the search's heading, the map's and the list's labels,
 *  and what the area's data notes say about where its businesses and relief centres come from (an area may have no notes).
 *  On the whole city's map (`city` given, with its `word` for a section) the map is about the sections' shading, and the
 *  table of sections under it, which holds the same figures, describes it. */
export { lossWords, renderMethod } from "./reference-cards.js";   // tests and older callers read them here
export { createCityDirectory, createDirectory } from "./directory.js";

export function renderAreaLabels(area, city = null) {
  $("finder-hero-label").textContent = t("hero.headingIn", { area: area.name });
  $("directory-heading").textContent = t("overview.directoryHeading", { area: area.name });
  foldNotes($("directory-note"), [["overview.noteBusinesses", area.notes?.businesses]]);
  listNotes($("map-note"), $("map-notes-card"), [["overview.noteDepths", area.notes?.depths], ["overview.noteShelters", area.notes?.shelters],
    ["overview.noteSections", area.notes?.sections], ["overview.noteBusinesses", area.notes?.businesses]]);
  renderLosses(area.losses);
  if (!city) {
    $("map").setAttribute("aria-label", t("overview.mapLabel", { area: area.display_name }));
    return;
  }
  const word = dataWord(city.word, { lower: true });
  $("map").setAttribute("aria-label", t("city.mapLabel", { area: area.display_name, word }));
  $("map").setAttribute("aria-describedby", "sections-caption");
  $("map-lead").textContent = t("city.mapLead", { word });
  $("sections-heading").textContent = t("sections.heading", { word });
}

/** "Pick another area": the area chooser, on show and with focus. */
function goToAreaSelect() {
  $("area-select").scrollIntoView({ block: "center" });
  $("area-select").focus({ preventScroll: true });
}

/** The scope bar's part for a city split into sections: its section select, and the way back to the whole city. */
const cityScope = (city) => (city ? {
  sections: city.sections, sectionId: city.section?.id ?? null, word: city.word, wholeCity: city.wholeCity,
  onSection: city.onSection, cityHref: city.cityHref, cityName: city.cityName,
} : {});

/** What the map opens on and which squares are the page's own (pin.js and cells.js draw a point's others): a section's
 *  box, none on the whole city's map (it draws no squares of its own), else the area's view. */
export function mapFrame(area, city) {
  if (city?.section) return { view: city.section.bbox, zoom: city.section.zoom, ownedBox: city.section.bbox, outline: city.section.outline, fit: true };
  return city ? { view: area.view, zoom: area.zoom, ownedBox: null, outline: null, fit: true } : { view: area.view, zoom: area.zoom, ownedBox: area.view, outline: null };
}

/** For a section with floods on record where the river model shows no water at its businesses (or none at all): that
 *  the map shows river floods only. null elsewhere, and on the whole city's page. */
export function riverOnlyNote(area, section) {
  if (!section || !area.history?.floods?.length) return null;
  const { businesses = 0, wet_businesses: wet = {}, wet_cells: cells = {} } = section.counts ?? {};
  const isDry = (cells[DEFAULT_SIZE] ?? 0) === 0 || (businesses > 0 && (wet[DEFAULT_SIZE] ?? 0) === 0);
  return isDry ? t("city.riverOnly", { area: area.name }) : null;
}

/** The whole city's own parts: the shading on the map and the table under it, each repainted for a flood size, and the
 *  shading and the map's lead for the metric picked. */
function createCityParts(map, city, showScore) {
  const word = dataWord(city.word, { lower: true });
  const choropleth = map.addOverlay(({ map: leaflet, renderer, isAiming }) =>
    createChoropleth(leaflet, renderer, city.sections, { onOpen: city.onSection, isAiming }));
  $("sections-surface").hidden = false;
  const table = createSectionTable($("sections-table"), {
    sections: city.sections, word: city.word, hrefOf: city.hrefOf, onHighlight: choropleth.highlight, showScore,
  });
  let isFirst = true;
  return {
    show(rp) {
      choropleth.show(rp);
      if (isFirst && globalThis.matchMedia?.("(prefers-reduced-motion: no-preference)").matches) choropleth.reveal();
      isFirst = false;
      table.show(rp);
      $("sections-lead").textContent = t("sections.lead", { rp, word });
    },
    setMetric(key) {
      choropleth.setMetric(METRICS[key]);
      $("map-lead").textContent = t(METRIC_LEADS[key], { word });
    },
  };
}

/** The controls under the map (flash flood potential's, the low ground layer's), which repaint the key (and the city's
 *  shading), and "How these are worked out". */
function createIndexParts(map, area, { city, cityParts, hasShelters }) {
  const keyCity = cityParts ? city : null;
  const layer = area.layers?.flash_flood ?? null;
  let shown = { isFlashOn: false, metric: "depth", lowKey: null };
  const paint = (change) => {
    shown = { ...shown, ...change };
    // the flash flood, score and low ground ramps were made for a pale map: while one is on, the map turns to day
    const isDay = Boolean(shown.isFlashOn || shown.lowKey || shown.metric !== "depth");
    $("map").classList.toggle("is-day", isDay);
    $("map").classList.toggle("is-day-water", isDay && shown.metric === "depth");   // views.css turns the squares back to darker = deeper
    renderLegend($("legend"), hasShelters, keyCity, { metric: METRICS[shown.metric], isFlashOn: shown.isFlashOn, credit: layer?.credit, lowKey: shown.lowKey, isDay });
  };
  const low = createLowGround(map, area.layers?.low_ground ?? null, { onChange: (lowKey) => paint({ lowKey }) });
  createIndexControls($("map-controls"), {
    map, layer, word: city?.word ?? null, validation: area.index_method?.validation ?? null, extra: low.nodes,
    metrics: cityParts ? indexMetrics(city.sections, area.index_method) : [],
    onChange: (state) => {
      cityParts?.setMetric(state.metric);
      paint(state);
    },
  });
  renderMethod($("index-method"), $("index-method-body"), area, { word: area.section_word ?? null });
}

/** `area` is the page's area config (GET /api/areas/{id}/data; for a section, the section dressed as an area, start.js
 *  pageArea) and `areas` the listed areas for the chooser. onArea(areaId) is for another area's page; onCheckPoint(button)
 *  opens the pin and GPS flow (pin.js) from the map's own button and from an empty list, and is null when this build
 *  cannot check points. showMatches(text) is the list, filtered by a search that could mean several businesses or none.
 *  `city` is null for a plain area; for a city split into sections it is {sections, word, section (null on the whole
 *  city), index (the whole city's lean list), wholeCity, onSection(id | null), hrefOf(id), cityHref(), cityName}. */
export function createOverview({ area, areas, premises, town, onSelect, onOpen, onPick, onArea, onCheckPoint = null, city = null }) {
  const isWholeCity = Boolean(city && !city.section);
  const scope = createScopeBar($("scope"), { areas, areaId: area.id, onArea, ...cityScope(city) });
  renderAreaLabels(area, isWholeCity ? city : null);
  if (city) $("finder-hero-label").textContent = t("hero.headingIn", { area: city.cityName });   // the search covers the whole city
  const riverOnly = riverOnlyNote(area, city?.section ?? null);
  if (riverOnly) $("map-lead").after(h("p", { class: "alert alert-inline alert-info river-note" }, riverOnly));   // up top, beside the map it explains
  const map = createMap($("map"), mapFrame(area, city), town, premises, { onSelect, onOpen, onCheckPoint });
  const parts = {
    list: $("directory"), filter: $("directory-filter"), status: $("directory-status"), next: $("directory-next"),
    head: document.querySelector(".directory-head"),
  };
  const ways = { area, onOpen, onCheckPoint, onOtherArea: areas.length > 1 ? () => goToAreaSelect() : null };
  const directory = isWholeCity ? createCityDirectory(parts, city.index, { ...ways, sections: city.sections }) : createDirectory(parts, premises, ways);
  renderLegend($("legend"), town.shelters.length > 0, isWholeCity ? city : null);
  renderHistory($("history"), area);   // area.history is the whole city's or the section's, as the server cut it
  const kpis = createKpis($("kpis"), { history: area.history, areaName: area.name, premises: isWholeCity ? city.index : premises });
  renderStamp($("stamp"), { history: area.history, areaName: area.name });
  const cityParts = isWholeCity ? createCityParts(map, city, showsScore(area.index_method)) : null;
  const evacuation = createEvacuation($("evacuation"));
  const tideCard = createTide($("tide"));
  const outlookCard = createOutlook($("outlook"));
  createIndexParts(map, area, { city, cityParts, hasShelters: town.shelters.length > 0 });
  let shown = {};

  return {
    map,
    showMatches: directory.showMatches,
    /** On a section's page: the city's lean index is in, so the list's filter and a search reach the whole city. */
    widen: (index) => { if (city?.section) directory.widen(index, city.sections, city.cityName); },
    /** Each part changes only when its own inputs do, so focus and the live figures stay put. */
    render({ rp, selectedId, rain, evacuation: centres, tide, outlook }) {
      if (rp !== shown.rp) {
        kpis.setScenario(rp);
        $("scenario-sentence").textContent = scenarioSentence(rp);
        renderPicker(document.querySelector("[data-scenario]"), rp, onPick, area.bigger_flood_example);
        cityParts?.show(rp);
        scope.refresh();   // "All of {city}" carries the flood size, as the table's links do
      }
      if (rain !== shown.rain) kpis.setRain(rain);
      evacuation.set(centres);   // each keeps its own last state, so the same answer is not drawn twice
      tideCard.set(tide);
      outlookCard.set(outlook);
      if (rp !== shown.rp || selectedId !== shown.selectedId) {
        map.show(rp, selectedId);
        directory.markSelected(selectedId);
      }
      shown = { rp, selectedId, rain };
    },
  };
}
