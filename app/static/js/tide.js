// "Tide at <station>" on the Area overview, for an area whose river is tidal (GET /api/tide; the server keeps a table of
// predicted highs and lows built from a public tide-gauge record). Today's high tides, whether today is a big (spring)
// tide, and why it matters: heavy rain near high tide drains more slowly. The card stays out until the server answers,
// and for an area with no tide table.
import { h } from "./dom.js";
import { dateLocale, t } from "./i18n.js";

/** "03:18 and 15:48" in the page's language. */
export const timesText = (times) => (times.length > 1 ? t("tide.and", { first: times.slice(0, -1).join(", "), last: times.at(-1) }) : times[0] ?? "");

/** Today's date in Malaysia, "YYYY-MM-DD". */
export const malaysiaToday = (now = new Date()) => now.toLocaleDateString("en-CA", { timeZone: "Asia/Kuala_Lumpur" });

/** The tide answer when it is still today's, else null: a page left open past midnight must not show yesterday's tides. */
export const current = (found, now = new Date()) => (found && found.date === malaysiaToday(now) ? found : null);

/** "9 Oct": a Malaysian date, as the page's language writes it. */
export const dayText = (iso, locale = dateLocale()) =>
  new Date(`${iso}T12:00:00+08:00`).toLocaleDateString(locale, { day: "numeric", month: "short", timeZone: "Asia/Kuala_Lumpur" });

/** The next run of big tides: until when, if it has begun; else from and to. */
export function outlookText(found) {
  const run = found.next_big;
  if (!run) return null;
  if (run.from === found.date) return t("tide.bigUntil", { to: dayText(run.to) });
  return run.from === run.to ? t("tide.bigNextOne", { from: dayText(run.from) }) : t("tide.bigNext", { from: dayText(run.from), to: dayText(run.to) });
}

/** The flood checklist's line: today's high tides, or null for a place with no tide table. */
export const tideLine = (found) => found?.highs?.length > 0
  && h("p", {}, t("tide.checklist", { station: found.station, times: timesText(found.highs) }));

function body(found) {
  const outlook = outlookText(found);
  const next = found.next_high && t("tide.next", { time: found.next_high.time, day: t(found.next_high.tomorrow ? "tide.tomorrow" : "tide.today") });
  return [
    found.highs.length > 0 && h("p", { class: "tide-highs" }, t("tide.highs", { times: timesText(found.highs) })),
    next && h("p", {}, next),
    h("p", { class: found.big ? "tide-big" : "" }, t(found.big ? "tide.big" : "tide.ordinary", { range: found.range_m })),
    outlook && h("p", {}, outlook),
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
      const found = current(state?.data);
      section.hidden = !found;
      if (!found) return;
      section.replaceChildren(h("h2", { class: "small-heading", id: "tide-heading" }, t("tide.heading", { station: found.station })), ...body(found));
    },
  };
}
