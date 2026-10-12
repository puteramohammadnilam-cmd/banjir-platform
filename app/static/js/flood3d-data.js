// The 3D page's data, with no DOM or map, so node can test it (tests/flood3d.test.mjs): what a link asks for, where
// its shop is, and its section's bundle turned into what the map draws. tools/build_flood3d.py bakes one bundle per
// section of a city into flood3d/<area id>/<section id>.json:
//   box             [west, south, east, north]: the section's box and 300 m around it
//   origin          [lon0, lat0]
//   buildings       [[h, src, x1, y1, x2, y2, ...], ...]: h metres; src 0 OpenStreetMap, 1 Google, 2 guessed; each
//                   vertex lon0 + x / 1e6, lat0 + y / 1e6; the outer ring, its first point not repeated at the end
//   cell_deg, return_periods, water [[south, west, d10, d20, d50], ...]: the flood model's wet squares, cell_deg a side
//   credit, fetched_on
import { SCENARIOS } from "./dom.js";

export const VIEW_RADIUS_M = 450;   // what the tilted view shows around the shop: the rest of the section is left out
export const NEAR_M = 30;           // tools/build_flood3d.py: a shop mapped as a dot just outside its building's outline
// ponytail: a bare 3d.html still opens the first shop baked, a 7-Eleven, as the mock-up did; drop it once the card's
// link is the only way in.
export const DEFAULT_PLACE = "node-5565878632";
const PLACE_ID = /^(node|way|relation)-\d{1,15}$/;
const SCOPE_ID = /^[a-z0-9][a-z0-9-]{0,59}$/;   // an area's or a section's id, as place.js takes a section's
const METRES_PER_DEG = 111_320;
const MICRO = 1e6;
const SOURCES = ["osm", "google", "guess"];
const GUESSED = 2;
const DRY = Object.freeze(Object.fromEntries(SCENARIOS.map((rp) => [`d${rp}`, 0])));
// 0.002 of a square (about 17 cm): more than two corners written to 6 decimals can stray apart (1e-6 degrees, 0.0012
// of a square), so a point on a written corner lands in that corner's square, not the one south or west of it.
const SNAP = 0.002;

/** What a 3D link asks for: {area, section, place, rp}. area and section are null when missing or not an id; place
 *  is DEFAULT_PLACE when missing and null when not a business id; rp is null unless one of the flood sizes. The first
 *  links (?place= alone) name no section: findShop looks it up. */
export function readLink(search) {
  const query = new URLSearchParams(search);
  const id = (name, pattern) => (pattern.test(query.get(name) ?? "") ? query.get(name) : null);
  const rp = query.get("rp");
  return { area: id("area", SCOPE_ID), section: id("section", SCOPE_ID),
    place: query.get("place") === null ? DEFAULT_PLACE : id("place", PLACE_ID), rp: SCENARIOS.includes(rp) ? rp : null };
}

/** Whether a string is an area's or a section's id, safe in a path: the server's are checked too, before use. */
export const isScopeId = (value) => typeof value === "string" && SCOPE_ID.test(value);

/** A section's data (GET /api/areas/{area}/sections/{section}/data) for the link: the section it names, else the one
 *  its area's data (else the default area's) puts the shop in (the city's `index`; an old area id's data is its
 *  section's already). null when no section holds the shop. */
async function sectionData(link, api) {
  if (link.section) return api.getSectionData(link.area ?? (await api.getAreas()).default, link.section);
  const whole = await (link.area ? api.getAreaData(link.area) : api.getDefaultData());
  if (whole.section) return whole;
  const section = (whole.index ?? []).find((row) => row.id === link.place)?.section;
  return section ? api.getSectionData(whole.area.id, section) : null;
}

/** The link's shop and where it is: {areaId, sectionId, sectionName, shop}, the shop as the section's data has it
 *  (name, kind, lat, lon, depth_m). null when the server holds no such shop; throws (api.js ApiError) when it could
 *  not be asked or names no such area or section. */
export async function findShop(link, api) {
  if (!link.place) return null;
  const data = await sectionData(link, api);
  const shop = data?.premises?.find((premise) => premise.id === link.place);
  if (!shop || !isScopeId(data.area?.id) || !isScopeId(data.section?.id)) return null;
  return { areaId: data.area.id, sectionId: data.section.id, sectionName: data.section.name, shop };
}

