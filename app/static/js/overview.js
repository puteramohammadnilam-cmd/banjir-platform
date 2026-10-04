// The "Area overview" tab: the area chooser, headline figures, the map, past floods and the area's businesses in one list.
import { BANDS, SCENARIOS, band, depthText, h, kindText, renderPicker, roadName } from "./dom.js";
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

function createDirectory(premises, onOpen) {
  const rows = [...premises].sort((a, b) => a.name.localeCompare(b.name)).map((p) => {
    const road = roadName(p.road.name);
    const depths = SCENARIOS.map((rp) => t("overview.rowDepth", { rp, depth: depthText(p.depth_m[rp]) })).join(", ");
    const label = t("overview.rowLabel", { name: p.name, kind: kindText(p), road, depths });
    const button = h("button", { type: "button", "aria-label": label, onclick: () => onOpen(p.id) },
      h("span", {}, h("span", { class: "name" }, p.name), h("span", { class: "meta" }, `${kindText(p)} · ${road}`)),
      SCENARIOS.map((rp) => depthChip(p.depth_m[rp], rp)));
    return { id: p.id, button, item: h("li", {}, button), text: `${p.name} ${p.kind} ${road}`.toLowerCase() };
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

const setNote = (element, text) => { element.textContent = text ?? ""; element.hidden = !text; };

/** The page's words that name the area come from its config: the map's and the list's labels, and what the area's
 *  data notes say about where its businesses and relief centres come from (an area may have no notes). */
function renderAreaLabels(area) {
  $("map").setAttribute("aria-label", t("overview.mapLabel", { area: area.display_name }));
  $("directory-heading").textContent = t("overview.directoryHeading", { area: area.name });
  setNote($("directory-note"), area.notes?.businesses);
  setNote($("map-note"), [area.notes?.shelters, area.notes?.depths].filter(Boolean).join(" "));
}

/** `area` is the page's area config (GET /api/areas/{id}/data) and `areas` the listed areas for the chooser.
 *  onArea(areaId) is for another area's page; onCheckPoint(button) opens the pin and GPS flow (pin.js) from the map's
 *  own button, and is null when this build cannot check points. */
export function createOverview({ area, areas, premises, town, onSelect, onOpen, onPick, onArea, onCheckPoint = null }) {
  createScopeBar($("scope"), { areas, areaId: area.id, onArea });
  renderAreaLabels(area);
  const map = createMap($("map"), area, town, premises, { onSelect, onOpen, onCheckPoint });
  const markSelected = createDirectory(premises, onOpen);
  renderLegend($("legend"), town.shelters.length > 0);
  renderHistory($("history"), area);
  const kpis = createKpis($("kpis"), { history: area.history, areaName: area.name, premises });
  let shown = {};

  return {
    map,
    /** Each part changes only when its own inputs do, so focus and the live figures stay put. */
    render({ rp, selectedId, rain }) {
      if (rp !== shown.rp) {
        kpis.setScenario(rp);
        renderPicker(document.querySelector("[data-scenario]"), rp, onPick);
      }
      if (rain !== shown.rain) kpis.setRain(rain);
      if (rp !== shown.rp || selectedId !== shown.selectedId) {
        map.show(rp, selectedId);
        markSelected(selectedId);
      }
      shown = { rp, selectedId, rain };
    },
  };
}
