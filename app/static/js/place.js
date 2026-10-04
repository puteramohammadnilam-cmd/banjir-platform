// Places and links, with no DOM, so node can test them (tests/place.test.mjs). A place is a mapped business or a
// point someone picked, addressed by one id string, as in app/places.py:
//   business  "node-11075038761"       (node|way|relation)-digits: an OpenStreetMap business in a listed area
//   point     "pt:3.02998,101.53667"   the centre of the 90 m flood model square that holds the point, 5 decimals
// A link carries the area, the section of a city split into sections, tab, flood size, a business's id and the language
// (when not English) in its query. A point's id goes in the fragment
// (#place=…) and never in the query: the browser sends the query to the server, where it reaches the logs, but it
// never sends the fragment.
import { SCENARIOS } from "./dom.js";
import { LANGS } from "./i18n.js";

export const TABS = ["overview", "business", "cost"];
const BUSINESS_ID = /^(?:node|way|relation)-[0-9]{1,19}$/;
const POINT_ID = /^pt:(-?[0-9]{1,2}\.[0-9]{5}),(-?[0-9]{1,3}\.[0-9]{5})$/;
const POINT_PREFIX = "pt:";
const SECTION_ID = /^[a-z0-9][a-z0-9-]{0,59}$/;   // a section's id as its city's data writes it, such as "presint-9"
const ID_DECIMALS = 5;
const MAX_LAT = 90;
const MAX_LON = 180;

/** {kind: "business", id} or {kind: "point", id, lat, lon} for an id in exactly the server's form; else null. */
export function parseRef(ref) {
  if (typeof ref !== "string") return null;
  if (BUSINESS_ID.test(ref)) return { kind: "business", id: ref };
  const match = POINT_ID.exec(ref);
  if (!match) return null;
  const [lat, lon] = [Number(match[1]), Number(match[2])];
  if (Math.abs(lat) > MAX_LAT || Math.abs(lon) > MAX_LON) return null;
  return { kind: "point", id: ref, lat, lon };
}

/** Whether a place, or a place id, is a point rather than a mapped business. */
export function isPoint(ref) {
  if (ref !== null && typeof ref === "object") return ref.is_point === true;
  return parseRef(ref)?.kind === "point";
}

/** A square centre's id. toFixed rounds the exact number, as Python's f"{v:.5f}" does; app/places.py explains why
 *  the two never differ on a square centre of the shipped grid. */
export const pointId = (lat, lon) => `${POINT_PREFIX}${lat.toFixed(ID_DECIMALS)},${lon.toFixed(ID_DECIMALS)}`;

/** A business from an area's premises.json in the Place shape the server gives it (app/places.py resolve). */
export const businessPlace = (premise, areaId) => ({ ...premise, is_point: false, area_id: areaId, cell: null });

/** The flood model square holding (lat, lon), found exactly as app/places.py snap() finds it: the first grid, in the
 *  order GET /api/coverage lists them, where 0 <= y < rows and 0 <= x < cols. A point on a square's edge goes to the
 *  square east and south of it. {id, lat, lon, grid, row, col}, with the centre's exact lat and lon, or null where no
 *  grid holds the point. Keep the arithmetic in this order: it must match the server to the last bit. */
export function snapToGrid(lat, lon, grids) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  for (const grid of grids ?? []) {
    const y = (grid.y0 - lat) / grid.py;
    const x = (lon - grid.x0) / grid.px;
    if (!(0 <= y && y < grid.rows && 0 <= x && x < grid.cols)) continue;   // also false for a grid missing a field
    const row = Math.floor(y);
    const col = Math.floor(x);
    const centreLat = grid.y0 - (row + 0.5) * grid.py;
    const centreLon = grid.x0 + (col + 0.5) * grid.px;
    return { id: pointId(centreLat, centreLon), lat: centreLat, lon: centreLon, grid: grid.name, row, col };
  }
  return null;
}

/** [west, south, east, north], edges included. Text that looks like a number is not one: `<=` would convert it. */
const inBox = (lat, lon, box) => Number.isFinite(lat) && Number.isFinite(lon)
  && Array.isArray(box) && box.length === 4 && box[0] <= lon && lon <= box[2] && box[1] <= lat && lat <= box[3];

/** The id of the first region box (GET /api/coverage `regions`, in the order listed) that holds the spot, edges
 *  included, else null: app/places.py region_at. The boxes are coarse, as the server's are. */
