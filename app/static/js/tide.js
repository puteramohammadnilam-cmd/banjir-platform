// "Tide at <station>" on the Area overview, for an area whose river is tidal (GET /api/tide; the server keeps a table of
// predicted highs and lows built from a public tide-gauge record). Today's high tides, whether today is a big (spring)
// tide, and why it matters: heavy rain near high tide drains more slowly. The card stays out until the server answers,
// and for an area with no tide table.
import { h } from "./dom.js";
import { t } from "./i18n.js";

/** "03:18 and 15:48" in the page's language. */
export const timesText = (times) => (times.length > 1 ? t("tide.and", { first: times.slice(0, -1).join(", "), last: times.at(-1) }) : times[0] ?? "");

function body(found) {
  const next = found.next_high && t("tide.next", { time: found.next_high.time, day: t(found.next_high.tomorrow ? "tide.tomorrow" : "tide.today") });
  return [
    found.highs.length > 0 && h("p", { class: "tide-highs" }, t("tide.highs", { times: timesText(found.highs) })),
    next && h("p", {}, next),
    h("p", { class: found.big ? "tide-big" : "" }, t(found.big ? "tide.big" : "tide.ordinary", { range: found.range_m })),
    h("p", { class: "muted small" }, t("tide.why")),
    h("p", { class: "fineprint" }, t("tide.source", { error: found.typical_error_m, station: found.station })),
  ].filter(Boolean);
}

/** The card in `section`; set(state) draws it from {data} (the answer's `tide`), or hides it for {busy}, {error} or
 *  an area without a tide table (data null). */
export function createTide(section) {
  section.hidden = true;
  let shown;
  return {
    set(state) {
      if (state === shown) return;
      shown = state;
      const found = state?.data;
      section.hidden = !found;
      if (!found) return;
      section.replaceChildren(h("h2", { class: "small-heading", id: "tide-heading" }, t("tide.heading", { station: found.station })), ...body(found));
    },
  };
}
