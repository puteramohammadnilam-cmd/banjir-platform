// Shared by tests/point.test.mjs and tests/views.test.mjs: two listed areas, a point as POST /api/point gives it, and a
// business as the page holds it. The names are made up: nothing here depends on a real area's data.
import { businessPlace } from "../app/static/js/place.js";

const HISTORY = {
  first_year: 2000, recent_from: 2019, last_year: 2026,
  floods: [
    { when: "2005", year: 2005.1, what: "A flood.", source: "A paper" },
    { when: "May 2020", year: 2020.4, what: "Another flood.", source: "A paper" },
  ],
};

/** The page's own area, as GET /api/areas/{id}/data sends it (`area`): with its flood record. */
export const HOME = { id: "home", name: "Home Town", display_name: "Home Town, Some State", history: HISTORY };
/** A listed area as GET /api/areas lists it: no flood record, only that it has one. */
export const FAR = { id: "far", name: "Far Town", display_name: "Far Town centre, Other State" };
export const AREAS = [{ id: "home", name: "Home Town", display_name: "Home Town, Some State" }, FAR];

/** A point as POST /api/point gives it (1.88 m at 1 in 100 is the square of a real business; the area is made up). */
export const point = (change = {}) => ({
  id: "pt:3.02998,101.53667", is_point: true, name: null, sector: null, kind: null, is_chain: null, lat: 3.02998, lon: 101.53667,
  map_last_edited: null, area_id: "home", depth_m: { 10: 1.35, 100: 1.88, 500: 2.11 }, road: null, shelter: null,
  cell: { grid: "N10_E100", row: 8372, col: 1872, bounds: [101.536252, 3.029567, 101.537085, 3.0304] }, ...change,
});

/** A mapped business of the page's area, with a road. */
export const shop = businessPlace({
  id: "node-1", name: "A Shop", depth_m: { 10: 0.2, 100: 0.5, 500: 1 },
  road: { name: "Jalan A", kind: "service", distance_m: 9, depth_m: { 10: 0.1, 100: 0.4, 500: 0.9 } },
}, "home");

/** What GET /api/place/{id} says for a business that Google Maps lists. */
export const LISTING = { configured: true, place: { status: "open", name: "A Shop", maps_uri: "https://maps.example/a-shop" } };
