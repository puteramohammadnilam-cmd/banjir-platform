// The new map's data work, with no DOM and no MapLibre, so node can test it (tests/map-gl.test.mjs): the area's and a
// section's data turned into GeoJSON, the paint rules that follow the flood size and the theme, where our water goes
// in a base map's layers, the place card's badge and the nearest relief centre. map-gl.js draws with them.
// Look and layering adapted from Arus by Farhan Syah (MIT, vendor/LICENSE-arus.txt).
import { ADULT_M, COUNTER_M, SCENARIOS, band } from "./dom.js";
import { readUrl } from "./place.js";

export const BASEMAPS = ["map", "sat", "dark"];
export const STYLE_FILES = { map: "vendor/openfreemap/positron.json", dark: "vendor/openfreemap/dark.json" };
const NO_DEPTH = -1;   // GeoJSON has no null in a paint rule: dry squares and shops carry -1
// the badge's tone for each of the main page's depth bands (dom.js BANDS): up to the counter, over it, over a head...
const BAND_TONES = ["watch", "high", "deep", "deep", "deep"];
const EARTH_KM = 6371;
export const SHELTER_REACH_KM = 15;   // app/places.py SHELTER_REACH_M: a centre farther is not offered (tests hold them equal)
// the first base-map layer our water goes under: buildings, roads and every name stay drawn over it (Arus,
// findFloodInsertBeforeId)
const OVER_WATER = /^(building|tunnel|road|highway|bridge|railway|aeroway|transportation)/i;

/** The link's view: area, section, place, flood size and language as the main page reads them, plus the base map and
 *  whether to start tilted. */
export function readMapLink(search = "", hash = "") {
  const link = readUrl({ search, hash });
  const query = new URLSearchParams(search);
  const base = query.get("base");
  return { ...link, rp: link.rp ?? "50", base: BASEMAPS.includes(base) ? base : "map", tilt: query.get("tilt") === "1" };
}

/** The data the map opens on, and its link: an old area id that is now one of an area's sections (an alias, such as
 *  sri-muda or kota-tinggi) is answered with that section's page, so the whole area is asked for instead and the link
 *  opens on the section (the link's own section, if it names one, still wins). */
export async function areaForLink(link, { getAreaData, getDefaultData }) {
  const found = link.area ? await getAreaData(link.area) : await getDefaultData();
  if (!found.section) return { data: found, link };
  return { data: await getAreaData(found.area.id), link: { ...link, area: found.area.id, section: link.section ?? found.section.id } };
}

/** This map's own link: the main page's (place.js writeUrl), then the base map and the tilt. A point stays in the
 *  fragment, last, where the browser never sends it to the server. */
export function withMapView(link, base, tilt) {
  const [query, fragment] = link.split("#");
  const more = [base === "map" ? null : `base=${base}`, tilt ? "tilt=1" : null].filter(Boolean).join("&");
  const full = more ? `${query}${query.length > 1 ? "&" : ""}${more}` : query;
  return fragment ? `${full}#${fragment}` : full;
}

const depthOrNone = (value) => (typeof value === "number" && Number.isFinite(value) ? value : NO_DEPTH);
const byFloodSize = (prefix, values) => Object.fromEntries(SCENARIOS.map((rp) => [`${prefix}${rp}`, values(rp)]));

/** The area's sections, each with its share of wet squares (s10, s20, s50) and its wet businesses (w10, w20, w50). */
export function sectionsGeo(sections) {
  const share = (counts, rp) => (counts.cells ? counts.wet_cells[rp] / counts.cells : 0);
  return {
    type: "FeatureCollection",
    features: sections.filter((s) => s.outline).map((s) => ({
      type: "Feature",
      properties: { id: s.id, name: s.name, n: s.counts.businesses, ...byFloodSize("s", (rp) => share(s.counts, rp)),
        ...byFloodSize("w", (rp) => s.counts.wet_businesses[rp] ?? 0) },
      geometry: s.outline,
    })),
  };
}

const box = (west, south, east, north) => ({ type: "Polygon", coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] });

/** The flood model's squares, [south, west, depth 1 in 10, 1 in 20, 1 in 50] each, as polygons `size` degrees across
 *  and `tall` degrees high (the same, for the areas' own grids). */
export function squaresGeo(cells, size, tall = size) {
  return {
    type: "FeatureCollection",
    features: cells.map(([south, west, ...depths]) => ({
      type: "Feature",
      properties: byFloodSize("d", (rp) => depthOrNone(depths[SCENARIOS.indexOf(rp)])),
      geometry: box(west, south, west + size, south + tall),
    })),
  };
}

