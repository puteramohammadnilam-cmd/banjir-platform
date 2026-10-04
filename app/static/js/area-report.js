// A one-page flood summary of the area on show, to print or save as a PDF, for trade associations and councils. Every
// figure is worked out here from the area's own data (its businesses' modelled depths); nothing is asked of the AI.
import { CHANCE_YEARS, SCENARIOS, UNNAMED_ROAD, chanceWithin, h } from "./dom.js";
import { shareOf, shareText } from "./choropleth.js";
import { isSearched } from "./history.js";
import { dataWord, t } from "./i18n.js";
import { DEFAULT_RP } from "./pick.js";

const TOP_STREETS = 5;
const TOP_SECTIONS = 10;

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

/** {total, floods: [{rp, wet, percent, median, chance}], streets: [{name, wet}]}: per flood size, how many businesses
 *  get water in the model and the median depth among them; the streets with the most wet businesses at the default size (1 in 50). */
export function areaSummary(premises) {
  const total = premises.length;
  const floods = SCENARIOS.map((rp) => {
    const wet = premises.map((p) => p.depth_m[rp]).filter((depth) => depth > 0);
    return { rp, wet: wet.length, percent: total ? Math.round((100 * wet.length) / total) : 0,
      median: wet.length ? median(wet) : null, chance: Math.round(100 * chanceWithin(Number(rp), CHANCE_YEARS)) };
  });
  const byStreet = new Map();
  for (const p of premises) {
    if (p.depth_m[DEFAULT_RP] > 0 && p.road?.name && p.road.name !== UNNAMED_ROAD) byStreet.set(p.road.name, (byStreet.get(p.road.name) ?? 0) + 1);
  }
  const streets = [...byStreet].map(([name, wet]) => ({ name, wet }))
    .sort((a, b) => b.wet - a.wet || a.name.localeCompare(b.name)).slice(0, TOP_STREETS);
  return { total, floods, streets };
}

function floodTable({ total, floods }) {
  return h("table", { class: "loss-table" },
    h("thead", {}, h("tr", {}, [t("cost.colSize"), t("report.colChance", { years: CHANCE_YEARS }), t("report.colWet"), t("report.colMedian")]
      .map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, floods.map((f) => h("tr", {},
      h("th", { scope: "row" }, t("common.rpYears", { rp: f.rp })), h("td", {}, `${f.chance}%`),
      h("td", {}, t("report.wet", { wet: f.wet, total, pct: f.percent })),
      h("td", {}, f.median == null ? t("report.none") : t("common.metres", { m: f.median.toFixed(1) }))))));
}

function record(area) {
  const { history } = area;
  const floods = history?.floods ?? [];
  if (!floods.length && isSearched(history)) {   // searched, with none found: as the page's own record says it
    return [h("p", {}, t("history.noneFound", { area: area.name, from: history.first_year, to: history.last_year }))];
  }
  if (!floods.length) return [h("p", {}, t("report.noRecord", { area: area.name }))];
  return [h("ul", {}, floods.map((f) => h("li", {},
    `${f.when}: ${f.what} (${f.source})`, f.account ? t("report.account") : "")))];
}

/** A city's sections with the most businesses with water at the default size (1 in 50), biggest first, ties in the
 *  data's order; at most TOP_SECTIONS, and none with none: [{id, name, wet, total, share}]. */
export function topSections(sections) {
  return sections.map((section) => ({
    id: section.id, name: section.name, wet: section.counts?.wet_businesses?.[DEFAULT_RP] ?? 0,
    total: section.counts?.businesses ?? 0, share: shareOf(section, DEFAULT_RP),
  })).filter((row) => row.wet > 0).sort((a, b) => b.wet - a.wet).slice(0, TOP_SECTIONS);
}

/** The whole city's sheet adds its sections with the most businesses with water, in the area's own `word` for one. */
function sectionsPart(sections, word) {
  const rows = topSections(sections);
  return [h("h4", {}, t("report.sectionsHeading", { word: dataWord(word, { lower: true }), rp: DEFAULT_RP })),
    rows.length ? h("div", { class: "table-scroll" }, h("table", { class: "loss-table" },
      h("thead", {}, h("tr", {}, [dataWord(word), t("sections.colBusinesses"), t("sections.colSquares")].map((text) => h("th", { scope: "col" }, text)))),
      h("tbody", {}, rows.map((row) => h("tr", {}, h("th", { scope: "row" }, row.name),
        h("td", {}, t("overview.wetFigure", { wet: row.wet, total: row.total })), h("td", {}, shareText(row.share)))))))
      : h("p", {}, t("report.noStreets"))];
}

/** The sheet. `date` is the day it is printed, as text. For a whole city `premises` is its lean index and `sections`
 *  its sections (with `word`, the area's word for one); otherwise sections is null. */
export function buildAreaReport({ area, premises, date, sections = null, word = null }) {
  const summary = areaSummary(premises);
  const notes = Object.values(area.notes ?? {}).filter(Boolean);
  return h("article", { class: "plan-sheet area-report" },
    h("h3", {}, t("report.title", { area: area.display_name })),
    h("p", {}, t("report.lead", { total: summary.total })),
    h("div", { class: "table-scroll" }, floodTable(summary)),
    h("h4", {}, t("report.streets", { rp: DEFAULT_RP })),
    summary.streets.length
      ? h("ul", {}, summary.streets.map((s) => h("li", {}, `${s.name}: ${s.wet}`)))
      : h("p", {}, t("report.noStreets")),
    ...(sections ? sectionsPart(sections, word) : []),
    h("h4", {}, t("report.floods")), ...record(area),
    ...(notes.length ? [h("h4", {}, t("report.notes")), h("ul", {}, notes.map((n) => h("li", {}, n)))] : []),
    area.council ? h("p", {}, t("report.council", { council: area.council })) : null,
    h("p", { class: "fineprint" }, t("report.footer", { date })));
}
