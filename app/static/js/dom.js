// Small DOM helpers. Text goes in through textContent only, so nothing is parsed as HTML.
import { dateLocale, numberLocale, t } from "./i18n.js";
const SVG_NS = "http://www.w3.org/2000/svg";

function fill(node, attrs, children) {
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child != null && child !== false) node.append(child);
  }
  return node;
}

export const h = (tag, attrs = {}, ...children) => fill(document.createElement(tag), attrs, children);
export const s = (tag, attrs = {}, ...children) => fill(document.createElementNS(SVG_NS, tag), attrs, children);

export const SCENARIOS = ["10", "20", "50"];   // app/raster.py RETURN_PERIODS: the flood sizes the data holds
/** "once in 50 years": a flood size in words, for "in a flood expected …". */
export const scenarioLabel = (rp) => t("scenario.label", { rp });

// Things a shop owner can picture, at typical heights: a counter, an adult, a door, a storey. Same colours as tokens.css
// (water-blue, then indigo and plum for the two deepest, so each class reads apart from its neighbours).
export const ADULT_M = 1.65;
export const COUNTER_M = 0.9;
export const DOOR_M = 2.1;
/** A depth band: water shallower than `below` metres, its colour and its words in the page's language. */
const bandEntry = (n, below, color) => ({ below, color, words: t(`band.${n}.words`), range: t(`band.${n}.range`) });
export const BANDS = [
  bandEntry(1, COUNTER_M, "#c2e6f5"),
  bandEntry(2, ADULT_M, "#6fb3dc"),
  bandEntry(3, DOOR_M, "#2b77a7"),
  bandEntry(4, 3, "#3b3fbd"),
  bandEntry(5, Infinity, "#5a1170"),
];
export const DRY_COLOR = "#fbf8f1";

/** 0 = dry, 1..5 = depth band, shallow to deep. */
export function band(depth) {
  if (depth == null || depth <= 0) return 0;
  return BANDS.findIndex((b) => depth < b.below) + 1;
}

export const bandColor = (depth) => BANDS[band(depth) - 1]?.color ?? DRY_COLOR;

const WORDS = [[0.15, "depth.ankle"], [0.5, "depth.knee"], [COUNTER_M, "depth.waist"], [1.3, "depth.chest"],
  [ADULT_M, "depth.neck"], [DOOR_M, "depth.overHead"], [3, "depth.overDoor"], [Infinity, "depth.storey"]];

/** Plain words for a depth, for an adult about 1.65 m tall. */
export function depthWords(depth) {
  if (!band(depth)) return t("common.noWater");
  return t(WORDS.find(([below]) => depth < below)[1]);
}

/** Chance of at least one flood this size within `years`, for a flood expected once in `returnPeriod` years. */
export const chanceWithin = (returnPeriod, years) => 1 - (1 - 1 / returnPeriod) ** years;

export const depthText = (depth) => (band(depth) ? t("common.metres", { m: depth.toFixed(2) }) : t("common.noWater"));

/** An icon from the sprite in index.html. Decorative, so screen readers skip it. */
export const icon = (name) => s("svg", { class: "icon", "aria-hidden": "true" }, s("use", { href: `#i-${name}` }));

export const CHANCE_YEARS = 10;   // about one shop lease

/** The three flood sizes as one control, each with its chance of happening at least once in CHANCE_YEARS. */
export function scenarioPicker(rp, onPick) {
  return h("div", { class: "scenario", role: "group", "aria-label": t("scenario.group") },
    SCENARIOS.map((key) => {
      const chance = t("scenario.chance", { pct: Math.round(chanceWithin(Number(key), CHANCE_YEARS) * 100), years: CHANCE_YEARS });
      return h("button", { type: "button", "aria-pressed": String(key === rp), "aria-label": t("scenario.option", { rp: key, chance }), onclick: () => onPick(key) },
        t("common.rpYears", { rp: key }), h("span", { class: "chance" }, chance));
    }));
}

/** The month of a past flood ("2021-12"), written in the page's language: "December 2021", "Disember 2021". */
const monthText = (month) => new Date(`${month}-01T00:00:00`).toLocaleDateString(dateLocale(), { month: "long", year: "numeric" });

/** "Floods bigger than 1 in 50 years are not shown", with the area's own example of one (area.json
 *  bigger_flood_example, a month such as "2021-12") when it names one. */
const notShown = (example) => h("p", { class: "scenario-note" }, example
  ? t("scenario.notShownSuch", { rp: SCENARIOS.at(-1), when: monthText(example) })
  : t("scenario.notShown", { rp: SCENARIOS.at(-1) }));

/** Put a fresh picker in `slot`, and the note on floods bigger than it offers, keeping keyboard focus on the chosen size
 *  if the old picker had it. */
export function renderPicker(slot, rp, onPick, example = null) {
  const hadFocus = slot.contains(document.activeElement);
  slot.replaceChildren(scenarioPicker(rp, onPick), notShown(example));
  if (hadFocus) slot.querySelector('[aria-pressed="true"]')?.focus();
}

const RINGGIT = new Map();   // one formatter per locale, made when first needed
/** Ringgit with no sen, grouped as the page's language groups numbers ("RM 50,000"). */
export function ringgit(value) {
  const locale = numberLocale();
  if (!RINGGIT.has(locale)) RINGGIT.set(locale, new Intl.NumberFormat(locale, { style: "currency", currency: "MYR", maximumFractionDigits: 0 }));
  return RINGGIT.get(locale).format(value);
}

/** What tools/build_area.py names a road with no name, in the data; shown in the page's language. */
export const UNNAMED_ROAD = "a road with no name";
export const roadName = (name) => (name === UNNAMED_ROAD ? t("common.unnamedRoad") : name);

/** "Shop · convenience": the kind is OpenStreetMap's own tag, in English, as the map has it. */
export const kindText = (premise) => `${t(premise.sector === "eatery" ? "kind.eatery" : "kind.shop")}${premise.kind ? ` · ${premise.kind.replaceAll("_", " ")}` : ""}`;
