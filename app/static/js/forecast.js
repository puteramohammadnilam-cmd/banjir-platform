// "River forecast" on My business: a link to Google Flood Hub's map at the place, where Google shows its AI forecast of
// river floods for the gauges it has nearby. Only a link: the Flood Forecasting API needs Google's approval first. The
// place is rounded to two decimals (about 1 km), so a point someone picked is never sent to Google exactly.
import { h } from "./dom.js";
import { factCard } from "./fact.js";
import { t } from "./i18n.js";

const ZOOM = 11;
const ROUND = 2;

/** Google Flood Hub at the place, rounded to about 1 km; null for a place with no coordinates. */
export function floodHubLink(place) {
  if (!Number.isFinite(place?.lat) || !Number.isFinite(place?.lon)) return null;
  return `https://sites.research.google/floods/l/${place.lat.toFixed(ROUND)}/${place.lon.toFixed(ROUND)}/${ZOOM}`;
}

const link = (href) => h("a", { href, target: "_blank", rel: "noopener noreferrer" }, t("forecast.link"));

/** The fact card, or null with no link to make. */
export function forecastFact(place) {
  const href = floodHubLink(place);
  return href && factCard({ iconName: "rain", label: t("forecast.label"), value: "Google Flood Hub",
    lead: h("p", { class: "fact-note" }, link(href)), more: h("p", {}, t("forecast.note")) });
}

/** The link alone, for the "Flood is coming" checklist. */
export const forecastLine = (place) => {
  const href = floodHubLink(place);
  return href && h("p", {}, t("forecast.lead"), " ", link(href));
};
