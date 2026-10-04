// The "Area overview" tab: the area chooser, headline figures, the map, past floods and the area's businesses in one list.
// A city split into sections has two kinds of page: a section's, which is an area's page for the section, and the whole
// city's, where the map shades each section (choropleth.js), a table ranks them (section-table.js) and the list of
// businesses waits for a name, as the city has thousands.
import { SQUARE_RAMP } from "./cells.js";
import { choroplethKey, createChoropleth } from "./choropleth.js";
import { BANDS, SCENARIOS, band, depthText, h, icon, kindText, renderPicker, roadName } from "./dom.js";
import { renderHistory } from "./history.js";
import { dataWord, t } from "./i18n.js";
import { createKpis } from "./kpis.js";
import { createMap } from "./map.js";
import { createScopeBar } from "./scope.js";
import { createSectionTable } from "./section-table.js";

const $ = (id) => document.getElementById(id);
const CITY_LIST_MAX = 100;   // rows the whole city's list shows for one filter; typing more narrows them
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

/** The map's key. On the whole city's map (`city` given, with the area's `word` for a section) the sections' shading
 *  takes the dots' place, as no business is drawn there. */
export function renderLegend(element, hasShelters, city = null) {
  const first = city
    ? choroplethKey(city.word, hasShelters ? h("li", {}, h("span", { class: "shelter-pin" }), t("common.relief")) : null)
    : legendGroup(t("legend.dots"), dotKey(hasShelters));
  element.replaceChildren(first, legendGroup(t("legend.squares"), squareKey()));
}

const depthChip = (depth, rp) => {
  const level = band(depth);
  return h("span", { class: `depth-chip${level ? ` band-${level}` : ""}`, "data-rp": rp, "data-size": t("common.rpShort", { rp }) },
    level ? depth.toFixed(1) : t("overview.dry"));
};

/** One row of the list: the business's name, kind and road (and its section, in the whole city's list), and its depths. */
function directoryRow(p, onOpen, sectionName = null) {
  const road = roadName(p.road.name);
  const depths = SCENARIOS.map((rp) => t("overview.rowDepth", { rp, depth: depthText(p.depth_m[rp]) })).join(", ");
  const where = sectionName ? ` ${t("city.rowIn", { section: sectionName })}` : "";
  const label = `${t("overview.rowLabel", { name: p.name, kind: kindText(p), road, depths })}${where}`;
  const meta = [kindText(p), road, sectionName].filter(Boolean).join(" · ");
  const button = h("button", { type: "button", "aria-label": label, onclick: () => onOpen(p.id) },
    h("span", {}, h("span", { class: "name" }, p.name), h("span", { class: "meta" }, meta)),
    SCENARIOS.map((rp) => depthChip(p.depth_m[rp], rp)));
  return { id: p.id, button, item: h("li", {}, button), text: `${p.name} ${p.kind} ${road} ${sectionName ?? ""}`.toLowerCase() };
}

const byName = (a, b) => a.name.localeCompare(b.name);

function directoryRows(premises, onOpen) {
  return [...premises].sort(byName).map((p) => directoryRow(p, onOpen));
}

/** What the list says over its rows: how many a search found, or why none is on show. */
function statusText({ text, shown, isSearch, area }) {
  if (!isSearch) return shown ? "" : t("overview.noMatch");
  if (!shown) return t("overview.notListed", { area: area.name });
  return shown === 1 ? t("overview.matchOne", { text }) : t("overview.matches", { count: shown, text });
}

/** The ways on from an empty list: the spot itself, on the map, and another area. */
const nextSteps = ({ onCheckPoint, onOtherArea }) => [
  onCheckPoint && h("button", { type: "button", class: "btn btn-primary", onclick: (event) => onCheckPoint(event.currentTarget) },
    icon("pin"), t("overview.checkSpot")),
  onOtherArea && h("button", { type: "button", class: "btn btn-secondary", onclick: () => onOtherArea() }, t("overview.otherArea")),
].filter(Boolean);

/** The area's businesses in one list, with its filter box: typing in `filter` filters them by name, type or road, and
 *  showMatches(text) does the same for a search that did not open one business (pick.js), and says how many it found.
 *  With none on show, `next` holds the ways on: onCheckPoint(button) checks the spot on the map (null when this build
 *  cannot check points) and onOtherArea() goes to the area chooser (null with one area listed). */
export function createDirectory({ list, filter, status, next, head }, premises,
  { area, onOpen, onCheckPoint = null, onOtherArea = null }) {
  const rows = directoryRows(premises, onOpen);
  list.replaceChildren(...rows.map((row) => row.item));
  next.replaceChildren(...nextSteps({ onCheckPoint, onOtherArea }));
  const apply = (text, isSearch) => {
    const needle = text.trim().toLowerCase();
    let shown = 0;
    for (const row of rows) {
      row.item.hidden = Boolean(needle) && !row.text.includes(needle);
      if (!row.item.hidden) shown += 1;
    }
    status.textContent = rows.length ? statusText({ text: text.trim(), shown, isSearch, area }) : t("city.noneMapped", { area: area.name });
    head.hidden = shown === 0;
    next.hidden = shown > 0 || next.children.length === 0;
  };
  filter.addEventListener("input", () => apply(filter.value, false));
  if (!rows.length) apply("", false);   // a section with no businesses mapped says so at once
  return {
    markSelected: (selectedId) => { for (const row of rows) row.button.setAttribute("aria-current", String(row.id === selectedId)); },
    showMatches: (text) => { filter.value = text; apply(text, true); },
  };
}

