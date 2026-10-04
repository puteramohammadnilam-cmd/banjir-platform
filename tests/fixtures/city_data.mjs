// The API contract of a city split into sections (plan Phase 2, section 1), as the front end codes against it before the
// server exists. Made up and small: three sections, five businesses. Shapes are exact; app/sections.py must give the same.
//   GET /api/areas                       AREA_LIST: each area gains `has_sections` and `aliases`
//   GET /api/data, /api/areas/{id}/data  CITY_DATA: the city's details, `sections` (outlines and counts), the lean `index`
//                                        of every business, the town with shelters but no squares, and no premises
// A plain area (no sections) answers as it always did: PLAIN_DATA.

export const SECTION_WORD = Object.freeze({ en: "Section", ms: "Seksyen" });
export const ALIASES = Object.freeze([{ id: "sri-muda", section: "seksyen-25", names: ["Taman Sri Muda", "Taman Seri Muda"] }]);

/** One flood of app/history.py for_scope (F): the old fields (when, year, what, source, account) and the new ones. */
export const flood = (id, date, year, sections, change = {}) => ({
  id, date, when: date, year, place: "A street", what: "A flood.", depth: null, sections, confidence: "high", account: false,
  undated: false, source: "A paper", url: "https://example.org/a", source_type: "news",
  sources: [{ title: "A paper", url: "https://example.org/a", type: "news" }], ...change,
});

const SECTION_NAMES = { "seksyen-24": { en: "Section 24", ms: "Seksyen 24" }, "seksyen-25": { en: "Section 25", ms: "Seksyen 25" } };

/** The whole city's record (scope null), as the city's data sends it in `area.history`. */
export const CITY_HISTORY = {
  first_year: 1992, recent_from: 2019, last_year: 2026, scope: null, checked: "2026-10-04", section_names: SECTION_NAMES,
  gaps: [[1992, 2005], [2007, 2020], [2022, 2026]],
  floods: [flood("f-2006", "2006-02-26", 2006.15, ["seksyen-24"]), flood("f-2021", "2021-12-18", 2021.96, ["seksyen-25"], { depth: "over 4 m" })],
};

const SUMMARY = {
  id: "shah-alam", name: "Shah Alam", display_name: "Shah Alam, Selangor", view: [101.48, 3.0, 101.56, 3.08], zoom: 12,
  counts: { businesses: 5, squares: 0, shelters: 1 }, has_history: true, has_shelters: true,
  has_sections: true, aliases: ALIASES,
};

/** GET /api/areas/shah-alam/data `area`: the summary, the details as today, and the section fields. */
export const CITY_AREA = Object.freeze({
  ...SUMMARY, council: "The council", notes: { businesses: "Mapped on a public map." }, history: CITY_HISTORY,
  bigger_flood_example: "2021-12", section_word: SECTION_WORD, default_section: null,
});

/** A plain area as GET /api/areas lists it today (older servers send no has_sections or aliases at all). */
export const PLAIN_SUMMARY = Object.freeze({
  id: "kuantan", name: "Kuantan", display_name: "Kuantan town centre, Pahang", view: [103.3085, 3.7907, 103.3435, 3.8247],
  zoom: 15, counts: { businesses: 2, squares: 1, shelters: 0 }, has_history: false, has_shelters: false,
});

export const AREA_LIST = Object.freeze({ default: "shah-alam", areas: [SUMMARY, PLAIN_SUMMARY] });

const box = ([west, south, east, north]) => ({
  type: "Polygon", coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
});
const counts = (businesses, cells, wetBusinesses, wetCells) => ({
  businesses, cells,
  wet_businesses: { 10: wetBusinesses[0], 20: wetBusinesses[1], 50: wetBusinesses[2] },
  wet_cells: { 10: wetCells[0], 20: wetCells[1], 50: wetCells[2] },
});

/** In the data's own order (1-36, then U1-U20): the order a sort by name puts back. */
export const SECTIONS = Object.freeze([
  { id: "seksyen-24", name: "Seksyen 24", bbox: [101.5, 3.0, 101.52, 3.02], zoom: 15, outline: box([101.5, 3.0, 101.52, 3.02]),
    area_km2: 4.9, counts: counts(1, 600, [0, 1, 1], [12, 30, 66]) },
  { id: "seksyen-25", name: "Seksyen 25", bbox: [101.52, 3.0, 101.55, 3.04], zoom: 15,
    outline: { type: "MultiPolygon", coordinates: [box([101.52, 3.0, 101.55, 3.04]).coordinates] },
    area_km2: 12.2, counts: counts(3, 1500, [1, 2, 2], [300, 520, 870]) },
  { id: "seksyen-u1", name: "Seksyen U1", bbox: [101.5, 3.05, 101.53, 3.08], zoom: 15, outline: box([101.5, 3.05, 101.53, 3.08]),
    area_km2: 9.6, counts: counts(1, 1200, [0, 0, 0], [0, 0, 0]) },
]);

const row = (id, name, section, depths, road = "Jalan A") => ({
  id, name, kind: "convenience", sector: "shop", section, road: { name: road }, depth_m: { 10: depths[0], 20: depths[1], 50: depths[2] },
});

