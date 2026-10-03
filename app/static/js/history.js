// An area's past floods: a strip of dots and a list of sources. The floods are the area's data (its area.json,
// `history`), paraphrased from the sources named there, with figures as printed. `year` only places the dot on the
// strip; `account` marks a single person's undated memory. An area without a record says so and draws no strip.
import { h, s } from "./dom.js";
import { t } from "./i18n.js";

const DOT_Y = 22;
const AXIS_Y = 30;
const TICK_EVERY_YEARS = 5;
const LONG_RECORD_YEARS = 40;   // past this the labels come every 10 years, so they never touch

/** Dated floods (an undated account is kept apart) and those since the area's `recent_from` year, or null when no
 *  flood record has been collected for the area. */
export function floodCounts(history) {
  if (!history?.floods?.length) return null;
  const dated = history.floods.filter((flood) => !flood.account);
  return {
    dated: dated.length,
    recent: dated.filter((flood) => flood.year >= history.recent_from).length,
    since: history.first_year,
    recentFrom: history.recent_from,
  };
}

/** The years to label on the strip: round years from the first one inside the record to its last. */
export function tickYears(first, last) {
  const step = last - first > LONG_RECORD_YEARS ? TICK_EVERY_YEARS * 2 : TICK_EVERY_YEARS;
  const start = Math.ceil(first / step) * step;
  return Array.from({ length: Math.max(0, Math.floor((last - start) / step) + 1) }, (_, i) => start + i * step);
}

/** Positions are percentages and the svg has no viewBox, so text keeps its real size on a phone. */
function strip({ floods, first_year: first, last_year: last }) {
  const xOf = (year) => `${2 + ((year + 0.5 - first) / Math.max(1, last - first)) * 96}%`;
  const byYear = new Map();   // one dot a year, with a count, so a narrow screen never piles dots on top of each other
  for (const flood of floods) {
    const year = Math.floor(flood.year);
    const seen = byYear.get(year) ?? { count: 0, account: true };
    byYear.set(year, { count: seen.count + 1, account: seen.account && Boolean(flood.account) });
  }
  const dots = [...byYear].map(([year, { count, account }]) => s("g", {},
    s("circle", { class: account ? "flood-dot is-account" : "flood-dot", cx: xOf(year), cy: DOT_Y, r: 5 }),
    count > 1 && s("text", { class: "flood-count", x: xOf(year), y: DOT_Y - 9, "text-anchor": "middle" }, `×${count}`)));
  const ticks = tickYears(first, last).map((year) =>
    s("text", { x: xOf(year), y: AXIS_Y + 16, "text-anchor": "middle" }, String(year)));
  return s("svg", { class: "flood-strip", height: AXIS_Y + 22, "aria-hidden": "true" },
    s("line", { class: "axis", x1: "1%", x2: "99%", y1: AXIS_Y, y2: AXIS_Y }), ticks, dots);
}

/** The area's flood record in `element`, or a note that none has been collected. `area` is the page's area config:
 *  {name, display_name, history}. */
export function renderHistory(element, area) {
  const counts = floodCounts(area.history);
  const heading = h("h2", { id: "history-heading" }, t("history.heading"));
  if (!counts) {
    element.replaceChildren(heading, h("p", { class: "history-none" }, t("history.none", { area: area.display_name })));
    return;
  }
  const { history } = area;
  const memory = history.floods.some((flood) => flood.account) ? t("history.memory") : "";
  element.replaceChildren(
    heading,
    h("p", { class: "history-lead" }, h("strong", {}, t("history.leadDated", { n: counts.dated })),
      t("history.leadMid", { area: area.name, since: counts.since }),
      h("strong", {}, t("history.leadRecent", { n: counts.recent, from: counts.recentFrom })), t("history.leadEnd")),
    strip(history),
    h("p", { class: "fineprint" }, t("history.mapNote", { memory })),
    h("details", {}, h("summary", {}, t("history.list")),   // each flood's own words are the area's data, as its sources have them
      h("ol", { class: "flood-list" }, history.floods.map((f) => h("li", {},
        h("strong", {}, f.when), ` ${f.what} `, h("span", { class: "muted" }, f.source))))),
  );
}