/** Whether a fetched bundle has the parts the page reads (it is the server's own file, but a half-written one or an
 *  error page must not break the map). */
export const isBundle = (doc) => doc?.version === 1 && Array.isArray(doc.origin) && doc.origin.length === 2
  && doc.origin.every(Number.isFinite) && Array.isArray(doc.buildings) && Array.isArray(doc.water) && doc.cell_deg > 0;

/** Metres between two [lon, lat] points, on a flat local grid (fine over the few hundred metres of one view). */
export function metresApart([lon1, lat1], [lon2, lat2]) {
  const xScale = METRES_PER_DEG * Math.cos((lat1 * Math.PI) / 180);
  return Math.hypot((lon2 - lon1) * xScale, (lat2 - lat1) * METRES_PER_DEG);
}

/** The bundle's buildings as {h, src, ring}, the ring [lon, lat] points closed (its first point again at the end). A
 *  row with no positive height, or too few whole points for a triangle, is left out. */
export function decodeBuildings({ origin, buildings }) {
  const [lon0, lat0] = origin;
  return (buildings ?? [])
    .filter(([h, , ...xy]) => Number.isFinite(h) && h > 0 && xy.length >= 6 && xy.length % 2 === 0)
    .map(([h, src, ...xy]) => {
      const ring = Array.from({ length: xy.length / 2 }, (_, i) => [lon0 + xy[2 * i] / MICRO, lat0 + xy[2 * i + 1] / MICRO]);
      return { h, src, ring: [...ring, ring[0]] };
    });
}

/** The middle of a closed ring: the average of its points, the closing one left out, as tools/build_flood3d.py. */
export function middle(ring) {
  const points = ring.slice(0, -1);
  return [0, 1].map((axis) => points.reduce((sum, point) => sum + point[axis], 0) / points.length);
}

/** A wet square's depths by flood size, {d10, d20, d50}: 0 for a size it has no number for. */
function depthsOf(row, periods) {
  const at = (rp) => periods.indexOf(rp);
  return Object.fromEntries(SCENARIOS.map((rp) => {
    const depth = at(rp) < 0 ? null : row[2 + at(rp)];
    return [`d${rp}`, Number.isFinite(depth) ? depth : 0];
  }));
}

/** The bundle's wet squares by grid cell (row north, column east of the first square), to find the one under a point.
 *  Every corner lies a whole number of squares from the first square's, to the decimals it is written in: rounded,
 *  not floored, as 4.9999 squares is the fifth. */
export function waterGrid({ cell_deg: size, return_periods: returnPeriods, water }) {
  const rows = (water ?? []).filter((row) => Number.isFinite(row[0]) && Number.isFinite(row[1]));
  if (!rows.length || !(size > 0)) return { size, cells: new Map() };
  const [south0, west0] = rows[0];
  const periods = (returnPeriods ?? []).map(String);
  const key = ([south, west]) => `${Math.round((south - south0) / size)},${Math.round((west - west0) / size)}`;
  return { size, south0, west0, cells: new Map(rows.map((row) => [key(row), depthsOf(row, periods)])) };
}

/** The depths ({d10, d20, d50}) of the wet square under (lon, lat), all 0 where there is none. A square holds its south
 *  and west edges, as tools/build_flood3d.py contains has it; the squares tile the map with no gap and no overlap, their
 *  edges within SNAP of the written ones. */
export function depthsAt(grid, lon, lat) {
  if (!grid.cells.size) return DRY;
  const row = Math.floor((lat - grid.south0) / grid.size + SNAP);
  const col = Math.floor((lon - grid.west0) / grid.size + SNAP);
  return grid.cells.get(`${row},${col}`) ?? DRY;
}

/** Ray casting: whether (lon, lat) falls inside the closed ring of [lon, lat] points (tools/build_flood3d.py). */
export function contains(ring, lon, lat) {
  let inside = false;
  for (let i = 1; i < ring.length; i += 1) {
    const [[x1, y1], [x2, y2]] = [ring[i - 1], ring[i]];
    if ((y1 > lat) !== (y2 > lat) && lon < x1 + ((lat - y1) * (x2 - x1)) / (y2 - y1)) inside = !inside;
  }
  return inside;
}

