// An area's past floods: a strip of dots and a list of sources. The floods are the area's data (its area.json
// `history`, or for an area split into sections the record app/history.py cuts to the whole area or one section),
// paraphrased from the sources named there, with figures as printed. `year` only places the dot on the strip; `account`
// marks a single person's undated memory, `undated` a year whose reports give no day. A record cut to a scope also has
// links (https only), source types, a confidence, sections and a gaps line. An area without a record says so and draws
// no strip; a scope with no flood found says that is not the same as no flood.
import { h, s } from "./dom.js";
import { lang, t } from "./i18n.js";

const DOT_Y = 34;    // room above the dots for two rows of counts
const AXIS_Y = 42;
const COUNT_GAP_YEARS = 2;   // counts this close in years would overlap on a phone-wide strip
const TICK_EVERY_YEARS = 5;
const LONG_RECORD_YEARS = 40;   // past this the labels come every 10 years, so they never touch
const MIN_GAP_YEARS = 3;        // shorter runs with no record are not worth a mention
const TYPE_KEYS = Object.freeze({ news: "history.typeNews", official: "history.typeOfficial",
  dataset: "history.typeDataset", paper: "history.typePaper" });
const CONFIDENCE_KEYS = Object.freeze({ high: "history.confidenceHigh", medium: "history.confidenceMedium",
  low: "history.confidenceLow" });

/** A flood counts as dated unless it is one person's memory or a year with no day given. */
const isDated = (flood) => !flood.account && !flood.undated;
/** Floods on the same day in different sections are one flood: they share a `date`. Older records have none. */
const dayKey = (flood, index) => flood.date ?? `#${index}`;
const distinctDays = (pairs) => new Set(pairs.map(([flood, index]) => dayKey(flood, index))).size;

/** Dated floods (an undated account or year is kept apart) and those since the area's `recent_from` year, or null
 *  when no flood record has been collected for the area or none was found in its scope. */
