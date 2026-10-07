// "River gauge" on My business, and a line in the flood checklist: the nearest JPS river level gauge to the place (the
// server finds it, app/gauges.py) and a link to its live 7-day river level graph on JPS Public Infobanjir. Only the name
// and place of the gauge are ours to show; its readings stay on JPS's site.
import { h } from "./dom.js";
import { distanceText, factCard } from "./fact.js";
import { t } from "./i18n.js";

const GRAPH = "https://publicinfobanjir.water.gov.my/wl-graph/?stationid=";

/** JPS's live 7-day river level graph for the gauge. */
export const graphLink = (gauge) => GRAPH + encodeURIComponent(gauge.id);

const link = (gauge) => h("a", { href: graphLink(gauge), target: "_blank", rel: "noopener noreferrer" }, t("river.link"));

const where = (gauge) => (gauge.river ? t("river.whereRiver", { distance: distanceText(gauge.distance_m), river: gauge.river })
  : t("river.where", { distance: distanceText(gauge.distance_m) }));

/** The fact card, or null for a place with no gauge within reach. */
export function gaugeFact(place) {
  const gauge = place?.gauge;
  return gauge && factCard({ iconName: "wave", label: t("river.label"), value: gauge.name,
    lead: h("p", { class: "fact-note" }, where(gauge), " ", link(gauge)), more: h("p", {}, t("river.note")) });
}

/** The checklist's line: watch the river at the nearest gauge. */
export function gaugeLine(place) {
  const gauge = place?.gauge;
  return gauge && h("p", {}, t("river.watch", { name: gauge.name, distance: distanceText(gauge.distance_m) }), " ", link(gauge));
}
