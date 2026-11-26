// The new map's data work, with no DOM and no MapLibre, so node can test it (tests/map-gl.test.mjs): the area's and a
// section's data turned into GeoJSON, the paint rules that follow the flood size and the theme, where our water goes
// in a base map's layers, the place card's badge and the nearest relief centre. map-gl.js draws with them.
// Look and layering adapted from Arus by Farhan Syah (MIT, vendor/LICENSE-arus.txt).
import { SCENARIOS } from "./dom.js";
import { readUrl } from "./place.js";

export const BASEMAPS = ["map", "sat", "dark"];
export const STYLE_FILES = { map: "vendor/openfreemap/positron.json", dark: "vendor/openfreemap/dark.json" };
const NO_DEPTH = -1;   // GeoJSON has no null in a paint rule: dry squares and shops carry -1
const SHALLOW_M = 0.3;
const DEEP_M = 1;
const EARTH_KM = 6371;
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

/** The flood model's squares, [south, west, depth 1 in 10, 1 in 20, 1 in 50] each, as square polygons. */
export function squaresGeo(cells, size) {
  return {
    type: "FeatureCollection",
    features: cells.map(([south, west, ...depths]) => ({
      type: "Feature",
      properties: byFloodSize("d", (rp) => depthOrNone(depths[SCENARIOS.indexOf(rp)])),
      geometry: { type: "Polygon", coordinates: [[[west, south], [west + size, south], [west + size, south + size],
        [west, south + size], [west, south]]] },
    })),
  };
}

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

/** A shop's dot: grey when the model keeps it dry, then yellow, orange and red as the water at its door deepens. */
export const shopColour = (rp) => ["step", ["get", `d${rp}`], "#94a3b8", 0, "#eab308", SHALLOW_M, "#f97316", DEEP_M, "#e11d48"];

/** A section's shading by its share of wet squares, as the main page's choropleth bands it. */
export const sectionFill = (rp) => ["step", ["get", `s${rp}`], "rgba(0,0,0,0)", 0.0001, "#93c5fd", 0.05, "#60a5fa",
  0.15, "#3b82f6", 0.3, "#2563eb", 0.5, "#1e40af"];

/** The id of the base-map layer our water goes under, from a style's layers in drawing order; undefined puts it on top. */
export function underRoads(layers = []) {
  return (layers.find((layer) => OVER_WATER.test(layer.id)) ?? layers.find((layer) => layer.type === "symbol"))?.id;
}

/** The place card's badge for the water at a door: its tone and its words' key. */
export function badge(depth) {
  if (!(typeof depth === "number" && depth > 0)) return { tone: "dry", key: "mg.badge.dry" };
  if (depth < SHALLOW_M) return { tone: "watch", key: "mg.badge.shallow" };
  if (depth < DEEP_M) return { tone: "high", key: "mg.badge.deep" };
  return { tone: "deep", key: "mg.badge.veryDeep" };
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
  return shelters.reduce((best, shelter) => {
    const km = distanceKm(place, shelter);
    return !best || km < best.km ? { shelter, km } : best;
  }, null);
}

/** Up to `limit` businesses in the area's index whose name holds the words typed, in the index's order. */
export function searchIndex(index, words, limit = 6) {
  const wanted = words.trim().toLowerCase();
  if (wanted.length < 2) return [];
  return index.filter((entry) => entry.name?.toLowerCase().includes(wanted)).slice(0, limit);
}

/** Wet businesses across the area for a flood size, and all of them. */
export function wetTotals(sections, rp) {
  return sections.reduce((sum, s) => ({ wet: sum.wet + (s.counts.wet_businesses[rp] ?? 0), all: sum.all + s.counts.businesses }),
    { wet: 0, all: 0 });
}