export function floodCounts(history) {
  if (!history?.floods?.length) return null;
  const dated = history.floods.map((flood, index) => [flood, index]).filter(([flood]) => isDated(flood));
  return {
    dated: distinctDays(dated),
    recent: distinctDays(dated.filter(([flood]) => flood.year >= history.recent_from)),
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

/** Per year: how many distinct floods, and whether every one of them is undated (a hollow dot). */
function floodsByYear(floods) {
  const byYear = new Map();
  floods.forEach((flood, index) => {
    const year = Math.floor(flood.year);
    const seen = byYear.get(year) ?? { days: new Set(), hollow: true };
    byYear.set(year, { days: seen.days.add(dayKey(flood, index)), hollow: seen.hollow && !isDated(flood) });
  });
  return byYear;
}

/** Positions are percentages and the svg has no viewBox, so text keeps its real size on a phone. */
function strip({ floods, first_year: first, last_year: last }) {
  const xOf = (year) => `${2 + ((year + 0.5 - first) / Math.max(1, last - first)) * 96}%`;
  // one dot a year, with a count, so a narrow screen never piles dots on top of each other; counts of neighbouring
  // years take turns between two rows, so "×3" and "×4" a year apart do not run into each other
  let lastCounted = -Infinity;
  let isHigh = false;
  const dots = [...floodsByYear(floods)].sort(([a], [b]) => a - b).map(([year, { days, hollow }]) => {
    const isCounted = days.size > 1;
    if (isCounted) {
      isHigh = year - lastCounted <= COUNT_GAP_YEARS ? !isHigh : false;
      lastCounted = year;
    }
    return s("g", {},
      s("circle", { class: hollow ? "flood-dot is-account" : "flood-dot", cx: xOf(year), cy: DOT_Y, r: 5 }),
      isCounted && s("text", { class: "flood-count", x: xOf(year), y: DOT_Y - (isHigh ? 21 : 9), "text-anchor": "middle" }, `×${days.size}`));
  });
  const ticks = tickYears(first, last).map((year) =>
    s("text", { x: xOf(year), y: AXIS_Y + 16, "text-anchor": "middle" }, String(year)));
  return s("svg", { class: "flood-strip", height: AXIS_Y + 22, "aria-hidden": "true" },
    s("line", { class: "axis", x1: "1%", x2: "99%", y1: AXIS_Y, y2: AXIS_Y }), ticks, dots);
}

/** True for an absolute https link with a host: the only links the list makes clickable. */
export function isHttps(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && Boolean(parsed.hostname) && !/[\s"'<>\\]/.test(url);
  } catch {
    return false;
  }
}

/** A section's name in the page's language, from the record's own section_names. */
const sectionName = (names, id) => names?.[id]?.[lang] ?? names?.[id]?.en ?? id;

function sourceLinks(sources) {
  return sources.flatMap((source, i) => [i ? "; " : "", isHttps(source.url)
    ? h("a", { href: source.url, rel: "noopener noreferrer", target: "_blank" }, source.title)
    : source.title]);
}

function tags(flood, history) {
  const types = [...new Set(flood.sources.map((source) => source.type))].filter((type) => TYPE_KEYS[type]);
  const sections = history.scope ? [] : (flood.sections ?? []).map((id) => sectionName(history.section_names, id));
  const confidence = CONFIDENCE_KEYS[flood.confidence];
  return h("span", { class: "tags" }, types.map((type) => h("span", { class: "tag" }, t(TYPE_KEYS[type]))),
    confidence && h("span", { class: "tag" }, t(confidence)), sections.map((name) => h("span", { class: "tag" }, name)));
}

/** One flood in the list. A record without per-flood sources (the areas built before sections) keeps today's line. */
function floodItem(flood, history) {
  if (!Array.isArray(flood.sources)) {
    return h("li", {}, h("strong", {}, flood.when), ` ${flood.what} `, h("span", { class: "muted" }, flood.source));
  }
  return h("li", {}, h("strong", {}, flood.when), ` ${flood.what} `,
    flood.place && h("span", { class: "muted" }, flood.place),
    flood.depth && h("span", { class: "muted" }, t("history.depth", { depth: flood.depth })),
    tags(flood, history),
    h("span", { class: "muted" }, `${t("history.sources")} `, sourceLinks(flood.sources)));
}

/** "Years with no flood record … include 1992–1994, …", or null when the record has no gaps worth naming. */
function gapsLine(history) {
  const runs = (history.gaps ?? []).filter(([from, to]) => to - from + 1 >= MIN_GAP_YEARS);
  if (!runs.length) return null;
  return h("p", { class: "fineprint history-gaps" },
    t("history.gaps", { ranges: runs.map(([from, to]) => `${from}–${to}`).join(", ") }));
}

/** Whether the record was searched for this scope (a city's, or a section's with nothing found in it): it then has a
 *  list of floods, maybe empty, and the years searched. An area never searched has no record at all. */
export const isSearched = (history) => Array.isArray(history?.floods) && Number.isInteger(history.first_year);

/** The words for "nothing here": a scope searched with nothing found, or an area never searched. */
function noneText(area, history, place) {
  if (isSearched(history)) {
    return t("history.noneFound", { area: place, from: history.first_year, to: history.last_year });
  }
  return t("history.none", { area: area.display_name });
}

/** The area's flood record in `element`, or a note that none has been collected or found. `area` is the page's area
 *  config: {name, display_name, history}; history.scope, when set, is the section the record is cut to. */
export function renderHistory(element, area) {
  const { history } = area;
  const counts = floodCounts(history);
  const heading = h("h2", { id: "history-heading" }, t("history.heading"));
  const scopeName = history?.scope ? sectionName(history.section_names, history.scope) : null;
  if (!counts) {
    element.replaceChildren(heading, h("p", { class: "history-none" }, noneText(area, history, scopeName ?? area.display_name)));
    return;
  }
  const memory = (history.floods.some((flood) => flood.account) ? t("history.memory") : "")
    + (history.floods.some((flood) => flood.undated) ? t("history.undated") : "");
  const parts = [
    heading,
    h("p", { class: "history-lead" }, h("strong", {}, t("history.leadDated", { n: counts.dated })),
      t("history.leadMid", { area: scopeName ?? area.name, since: counts.since }),
      h("strong", {}, t("history.leadRecent", { n: counts.recent, from: counts.recentFrom })), t("history.leadEnd")),
    strip(history),
    h("p", { class: "fineprint" }, t("history.mapNote", { memory })),
    gapsLine(history),
    h("details", {}, h("summary", {}, t("history.list")),   // each flood's own words are the area's data, as its sources have them
      h("ol", { class: "flood-list" }, history.floods.map((flood) => floodItem(flood, history)))),
  ];
  element.replaceChildren(...parts.filter(Boolean));
}