/** A checked point's own square, its outline from the Place's `cell.bounds` ([west, south, east, north]). */
export const squareOutline = (bounds) => ({ type: "Feature", properties: {}, geometry: box(...bounds) });

/** The shops, each a point with its door's depth for each flood size. */
export function shopsGeo(premises) {
  return {
    type: "FeatureCollection",
    features: premises.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon)).map((p) => ({
      type: "Feature",
      properties: { id: p.id, ...byFloodSize("d", (rp) => depthOrNone(p.depth_m?.[rp])) },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })),
  };
}

/** The squares' colour for a flood size: darker is deeper on the light map, brighter is deeper on the dark ones. */
export function depthRamp(rp, isDark) {
  const steps = isDark
    ? ["#1a6aa8", 0.5, "#2f9be0", 1, "#62c3f5", 2, "#a8e2ff", 3, "#e6f7ff"]
    : ["#a9d8ff", 0.5, "#6cb8f0", 1, "#2f86d6", 2, "#1d5fae", 3, "#0b3478"];
  return ["step", ["get", `d${rp}`], "rgba(0,0,0,0)", 0, ...steps];
}

/** A shop's dot: grey when the model keeps it dry, then yellow up to counter height, orange over the counter and red
 *  over an adult's head, the main page's depth bands (dom.js). */
export const shopColour = (rp) => ["step", ["get", `d${rp}`], "#94a3b8", 0, "#eab308", COUNTER_M, "#f97316", ADULT_M, "#e11d48"];

/** A section's shading by its share of wet squares, as the main page's choropleth bands it. */
export const sectionFill = (rp) => ["step", ["get", `s${rp}`], "rgba(0,0,0,0)", 0.0001, "#93c5fd", 0.05, "#60a5fa",
  0.15, "#3b82f6", 0.3, "#2563eb", 0.5, "#1e40af"];

/** The id of the base-map layer our water goes under, from a style's layers in drawing order; undefined puts it on top. */
export function underRoads(layers = []) {
  return (layers.find((layer) => OVER_WATER.test(layer.id)) ?? layers.find((layer) => layer.type === "symbol"))?.id;
}

/** The place card's badge for the water at a door: its tone and its words' key, the main page's band words. */
export function badge(depth) {
  const n = band(depth);
  return n ? { tone: BAND_TONES[n - 1], key: `band.${n}.words` } : { tone: "dry", key: "mg.badge.dry" };
}

/** Great-circle distance in km between two {lat, lon}. */
export function distanceKm(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.sqrt(h));
}

/** The relief centre nearest a place, {shelter, km}, or null with none listed. */
export function nearestShelter(place, shelters = []) {
  const best = shelters.reduce((found, shelter) => {
    const km = distanceKm(place, shelter);
    return !found || km < found.km ? { shelter, km } : found;
  }, null);
  return best && best.km <= SHELTER_REACH_KM ? best : null;   // a state lists only a town's few
}

/** Up to `limit` businesses in the area's index whose name holds the words typed, in the index's order. */
export function searchIndex(index, words, limit = 6) {
  const wanted = words.trim().toLowerCase();
  if (wanted.length < 2) return [];
  return index.filter((entry) => entry.name?.toLowerCase().includes(wanted)).slice(0, limit);
}

/** Shops with water at the door in the model for a flood size: an area with no sections counts its shops itself. */
export const wetShops = (premises, rp) => premises.filter((p) => band(p.depth_m?.[rp]) > 0).length;

/** Wet businesses across the area for a flood size, and all of them. */
export function wetTotals(sections, rp) {
  return sections.reduce((sum, s) => ({ wet: sum.wet + (s.counts.wet_businesses[rp] ?? 0), all: sum.all + s.counts.businesses }),
    { wet: 0, all: 0 });
}

/** Up to `limit` sections a search could mean, from pick.js sectionFinder's {entries, synonyms}: a section's other name
 *  or the area's word for a section typed in full first, then names holding the words typed (the name only, not the
 *  city or section after its " · ": the city's name is not every section); each section once. */
export function searchSections(finder, words, limit = 3) {
  const wanted = words.trim().toLowerCase();
  if (!finder || wanted.length < 2) return [];
  const exact = finder.synonyms.get(wanted);
  const hits = finder.entries.filter(([text]) => text.split(" · ")[0].toLowerCase().includes(wanted)).map(([text, { section }]) => ({ text, section }));
  const seen = new Set();
  return [...(exact ? [{ text: null, section: exact.section }] : []), ...hits]
    .filter((hit) => !seen.has(hit.section) && seen.add(hit.section)).slice(0, limit);
}
