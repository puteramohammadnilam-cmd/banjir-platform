// GET|HEAD /api/areas/{id}/sections/{sid}/data, as the front end codes against it (plan Phase 2, section 1): the city's
// details with the section's own flood record, the section (outline and counts), the city's sections by id and name (for
// the section select and the finder), the town cut to the section (view = its bbox, the squares that overlap it, every
// shelter of the city) and the section's businesses in full, each with its `section`. An unknown section is a 404
// envelope, {success: false, error: "Unknown section."}.
import { CITY_AREA, CITY_HISTORY, CITY_SHELTERS, SECTIONS } from "./city_data.mjs";

const [, SEKSYEN_25] = SECTIONS;

const premise = (id, name, lat, lon, depths, road = "Jalan Sungai") => ({
  id, name, sector: "shop", kind: "convenience", is_chain: false, lat, lon, map_last_edited: null, section: "seksyen-25",
  depth_m: { 10: depths[0], 20: depths[1], 50: depths[2] },
  road: { name: road, kind: "service", distance_m: 9, depth_m: { 10: depths[0], 20: depths[1], 50: depths[2] } }, shelter: null,
});

/** The section's own record (scope = its id), as the section's data sends it in `area.history`. */
export const SECTION_HISTORY = {
  ...CITY_HISTORY, scope: "seksyen-25", section_names: { "seksyen-25": CITY_HISTORY.section_names["seksyen-25"] },
  gaps: [[1992, 2020], [2022, 2026]], floods: CITY_HISTORY.floods.filter((entry) => entry.sections.includes("seksyen-25")),
};

export const SECTION_DATA = Object.freeze({
  area: { ...CITY_AREA, history: SECTION_HISTORY },
  section: SEKSYEN_25,
  sections: SECTIONS.map(({ id, name }) => ({ id, name })),
  town: {
    view: SEKSYEN_25.bbox, cell_deg: 0.000833, return_periods: [10, 20, 50], shelters: CITY_SHELTERS,
    cells: [[3.03, 101.53, 0.2, 0.5, 1], [3.031, 101.531, null, 0.3, 0.6]],
  },
  premises: [
    premise("node-1", "A Shop", 3.0297, 101.5365, [0.2, 0.5, 1]),
    premise("node-2", "Dobi Queen", 3.031, 101.531, [null, 0.3, 0.6]),
    premise("node-3", "Dobi Kering", 3.035, 101.54, [null, null, null], "Jalan A"),
  ],
  limits: "Depths come from a global computer model.",
});

/** A section with no record found: history with no floods (F: "no record is not no flood"). */
export const QUIET_SECTION_DATA = Object.freeze({
  ...SECTION_DATA,
  area: { ...CITY_AREA, history: { ...SECTION_HISTORY, scope: "seksyen-u1", section_names: {}, gaps: [[1992, 2026]], floods: [] } },
  section: SECTIONS[2],
  premises: [],
});