/** Metres from (lon, lat) to the nearest wall of the closed ring, on a flat local grid (tools/build_flood3d.py). */
export function metresToRing(ring, lon, lat) {
  const xScale = METRES_PER_DEG * Math.cos((lat * Math.PI) / 180);
  const points = ring.map(([x, y]) => [(x - lon) * xScale, (y - lat) * METRES_PER_DEG]);
  let nearest = Infinity;
  for (let i = 1; i < points.length; i += 1) {
    const [[x1, y1], [x2, y2]] = [points[i - 1], points[i]];
    const length2 = (x2 - x1) ** 2 + (y2 - y1) ** 2;
    const share = length2 === 0 ? 0 : Math.max(0, Math.min(1, -(x1 * (x2 - x1) + y1 * (y2 - y1)) / length2));
    nearest = Math.min(nearest, Math.hypot(x1 + share * (x2 - x1), y1 + share * (y2 - y1)));
  }
  return nearest;
}

/** Index of the ring the shop stands in, else of the ring with a wall nearest it within NEAR_M (the first of equals),
 *  else null: tools/build_flood3d.py shop_building, its (lat, lon) order kept. */
export function shopBuilding(rings, lat, lon) {
  const inside = rings.findIndex((ring) => contains(ring, lon, lat));
  if (inside >= 0) return inside;
  const nearest = rings.reduce((best, ring, i) => {
    const metres = metresToRing(ring, lon, lat);
    return metres <= NEAR_M && (best === null || metres < best.metres) ? { metres, i } : best;
  }, null);
  return nearest?.i ?? null;
}

/** Metres from the shop to the nearest point of the square with this south-west corner. */
function metresToSquare(shopAt, south, west, size) {
  const [lon, lat] = shopAt;
  const clamp = (value, low) => Math.min(Math.max(value, low), low + size);
  return metresApart(shopAt, [clamp(lon, west), clamp(lat, south)]);
}

const polygon = (ring, properties) => ({ type: "Feature", properties, geometry: { type: "Polygon", coordinates: [ring] } });
const collection = (features) => ({ type: "FeatureCollection", features });

/** The wet squares that reach within `radius` metres of the shop, as GeoJSON with their depths, for the water layer. */
function waterNear(bundle, shopAt, radius) {
  const size = bundle.cell_deg;
  const periods = (bundle.return_periods ?? []).map(String);
  return (bundle.water ?? [])
    .filter(([south, west]) => Number.isFinite(south) && Number.isFinite(west) && metresToSquare(shopAt, south, west, size) <= radius)
    .map((row) => {
      const [south, west] = row;
      const [north, east] = [south + size, west + size];
      return polygon([[west, south], [east, south], [east, north], [west, north], [west, south]], depthsOf(row, periods));
    });
}

/** What the map draws around a shop ({lat, lon, depth_m}) from its section's bundle: the buildings whose middles are
 *  within `radius` metres, each with h, hsrc, guessed, shop and the depths of the wet square under its middle, and the
 *  wet squares that reach within it. The shop's building takes the shop's own depths, the ones the panel states.
 *  `hasShopBuilding` says whether one was found. */
export function scene(bundle, shop, radius = VIEW_RADIUS_M) {
  const shopAt = [shop.lon, shop.lat];
  const grid = waterGrid(bundle);
  const near = decodeBuildings(bundle).map((building) => ({ ...building, at: middle(building.ring) }))
    .filter((building) => metresApart(shopAt, building.at) <= radius);
  const own = shopBuilding(near.map((building) => building.ring), shop.lat, shop.lon);
  const ownDepths = Object.fromEntries(SCENARIOS.map((rp) => [`d${rp}`, shop.depth_m?.[rp] ?? 0]));
  const buildings = near.map(({ h, src, ring, at }, i) => polygon(ring, {
    h, hsrc: SOURCES[src] ?? null, guessed: src === GUESSED, shop: i === own,
    ...(i === own ? ownDepths : depthsAt(grid, at[0], at[1])),
  }));
  return { buildings: collection(buildings), water: collection(waterNear(bundle, shopAt, radius)), hasShopBuilding: own !== null };
}