/** The whole city's list: the lean `index` of its businesses, each with its section's name. Nothing shows until a name
 *  is typed, then at most CITY_LIST_MAX rows, built as they are needed; otherwise it reads as createDirectory's list. */
export function createCityDirectory({ list, filter, status, next, head }, index, { area, sections, onOpen, onCheckPoint = null, onOtherArea = null }) {
  const names = new Map(sections.map((section) => [section.id, section.name]));
  const entries = [...index].sort(byName).map((p) => ({ p, text: `${p.name} ${p.kind} ${roadName(p.road.name)} ${names.get(p.section) ?? ""}`.toLowerCase() }));
  next.replaceChildren(...nextSteps({ onCheckPoint, onOtherArea }));
  let rows = [];
  let selected = null;
  const mark = () => { for (const row of rows) row.button.setAttribute("aria-current", String(row.id === selected)); };
  const apply = (text, isSearch) => {
    const needle = text.trim().toLowerCase();
    const matches = needle ? entries.filter((entry) => entry.text.includes(needle)) : [];
    rows = matches.slice(0, CITY_LIST_MAX).map(({ p }) => directoryRow(p, onOpen, names.get(p.section)));
    list.replaceChildren(...rows.map((row) => row.item));
    mark();
    if (!needle) status.textContent = t("city.directoryHint", { count: index.length, area: area.name });
    else if (matches.length > CITY_LIST_MAX) status.textContent = t("city.directoryMore", { shown: CITY_LIST_MAX, count: matches.length });
    else status.textContent = statusText({ text: text.trim(), shown: rows.length, isSearch, area });
    head.hidden = rows.length === 0;
    next.hidden = !needle || rows.length > 0 || next.children.length === 0;
  };
  filter.addEventListener("input", () => apply(filter.value, false));
  apply("", false);
  return {
    markSelected: (selectedId) => { selected = selectedId; mark(); },
    showMatches: (text) => { filter.value = text; apply(text, true); },
  };
}

const setNote = (element, text) => { element.textContent = text ?? ""; element.hidden = !text; };

/** The page's words that name the area come from its config: the search's heading, the map's and the list's labels,
 *  and what the area's data notes say about where its businesses and relief centres come from (an area may have no notes).
 *  On the whole city's map (`city` given, with its `word` for a section) the map is about the sections' shading, and the
 *  table of sections under it, which holds the same figures, describes it. */
export function renderAreaLabels(area, city = null) {
  $("finder-hero-label").textContent = t("hero.headingIn", { area: area.name });
  $("directory-heading").textContent = t("overview.directoryHeading", { area: area.name });
  setNote($("directory-note"), area.notes?.businesses);
  setNote($("map-note"), [area.notes?.shelters, area.notes?.depths].filter(Boolean).join(" "));
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

/** The whole city's own parts: the shading on the map and the table under it, each repainted for a flood size. */
function createCityParts(map, city) {
  const word = dataWord(city.word, { lower: true });
  const choropleth = map.addOverlay(({ map: leaflet, renderer, isAiming }) =>
    createChoropleth(leaflet, renderer, city.sections, { onOpen: city.onSection, isAiming }));
  $("sections-surface").hidden = false;
  const table = createSectionTable($("sections-table"), { sections: city.sections, word: city.word, hrefOf: city.hrefOf, onHighlight: choropleth.highlight });
  return {
    show(rp) {
      choropleth.show(rp);
      table.show(rp);
      $("sections-lead").textContent = t("sections.lead", { rp, word });
    },
  };
}

/** `area` is the page's area config (GET /api/areas/{id}/data; for a section, the section dressed as an area, start.js
 *  pageArea) and `areas` the listed areas for the chooser. onArea(areaId) is for another area's page; onCheckPoint(button)
 *  opens the pin and GPS flow (pin.js) from the map's own button and from an empty list, and is null when this build
 *  cannot check points. showMatches(text) is the list, filtered by a search that could mean several businesses or none.
 *  `city` is null for a plain area; for a city split into sections it is {sections, word, section (null on the whole
 *  city), index (the whole city's lean list), wholeCity, onSection(id | null), hrefOf(id), cityHref, cityName}. */
export function createOverview({ area, areas, premises, town, onSelect, onOpen, onPick, onArea, onCheckPoint = null, city = null }) {
  const isWholeCity = Boolean(city && !city.section);
  createScopeBar($("scope"), { areas, areaId: area.id, onArea, ...cityScope(city) });
  renderAreaLabels(area, isWholeCity ? city : null);
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
  const cityParts = isWholeCity ? createCityParts(map, city) : null;
  let shown = {};

  return {
    map,
    showMatches: directory.showMatches,
    /** Each part changes only when its own inputs do, so focus and the live figures stay put. */
    render({ rp, selectedId, rain }) {
      if (rp !== shown.rp) {
        kpis.setScenario(rp);
        renderPicker(document.querySelector("[data-scenario]"), rp, onPick, area.bigger_flood_example);
        cityParts?.show(rp);
      }
      if (rain !== shown.rain) kpis.setRain(rain);
      if (rp !== shown.rp || selectedId !== shown.selectedId) {
        map.show(rp, selectedId);
        directory.markSelected(selectedId);
      }
      shown = { rp, selectedId, rain };
    },
  };
}
