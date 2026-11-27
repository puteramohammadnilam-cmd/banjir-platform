// The list of every business in an area or a city, with each one's water at the three flood sizes and a filter by name
// or kind: the old interface's Area overview list (overview.js) and the new map's (map-gl-area.js), the same code.
import { SCENARIOS, band, depthText, h, icon, kindText, roadName } from "./dom.js";
import { t } from "./i18n.js";

const CITY_LIST_MAX = 100;   // rows the whole city's list shows for one filter; typing more narrows them

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

/** What the list says over its rows: none mapped here, more matches than it shows, or statusText's words. */
function listStatus({ text, shown, found, isSearch, area, hasRows }) {
  if (!hasRows) return t("city.noneMapped", { area: area.name });
  if (found > shown) return t("city.directoryMore", { shown, count: found });
  return statusText({ text: text.trim(), shown, isSearch, area });
}

/** The area's businesses in one list, with its filter box: typing in `filter` filters them by name, type or road, and
 *  showMatches(text) does the same for a search that did not open one business (pick.js), and says how many it found.
 *  With none on show, `next` holds the ways on: onCheckPoint(button) checks the spot on the map (null when this build
 *  cannot check points) and onOtherArea() goes to the area chooser (null with one area listed). widen(index, sections,
 *  cityName) takes in a city's lean index: then a filter also shows the rest of the city's matches, after the list's
 *  own, each with its section, at most CITY_LIST_MAX (a section's page, once its city's index is in). `hint` is what
 *  the list says while its filter is empty and it has no rows of its own (the whole city's). */
export function createDirectory({ list, filter, status, next, head }, premises,
  { area, onOpen, onCheckPoint = null, onOtherArea = null, hint = null }) {
  const rows = directoryRows(premises, onOpen);
  let city = null;   // {entries, names, area}, once widened
  let more = [];     // the rows of the rest of the city on show
  let selected = null;
  const mark = () => { for (const row of [...rows, ...more]) row.button.setAttribute("aria-current", String(row.id === selected)); };
  list.replaceChildren(...rows.map((row) => row.item));
  next.replaceChildren(...nextSteps({ onCheckPoint, onOtherArea }));
  const apply = (text, isSearch) => {
    const needle = text.trim().toLowerCase();
    for (const row of rows) row.item.hidden = Boolean(needle) && !row.text.includes(needle);
    const own = rows.filter((row) => !row.item.hidden).length;
    const found = city && needle ? city.entries.filter((entry) => entry.text.includes(needle)) : [];
    more = found.slice(0, CITY_LIST_MAX).map(({ p }) => directoryRow(p, onOpen, city.names.get(p.section)));
    if (city) list.replaceChildren(...rows.map((row) => row.item), ...more.map((row) => row.item));
    mark();
    const shown = own + more.length;
    const isCitywide = Boolean(city && needle);   // the city was searched, so none found names it
    const isHint = Boolean(hint) && !needle;
    status.textContent = isHint ? hint : listStatus({
      text, shown, found: own + found.length, isSearch, area: isCitywide ? city.area : area, hasRows: rows.length > 0 || isCitywide,
    });
    head.hidden = shown === 0;
    next.hidden = shown > 0 || isHint || next.children.length === 0;
  };
  filter.addEventListener("input", () => apply(filter.value, false));
  if (!rows.length) apply("", false);   // a section with no businesses mapped says so at once
  return {
    markSelected: (selectedId) => { selected = selectedId; mark(); },
    showMatches: (text) => { filter.value = text; apply(text, true); },
    widen: (index, sections, cityName) => {
      const here = new Set(premises.map((p) => p.id));
      const names = new Map(sections.map((section) => [section.id, section.name]));
      const entries = index.filter((p) => !here.has(p.id)).sort(byName)
        .map((p) => ({ p, text: `${p.name} ${p.kind} ${roadName(p.road.name)} ${names.get(p.section) ?? ""}`.toLowerCase() }));
      city = { entries, names, area: { name: cityName } };
      if (filter.value.trim()) apply(filter.value, false);
    },
  };
}

/** The whole city's list: its lean `index`, each business with its section's name. Nothing shows until a name is
 *  typed, then at most CITY_LIST_MAX rows, built as they are needed. */
export function createCityDirectory(parts, index, { area, sections, ...ways }) {
  const directory = createDirectory(parts, [], { area, ...ways, hint: t("city.directoryHint", { count: index.length, area: area.name }) });
  directory.widen(index, sections, area.name);
  return directory;
}