/** The lean index: one row per business of the city. */
export const INDEX = Object.freeze([
  row("node-24", "Kedai Dua Empat", "seksyen-24", [null, 0.4, 0.9]),
  row("node-1", "A Shop", "seksyen-25", [0.2, 0.5, 1], "Jalan Sungai"),
  row("node-2", "Dobi Queen", "seksyen-25", [null, 0.3, 0.6], "Jalan Sungai"),
  row("node-3", "Dobi Kering", "seksyen-25", [null, null, null]),
  row("node-u1", "Kedai U Satu", "seksyen-u1", [null, null, null], "Persiaran U"),
]);

export const CITY_SHELTERS = Object.freeze([{ name: "Dewan Orang Ramai", lat: 3.03, lon: 101.53 }]);

/** GET /api/data when the default area is the city. */
export const CITY_DATA = Object.freeze({
  area: CITY_AREA, sections: SECTIONS, index: INDEX,
  town: { view: CITY_AREA.view, cell_deg: 0.000833, return_periods: [10, 20, 50], shelters: CITY_SHELTERS, cells: [] },
  premises: [], limits: "Depths come from a global computer model.",
});

/** GET /api/areas/kuantan/data: a plain area, as it always was. */
export const PLAIN_DATA = Object.freeze({
  area: { ...PLAIN_SUMMARY, council: "The town council", notes: {}, history: null, bigger_flood_example: null },
  town: { view: PLAIN_SUMMARY.view, cell_deg: 0.000833, return_periods: [10, 20, 50], shelters: [], cells: [[3.8, 103.32, 0.1, 0.2, 0.3]] },
  premises: [
    { id: "node-90", name: "Kedai Pantai", sector: "shop", kind: "convenience", is_chain: false, lat: 3.80, lon: 103.32, map_last_edited: null,
      depth_m: { 10: 0.1, 20: 0.2, 50: 0.3 }, road: { name: "Jalan Besar", kind: "primary", distance_m: 5, depth_m: { 10: null, 20: null, 50: 0.1 } }, shelter: null },
    { id: "node-91", name: "Kedai Bukit", sector: "shop", kind: "convenience", is_chain: false, lat: 3.81, lon: 103.33, map_last_edited: null,
      depth_m: { 10: null, 20: null, 50: null }, road: { name: "Jalan Bukit", kind: "primary", distance_m: 8, depth_m: { 10: null, 20: null, 50: null } }, shelter: null },
  ],
  limits: "Depths come from a global computer model.",
});

// ---------- flash flood potential and our score (plan Phase 3; tests/fixtures/index_contract.json on p3-index-data) ----------
// A section gains `indexes` {flash {mean (1-10), share {low, medium, high, extreme}} | null, score {value (1-5), class
// (very_low .. very_high)} | null} (the key absent where the area has none); the area's details always carry
// `layers.flash_flood` {url, bounds [west, south, east, north], breaks, credit} | null, `index_method` {flash, score,
// validation, show_score} | null and `flash_flood_example` (a section id) | null; a business or a point gains
// `flash_flood` {score, class} | null. Older servers send none of these.
const indexes = (mean, [low, medium, high, extreme], score) => ({ flash: { mean, share: { low, medium, high, extreme } }, score });
const SECTION_INDEXES = {
  "seksyen-24": indexes(4.1, [0.5, 0.3, 0.15, 0.05], { value: 3.2, class: "moderate" }),
  "seksyen-25": indexes(3.0, [0.7, 0.25, 0.04, 0.01], { value: 4.6, class: "very_high" }),
  "seksyen-u1": indexes(6.8, [0.1, 0.2, 0.4, 0.3], null),
};
export const INDEXED_SECTIONS = Object.freeze(SECTIONS.map((section) => ({ ...section, indexes: SECTION_INDEXES[section.id] })));

export const INDEX_METHOD = Object.freeze({
  show_score: true,
  flash: {
    name: "Flash Flood Potential Index (FFPI)", formula: "(1.5 M + L + S + 0.5 V) / 4", summary: "Each 30 m square rated 1 to 10.",
    citations: ["Smith, G. (2003). Flash flood potential.", { text: "Yassin et al. (2023). Planning Malaysia 21(2).", url: "https://example.org/pm" }],
    deviations: ["Vegetation cover from a satellite greenness composite.", "Built-up land with no soil data is rated impervious."],
    not: "A susceptibility to flash floods, not a water depth and not a chance of flooding.",
  },
  score: {
    name: "Flood risk score (multi-criteria)", summary: "Seven criteria.", weights_used: { river_distance: 0.2432 }, weights_total: 74,
    classes: ["very_low", "low", "moderate", "high", "very_high"], breaks: [1.5, 2.5, 3.5, 4.5], break_rule: "At or above a break: the class above.",
    citations: ["Leeonis, A. N. et al. (2024) Discover Sustainability 5:352."], deviations: ["Rainfall and economic loss are dropped: weights out of 74."],
    credit: "Section score: WorldPop 2020 constrained (CC BY 4.0); OpenStreetMap contributors (ODbL).",
  },
  validation: { wording: "Compared with past flood records and the river model; this does not validate either index.", n: 56 },
});

export const FLASH_LAYER = Object.freeze({
  url: "/api/areas/shah-alam/layers/flash-flood.png", bounds: [101.43, 2.95, 101.59, 3.23], breaks: [4.5, 6.5, 8.5],
  credit: "Flash flood potential: ESA WorldCover 2021, SoilGrids 2.0.",
});

/** The city's details with the index fields; its example of flash floods is a section its record names. */
export const INDEXED_AREA = Object.freeze({
  ...CITY_AREA, index_method: INDEX_METHOD, layers: { flash_flood: FLASH_LAYER }, flash_flood_example: "seksyen-24",
});
