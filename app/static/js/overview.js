// The "Area overview" tab: the area chooser, headline figures, the map, past floods and the area's businesses in one list.
import { BANDS, SCENARIOS, band, depthText, h, icon, kindText, renderPicker } from "./dom.js";
import { floodCounts, renderHistory } from "./history.js";
import { createMap } from "./map.js";
import { createScopeBar } from "./scope.js";

const $ = (id) => document.getElementById(id);

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** One figure tile, built once and updated in place, so its bar can animate and the live region only speaks on change. */
function kpiTile(iconName, { hero = false, bar = false } = {}) {
  const figure = h("p", { class: "kpi-figure" });
  const label = h("p", { class: "kpi-label" });
  const note = h("p", { class: "kpi-note" });
  const fill = bar ? h("span") : null;
  if (fill) fill.style.transform = "scaleX(0)";
  const node = h("div", { class: `kpi${hero ? " kpi-hero" : ""}` }, icon(iconName), figure, label, note,
    fill && h("div", { class: "kpi-bar", "aria-hidden": "true" }, fill));
  return {
    node,
    set(figureText, labelText, noteText, share) {
      figure.textContent = figureText;
      label.textContent = labelText;
      note.textContent = noteText;
      if (fill) fill.style.transform = `scaleX(${share})`;
    },
  };
}

function rainText(rain) {
  if (!rain || rain.busy) return ["…", "Rain due in the next 12 hours", "Checking Google Weather"];
  if (!rain.configured) return ["–", "Rain forecast", "Google Weather is not set up in this build"];
  if (rain.error || !rain.data) return ["–", "Rain due in the next 12 hours", "Google Weather did not answer just now"];
  const { total_mm: total, max_chance_pct: chance, hours } = rain.data;
  return [`${total} mm`, `Rain due in the next ${hours} hours`, `Chance up to ${chance}%. Google Weather, not a flood warning`];
}

function renderLegend(element, hasShelters) {
  const items = [
    ...BANDS.map((b, i) => h("li", {}, h("span", { class: `swatch band-${i + 1}` }), b.words, h("span", { class: "muted" }, b.range))),
    h("li", {}, h("span", { class: "swatch swatch-dry" }), "No water in the model"),
    hasShelters && h("li", {}, h("span", { class: "shelter-pin" }), "Flood relief centre"),
  ];
  element.replaceChildren(...items.filter(Boolean));
}

const depthChip = (depth, rp) => {
  const level = band(depth);
  return h("span", { class: `depth-chip${level ? ` band-${level}` : ""}`, "data-rp": rp }, level ? depth.toFixed(1) : "dry");
};

function createDirectory(premises, onOpen) {
  const rows = [...premises].sort((a, b) => a.name.localeCompare(b.name)).map((p) => {
    const depths = SCENARIOS.map((rp) => `1 in ${rp} years ${depthText(p.depth_m[rp])}`).join(", ");
    const button = h("button", { type: "button", "aria-label": `${p.name}, ${kindText(p)}, near ${p.road.name}. ${depths}.`, onclick: () => onOpen(p.id) },
      h("span", {}, h("span", { class: "name" }, p.name), h("span", { class: "meta" }, `${kindText(p)} · ${p.road.name}`)),
      SCENARIOS.map((rp) => depthChip(p.depth_m[rp], rp)));
    return { id: p.id, button, item: h("li", {}, button), text: `${p.name} ${p.kind} ${p.road.name}`.toLowerCase() };
  });
  $("directory").replaceChildren(...rows.map((row) => row.item));
  $("directory-filter").addEventListener("input", (event) => {
    const needle = event.target.value.trim().toLowerCase();
    let shown = 0;
    for (const row of rows) {
      row.item.hidden = Boolean(needle) && !row.text.includes(needle);
      if (!row.item.hidden) shown += 1;
    }
    $("directory-empty").hidden = shown > 0;
  });
  return (selectedId) => { for (const row of rows) row.button.setAttribute("aria-current", String(row.id === selectedId)); };
}

/** The "Floods recorded" tile: the area's own counts, or a dash when no flood record has been collected for it. */
function floodTileText(history) {
  const counts = floodCounts(history);
  if (!counts) return ["–", "Floods recorded", "No flood record collected yet"];
  return [String(counts.recent), `Floods recorded since ${counts.recentFrom}`, `${counts.dated} since ${counts.since}, in the sources we checked`];
}

function createKpis(history) {
  const tiles = { wet: kpiTile("wave", { hero: true, bar: true }), depth: kpiTile("store"), flood: kpiTile("clock"), rain: kpiTile("rain") };
  tiles.flood.set(...floodTileText(history));
  $("kpis").replaceChildren(tiles.wet.node, tiles.depth.node, tiles.flood.node, tiles.rain.node);
  return tiles;
}

const setNote = (element, text) => { element.textContent = text ?? ""; element.hidden = !text; };

/** The page's words that name the area come from its config: the map's and the list's labels, and what the area's
 *  data notes say about where its businesses and relief centres come from (an area may have no notes). */
function renderAreaLabels(area) {
  $("map").setAttribute("aria-label", `Map of ${area.display_name}, with modelled flood depth at each business`);
  $("directory-heading").textContent = `Businesses in ${area.name}`;
  setNote($("directory-note"), area.notes?.businesses);
  setNote($("map-note"), [area.notes?.shelters, area.notes?.depths].filter(Boolean).join(" "));
}

/** `area` is the page's area config (GET /api/areas/{id}/data) and `areas` the listed areas for the chooser.
 *  onArea(areaId) is for another area's page; onCheckPoint(button) opens the pin and GPS flow (pin.js), from the scope
 *  bar's button and from the map's own, and is null when this build cannot check points. */
export function createOverview({ area, areas, premises, town, onSelect, onOpen, onPick, onArea, onCheckPoint = null }) {
  createScopeBar($("scope"), { areas, areaId: area.id, onArea, onCheckPoint });
  renderAreaLabels(area);
  const map = createMap($("map"), area, town, premises, { onSelect, onOpen, onCheckPoint });
  const markSelected = createDirectory(premises, onOpen);
  renderLegend($("legend"), town.shelters.length > 0);
  renderHistory($("history"), area);
  const tiles = createKpis(area.history);
  let shown = {};

  return {
    map,
    /** Each part changes only when its own inputs do, so focus and the live figures stay put. */
    render({ rp, selectedId, rain }) {
      if (rp !== shown.rp) {
        const wet = premises.filter((p) => band(p.depth_m[rp]));
        const share = premises.length ? wet.length / premises.length : 0;
        tiles.wet.set(`${wet.length} of ${premises.length}`, `businesses in ${area.name} get water`, `In a 1 in ${rp} years flood, in the model`, share);
        tiles.depth.set(wet.length ? `${median(wet.map((p) => p.depth_m[rp])).toFixed(1)} m` : "–", "Typical depth at a wet business", "Half are deeper, in the model");
        renderPicker(document.querySelector("[data-scenario]"), rp, onPick);
      }
      if (rain !== shown.rain) tiles.rain.set(...rainText(rain));
      if (rp !== shown.rp || selectedId !== shown.selectedId) {
        map.show(rp, selectedId);
        markSelected(selectedId);
      }
      shown = { rp, selectedId, rain };
    },
  };
}
