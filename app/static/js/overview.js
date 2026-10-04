// The "Area overview" tab: the area chooser, headline figures, the map, past floods and the area's businesses in one list.
import { BANDS, SCENARIOS, band, depthText, h, icon, kindText, renderPicker, roadName } from "./dom.js";
import { renderHistory } from "./history.js";
import { t } from "./i18n.js";
import { createKpis } from "./kpis.js";
import { createMap } from "./map.js";
import { createScopeBar } from "./scope.js";

const $ = (id) => document.getElementById(id);

function renderLegend(element, hasShelters) {
  const items = [
    ...BANDS.map((b, i) => h("li", {}, h("span", { class: `swatch band-${i + 1}` }), b.words, h("span", { class: "muted" }, b.range))),
    h("li", {}, h("span", { class: "swatch swatch-dry" }), t("overview.legendDry")),
    hasShelters && h("li", {}, h("span", { class: "shelter-pin" }), t("common.relief")),
  ];
  element.replaceChildren(...items.filter(Boolean));
}

const depthChip = (depth, rp) => {
  const level = band(depth);
  return h("span", { class: `depth-chip${level ? ` band-${level}` : ""}`, "data-rp": rp, "data-size": t("common.rpShort", { rp }) },
    level ? depth.toFixed(1) : t("overview.dry"));
};

function directoryRows(premises, onOpen) {
  return [...premises].sort((a, b) => a.name.localeCompare(b.name)).map((p) => {
    const road = roadName(p.road.name);
    const depths = SCENARIOS.map((rp) => t("overview.rowDepth", { rp, depth: depthText(p.depth_m[rp]) })).join(", ");
    const label = t("overview.rowLabel", { name: p.name, kind: kindText(p), road, depths });
    const button = h("button", { type: "button", "aria-label": label, onclick: () => onOpen(p.id) },
      h("span", {}, h("span", { class: "name" }, p.name), h("span", { class: "meta" }, `${kindText(p)} · ${road}`)),
      SCENARIOS.map((rp) => depthChip(p.depth_m[rp], rp)));
    return { id: p.id, button, item: h("li", {}, button), text: `${p.name} ${p.kind} ${road}`.toLowerCase() };
  });
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
    status.textContent = statusText({ text: text.trim(), shown, isSearch, area });
    head.hidden = shown === 0;
    next.hidden = shown > 0 || next.children.length === 0;
  };
  filter.addEventListener("input", () => apply(filter.value, false));
  return {
    markSelected: (selectedId) => { for (const row of rows) row.button.setAttribute("aria-current", String(row.id === selectedId)); },
    showMatches: (text) => { filter.value = text; apply(text, true); },
  };
}

const setNote = (element, text) => { element.textContent = text ?? ""; element.hidden = !text; };

/** The page's words that name the area come from its config: the search's heading, the map's and the list's labels,
 *  and what the area's data notes say about where its businesses and relief centres come from (an area may have no notes). */
export function renderAreaLabels(area) {
  $("finder-hero-label").textContent = t("hero.headingIn", { area: area.name });
  $("map").setAttribute("aria-label", t("overview.mapLabel", { area: area.display_name }));
  $("directory-heading").textContent = t("overview.directoryHeading", { area: area.name });
  setNote($("directory-note"), area.notes?.businesses);
  setNote($("map-note"), [area.notes?.shelters, area.notes?.depths].filter(Boolean).join(" "));
}

/** "Pick another area": the area chooser, on show and with focus. */
function goToAreaSelect() {
  $("area-select").scrollIntoView({ block: "center" });
  $("area-select").focus({ preventScroll: true });
}

/** `area` is the page's area config (GET /api/areas/{id}/data) and `areas` the listed areas for the chooser.
 *  onArea(areaId) is for another area's page; onCheckPoint(button) opens the pin and GPS flow (pin.js) from the map's
 *  own button and from an empty list, and is null when this build cannot check points. showMatches(text) is the list,
 *  filtered by a search that could mean several businesses or none. */
export function createOverview({ area, areas, premises, town, onSelect, onOpen, onPick, onArea, onCheckPoint = null }) {
  createScopeBar($("scope"), { areas, areaId: area.id, onArea });
  renderAreaLabels(area);
  const map = createMap($("map"), area, town, premises, { onSelect, onOpen, onCheckPoint });
  const directory = createDirectory({
    list: $("directory"), filter: $("directory-filter"), status: $("directory-status"), next: $("directory-next"),
    head: document.querySelector(".directory-head"),
  }, premises, { area, onOpen, onCheckPoint, onOtherArea: areas.length > 1 ? () => goToAreaSelect() : null });
  renderLegend($("legend"), town.shelters.length > 0);
  renderHistory($("history"), area);
  const kpis = createKpis($("kpis"), { history: area.history, areaName: area.name, premises });
  let shown = {};

  return {
    map,
    showMatches: directory.showMatches,
    /** Each part changes only when its own inputs do, so focus and the live figures stay put. */
    render({ rp, selectedId, rain }) {
      if (rp !== shown.rp) {
        kpis.setScenario(rp);
        renderPicker(document.querySelector("[data-scenario]"), rp, onPick);
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
