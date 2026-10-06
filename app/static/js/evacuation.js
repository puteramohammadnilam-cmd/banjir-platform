// "Flood evacuation centres open now" on the Area overview: the flood centres JKM lists as open within a few km of the
// area or section on show (GET /api/evacuation; the server asks JKM's public feed at most every 5 minutes). Counts per centre,
// never a person's details. The card stays out of the page until the server has answered, and while the feed fails.
import { h } from "./dom.js";
import { dateLocale, formatNumber, t } from "./i18n.js";

const MAX_DISTRICT = 40;

/** When the feed was checked, as a Malaysian clock time ("21:05"). */
export function checkedTime(iso, locale = "en-MY") {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? "" : when.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kuala_Lumpur" });
}

/** One centre's line: its counts, how full it is when JKM says, and its district as JKM names it. */
export function centreLine(centre) {
  const counts = t("evac.counts", { people: formatNumber(centre.evacuees), families: formatNumber(centre.families) });
  const full = Number.isFinite(centre.full_pct) ? ` · ${t("evac.full", { pct: centre.full_pct })}` : "";
  const where = centre.district.slice(0, MAX_DISTRICT);
  return `${counts}${full}${where ? ` · ${where}` : ""}`;
}

function body(found) {
  const link = h("a", { href: found.source, target: "_blank", rel: "noopener noreferrer" }, t("evac.link"));
  const summary = found.count
    ? t("evac.some", { count: formatNumber(found.count), people: formatNumber(found.evacuees) })
    : t("evac.none");
  return [
    h("p", { class: "evac-summary" }, summary),
    found.centres.length > 0 && h("ul", { class: "evac-list" }, found.centres.map((centre) =>
      h("li", {}, h("strong", {}, centre.name), h("span", { class: "muted small" }, centreLine(centre))))),
    h("p", { class: "muted small" }, t("evac.nationwide", { count: formatNumber(found.open_nationwide) }), " ",
      t("evac.checked", { time: checkedTime(found.checked, dateLocale()), km: found.margin_km })),
    h("p", { class: "small" }, link),
  ].filter(Boolean);
}

/** The card in `section`; set(state) draws it from {data} (the answer's `centres`), or hides it for {busy}, {error},
 *  or a feed that is failing (data null). */
export function createEvacuation(section) {
  section.hidden = true;
  let shown;
  return {
    set(state) {
      if (state === shown) return;
      shown = state;
      const found = state?.data;
      section.hidden = !found;
      if (!found) return;
      section.replaceChildren(h("h2", { class: "small-heading", id: "evacuation-heading" }, t("evac.heading")), ...body(found));
    },
  };
}