export function regionAt(lat, lon, regions) {
  return (regions ?? []).find((region) => inBox(lat, lon, region?.box))?.id ?? null;
}

/** What the page knows about a spot before it asks the server, in the words of POST /api/point's answer:
 *   {coverage: "covered", region: null, square}  a loaded grid holds it; `square` is snapToGrid's. Only the server can
 *                                                say whether the square's own centre is in a region, so it has the last word;
 *   {coverage: "not_loaded", region}             no grid holds it, but a region box does (Sabah and Sarawak, Langkawi);
 *   {coverage: "outside", region: null}          no grid and no box holds it.
 *  A spot no grid holds has no square, so there is nothing the page could send for it. */
export function coverageAt(lat, lon, coverage) {
  const square = snapToGrid(lat, lon, coverage?.grids);
  if (square) return { coverage: "covered", region: null, square };
  const region = regionAt(lat, lon, coverage?.regions);
  return region ? { coverage: "not_loaded", region } : { coverage: "outside", region: null };
}

/** Whether a spot lies in an area's view, [west, south, east, north] as in area.json, edges included. */
export const isWithinView = (lat, lon, view) => inBox(lat, lon, view);

/** Whether the square with this south-west corner overlaps an area's view. The area's own squares (town.json) are every
 *  wet square that does, so a square that overlaps it must not be drawn a second time. `grid` gives the square's size in
 *  degrees: px wide, py high. Squares that only touch the view from outside do not overlap it. */
export function overlapsView(view, south, west, { px, py }) {
  return Array.isArray(view) && west < view[2] && west + px > view[0] && south < view[3] && south + py > view[1];
}

const given = (value) => value || null;   // an empty parameter counts as none
/** A section id in the form the data writes them, else null: the page puts it in an API path. */
const sectionId = (value) => (typeof value === "string" && SECTION_ID.test(value) ? value : null);
const claimsPoint = (value) => typeof value === "string" && value.startsWith(POINT_PREFIX);   // as places.is_point_id

/** What a link asks for: {area, section, place, tab, rp, lang, chat, pointInQuery}; each is null when not there. tab, rp and lang are null unless valid. chat is true for ?tab=ask, the old Ask AI tab, which is now the floating
 *  chat: it opens over the page's own tab. area and place are passed on as given, for the page to check against what this
 *  build holds. The place is the fragment's (where points go), else ?place=, else ?shop= from links made before
 *  there were points. A point is read only from the fragment: pointInQuery says the query named one (or anything
 *  starting "pt:"), which is never used, so the page can take it out of its address before it sends any request. */
export function readUrl({ search = "", hash = "" } = {}) {
  const query = new URLSearchParams(search);
  const fragment = new URLSearchParams(hash.replace(/^#/, ""));
  const named = [query.get("place"), query.get("shop")];
  const tab = query.get("tab");
  const rp = query.get("rp");
  const lang = query.get("lang");
  return {
    area: given(query.get("area")),
    section: sectionId(query.get("section")),
    place: given(fragment.get("place")) ?? given(named.find((value) => value && !claimsPoint(value))),
    tab: TABS.includes(tab) ? tab : null,
    chat: tab === "ask",
    rp: SCENARIOS.includes(rp) ? rp : null,
    lang: LANGS.includes(lang) ? lang : null,
    pointInQuery: named.some(claimsPoint),
  };
}

/** The link for a view, to pass to history.replaceState or location.assign. Area, section, tab, a business's id, rp and
 *  lang go in the query, in that order; a point's id goes in the fragment. Null values, and a place or section that is
 *  not a valid id, are left out; give area null for the default area, and section null for a whole area. */
export function writeUrl({ area = null, section = null, place = null, tab = null, rp = null, lang = null } = {}) {
  const ref = parseRef(place);
  const query = [["area", area], ["section", sectionId(section)], ["tab", tab], ["place", ref?.kind === "business" ? ref.id : null], ["rp", rp],
    ["lang", LANGS.includes(lang) ? lang : null]]
    .filter(([, value]) => value != null && value !== "")
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`);
  return `?${query.join("&")}${ref?.kind === "point" ? `#place=${ref.id}` : ""}`;
}

/** The link to another page (another area, or a section of a city: each is its own page) with or without a place on
 *  show. It has no tab, so a point handed to that page (its id only in the fragment) leaves a query no different from
 *  any other move to that page: no server log can tell a point was checked. The new page opens My business for a
 *  linked place and the Area overview otherwise (pick.js initialState). */
export const pageLink = (view) => writeUrl({ ...view, tab: null });
