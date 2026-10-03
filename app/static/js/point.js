// What the page says about a point someone picked, as plain data with no DOM, so node can test the words
// (tests/point.test.mjs). A point is one 90 m square of the flood model (app/places.py), not a mapped business: it has no
// name, kind or road. It lies in a listed area (place.area_id, set by the server) or in none.

export const POINT_KICKER = "A point you picked";
export const POINT_TAGS = Object.freeze(["90 m model square", "Not a mapped business"]);
/** Under a point's "No water in the model": the model shows river floods on land, and a point can be anywhere. */
export const NO_WATER_NOTE = "The model maps river floods on land. It does not show flash floods, blocked drains or the sea.";
const UNNAMED_TITLE = "Point you picked";
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

/** The words above a point's depth. `subline` is null if the square's centre did not come as numbers. `elsewhere` is
 *  the offer for a point that lies in a listed area other than the page's: where it is, and how to open that area; null
 *  when there is nothing to offer. */
export function pointHeader(place, page, areas) {
  const area = areaOf(place, page, areas);
  const [lat, lon] = [degrees(place.lat), degrees(place.lon)];
  const isElsewhere = area !== null && area.id !== page?.id;
  return {
    kicker: POINT_KICKER,
    title: area ? `Point in ${area.display_name ?? area.name}` : UNNAMED_TITLE,
    subline: lat !== null && lon !== null ? `The 90 m flood square at ${lat}, ${lon}` : null,
    tags: POINT_TAGS,
    elsewhere: isElsewhere ? { id: area.id, text: `This point is in ${area.name}.`, action: `Open ${area.name}` } : null,
  };
}
