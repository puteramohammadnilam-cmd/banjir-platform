// What the page says about a point someone picked, as plain data with no DOM, so node can test the words
// (tests/point.test.mjs). A point is one 90 m square of the flood model (app/places.py), not a mapped business: it has no
// name, kind or road. It lies in a listed area (place.area_id, set by the server) or in none.

import { t } from "./i18n.js";

// In the page's language, read once: the language is chosen as the page starts (i18n.js).
export const POINT_KICKER = t("point.kicker");
export const POINT_TAGS = Object.freeze([t("point.tagSquare"), t("point.tagNotBusiness")]);
/** Under a point's "No water in the model": the model shows river floods on land, and a point can be anywhere. */
export const NO_WATER_NOTE = t("point.noWaterNote");
const UNNAMED_TITLE = t("point.unnamed");
const COORD_DECIMALS = 5;

/** The area a place lies in: the page's own, or the listed one it names. null for a point in none, and for one in an
 *  area this build does not list (or whose list did not load: `areas` may be missing or null). An area is {id, name},
 *  with display_name too where a title is made (pointHeader). */
export function areaOf(place, page, areas) {
  const id = place?.area_id;
  if (!id) return null;
  return [page, ...(areas ?? [])].find((area) => area?.id === id) ?? null;
}

const degrees = (value) => (Number.isFinite(value) ? value.toFixed(COORD_DECIMALS) : null);

/** Where a point is, for its title: its section and city (a city split into sections; the server gives the point's
 *  `section`, {id, name}), else its area. A section's page is dressed as an area (start.js pageArea): its city's own
 *  name is `city_name`. */
const placeName = (area, section) => (section ? `${section.name}, ${area.city_name ?? area.name}` : area.display_name ?? area.name);

/** The offer to open where a point lies, {kind, id, text, action}: another listed area ("area"), or in the page's own
 *  city a section other than the page's ("section"; on the whole city's page, any section). Never taken on its own:
 *  the point's section goes into a link only when the button is pressed. null when there is nothing to offer. */
function elsewhereOf(area, section, page) {
  const offer = (kind, id, name) => ({ kind, id, text: t("point.elsewhere", { area: name }), action: t("point.openArea", { area: name }) });
  if (!area) return null;
  if (area.id !== page?.id) return offer("area", area.id, area.city_name ?? area.name);
  return section && section.id !== (page.section_id ?? null) ? offer("section", section.id, section.name) : null;
}

/** The words above a point's depth. `subline` is null if the square's centre did not come as numbers. `elsewhere` is
 *  the offer for a point that lies in a listed area, or a section, other than the page's (elsewhereOf). */
export function pointHeader(place, page, areas) {
  const area = areaOf(place, page, areas);
  const section = place.section?.id ? place.section : null;
  const [lat, lon] = [degrees(place.lat), degrees(place.lon)];
  return {
    kicker: POINT_KICKER,
    title: area ? t("point.in", { area: placeName(area, section) }) : UNNAMED_TITLE,
    subline: lat !== null && lon !== null ? t("point.subline", { lat, lon }) : null,
    tags: POINT_TAGS,
    elsewhere: elsewhereOf(area, section, page),
  };
}
