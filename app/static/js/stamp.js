// Where the Area overview's figures come from, under them as the public data sites do (data.gov.my, Our World in Data):
// the model and its licence, the businesses' map and its licence, the day the flood record was checked, and how to
// cite the page. Plain text only; the area's name and the date come from its data.
import { CHANCE_YEARS, chanceWithin, h } from "./dom.js";
import { dateLocale, t } from "./i18n.js";

const DAY = { day: "numeric", month: "short", year: "numeric" };
const day = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(dateLocale(), DAY);

/** The citation for the page as it is now: the tool, the area, its address and today's date. */
export function citation(areaName, href = globalThis.location?.href ?? "", today = new Date()) {
  const link = href.split("#")[0];   // a point someone picked lives after #, and is never cited
  return t("stamp.citeText", { year: today.getFullYear(), area: areaName, link, date: today.toLocaleDateString(dateLocale(), DAY) });   // the reader's own day, not UTC's
}

/** Fill `node` with the source line and a fold holding the citation. */
export function renderStamp(node, { history, areaName }) {
  const checked = history?.checked ? t("stamp.checked", { date: day(history.checked) }) : "";
  node.replaceChildren(
    h("p", {}, t("stamp.source"), checked),
    h("details", { class: "stamp-cite" }, h("summary", {}, t("stamp.cite")), h("p", { class: "fineprint" }, citation(areaName))));
}

/** "Showing a flood expected once in 50 years: an 18% chance of at least one this big in the next 10 years." */
export const scenarioSentence = (rp) =>
  t("overview.scenarioSentence", { rp, pct: Math.round(chanceWithin(Number(rp), CHANCE_YEARS) * 100), years: CHANCE_YEARS });
