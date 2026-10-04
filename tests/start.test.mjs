// Run from 11_Platform_Draft:  node --test tests/start.test.mjs
// Start-up (start.js): what a link asks for and the data loaded to show it, against a fake API that answers from the
// contract fixtures. A city split into sections opens on the whole city; a section link, an old area's alias and an old
// business link land in their section; a plain area (no sections) loads exactly as it always did.
import assert from "node:assert/strict";
import { test } from "node:test";

import { readUrl } from "../app/static/js/place.js";
import { isCityView, linkedPlace, loadStart, openLink, pageArea, resolveTarget, sectionOf } from "../app/static/js/start.js";
import { AREA_LIST, CITY_AREA, CITY_DATA, INDEX, PLAIN_DATA, PLAIN_SUMMARY, SECTIONS } from "./fixtures/city_data.mjs";
import { SECTION_DATA } from "./fixtures/section_data.mjs";

const PLAIN_DEFAULT = { default: "kuantan", areas: [PLAIN_SUMMARY] };

/** A fake API: every call is recorded; `sections` maps a section id to its data (a missing one fails as a 404 does). */
function fakeApi({ list = AREA_LIST, defaultData = CITY_DATA, sections = { "seksyen-25": SECTION_DATA } } = {}) {
  const calls = [];
  const byId = { "shah-alam": CITY_DATA, kuantan: PLAIN_DATA };
  const record = (name, value) => { calls.push(name); return value; };
  return {
    calls,
    getCoverage: async () => record("coverage", { grids: [], regions: [] }),
    getAreas: async () => record("areas", list),
    getStatus: async () => record("status", { points_ready: true, ai_ready: false, maps_ready: false }),
    getDefaultData: async () => record("default", defaultData),
    getAreaData: async (id) => record(`area:${id}`, byId[id]),
    getSectionData: async (id, section) => {
      calls.push(`section:${id}/${section}`);
      if (!sections[section]) throw new Error("Unknown section.");
      return sections[section];
    },
    checkPoint: async () => record("point", null),
  };
}

const start = (search, api = fakeApi(), hash = "") => loadStart(readUrl({ search, hash }), api);

// ---------- the link ----------

test("a link with no area is the default; a listed area is itself; an alias is its area and its section", () => {
  assert.deepEqual(resolveTarget(readUrl({ search: "" }), AREA_LIST), { areaId: "shah-alam", sectionId: null, isAreaMissing: false });
  assert.deepEqual(resolveTarget(readUrl({ search: "?area=kuantan" }), AREA_LIST), { areaId: "kuantan", sectionId: null, isAreaMissing: false });
  assert.deepEqual(resolveTarget(readUrl({ search: "?area=sri-muda" }), AREA_LIST), { areaId: "shah-alam", sectionId: "seksyen-25", isAreaMissing: false });
  assert.deepEqual(resolveTarget(readUrl({ search: "?area=sri-muda&section=seksyen-24" }), AREA_LIST),
    { areaId: "shah-alam", sectionId: "seksyen-24", isAreaMissing: false }, "a section the link names wins over the alias's");
  assert.deepEqual(resolveTarget(readUrl({ search: "?area=atlantis&section=seksyen-25" }), AREA_LIST),
    { areaId: "shah-alam", sectionId: null, isAreaMissing: true }, "an unknown area's section is not guessed at");
});

test("an older server's list, with no aliases or has_sections, resolves as it always did", () => {
  assert.deepEqual(resolveTarget(readUrl({ search: "?area=sri-muda" }), PLAIN_DEFAULT), { areaId: "kuantan", sectionId: null, isAreaMissing: true });
});

test("a business's section comes from the city index; one it does not hold has none", () => {
  assert.equal(sectionOf(INDEX, "node-2"), "seksyen-25");
  assert.equal(sectionOf(INDEX, "node-404"), null);
  assert.equal(sectionOf(null, "node-2"), null);
});

// ---------- the city view ----------

test("no link: the default city's data is asked for at once, beside the list, and the page opens on the whole city", async () => {
  const api = fakeApi();
  const shown = await start("", api);
  assert.deepEqual(api.calls.slice(0, 4).sort(), ["areas", "coverage", "default", "status"]);
  assert.equal(api.calls.length, 4, "one load: nothing waits on the list");
  assert.equal(isCityView(shown), true);
  assert.equal(shown.section, null);
  assert.deepEqual(shown.premises, []);
  assert.equal(shown.index.length, INDEX.length);
  assert.deepEqual(shown.sections.map(({ id }) => id), SECTIONS.map(({ id }) => id));
  assert.equal(shown.page.name, "Shah Alam", "the city's own name");
});

test("a section link loads that section: its businesses in full, its squares, and the city's sections for the select", async () => {
  const api = fakeApi();
  const shown = await start("?section=seksyen-25&tab=business&place=node-1", api);
  assert.ok(api.calls.includes("section:shah-alam/seksyen-25"));
  assert.ok(!api.calls.includes("default"), "the city's data is not loaded for a section");
  assert.equal(isCityView(shown), false);
  assert.equal(shown.section.id, "seksyen-25");
  assert.equal(shown.premises.length, 3);
  assert.deepEqual(shown.premises.map(({ area_id: areaId, is_point: isPoint }) => [areaId, isPoint]), Array(3).fill(["shah-alam", false]));
  assert.equal(shown.page.name, "Seksyen 25");
  assert.equal(shown.page.display_name, "Seksyen 25, Shah Alam");
  assert.equal(shown.page.id, "shah-alam", "requests still name the area");
  assert.equal(shown.index, null, "the city index is loaded only when the search needs it");
  const { linked, note } = await openLink(readUrl({ search: "?section=seksyen-25&place=node-1" }), shown, api);
  assert.equal(linked.place.id, "node-1");
  assert.equal(note, null);
});

test("the old area's link (?area=sri-muda) lands in its section with no note", async () => {
  const shown = await start("?area=sri-muda&tab=business&place=node-1");
  assert.equal(shown.section.id, "seksyen-25");
  assert.equal(shown.isAreaMissing, false);
  const { note } = await openLink(readUrl({ search: "?area=sri-muda&place=node-1" }), shown, fakeApi());
  assert.equal(note, null);
});

test("an old business link with no section goes to the business's section, found in the city index", async () => {
  const api = fakeApi();
  const shown = await start("?place=node-2&tab=business", api);
  assert.deepEqual(api.calls.filter((call) => call.startsWith("section:")), ["section:shah-alam/seksyen-25"]);
  assert.equal(shown.section.id, "seksyen-25");
  const { linked } = await openLink(readUrl({ search: "?place=node-2" }), shown, api);
  assert.equal(linked.place.id, "node-2");
});

test("a business the city does not hold stays on the whole city, with the note", async () => {
  const api = fakeApi();
  const shown = await start("?place=node-404&tab=business", api);
  assert.equal(isCityView(shown), true);
  const { linked, note } = await openLink(readUrl({ search: "?place=node-404" }), shown, api);
  assert.equal(linked, null);
  assert.match(note, /not in this build\. Showing Shah Alam\./);
});

test("an unknown section shows the whole city, with the note", async () => {
  const api = fakeApi();
  const shown = await start("?section=seksyen-99", api);
  assert.deepEqual(api.calls.filter((call) => call.startsWith("section:") || call.startsWith("area:")), ["section:shah-alam/seksyen-99", "area:shah-alam"]);
  assert.equal(isCityView(shown), true);
  assert.equal(shown.isSectionMissing, true);
  const { note } = await openLink(readUrl({ search: "?section=seksyen-99" }), shown, api);
  assert.match(note, /Showing Shah Alam/);
});

test("a city whose data names a default section opens on it when the link names none", async () => {
  const defaultData = { ...CITY_DATA, area: { ...CITY_AREA, default_section: "seksyen-25" } };
  const shown = await start("", fakeApi({ defaultData }));
  assert.equal(shown.section.id, "seksyen-25");
});

test("a point in the city view is checked as anywhere else: the point never picks a section on its own", async () => {
  const api = fakeApi();
  const shown = await start("", api, "#place=pt:3.02998,101.53667");
  assert.equal(isCityView(shown), true);
  const place = { id: "pt:3.02998,101.53667", is_point: true, area_id: "shah-alam", section: { id: "seksyen-25", name: "Seksyen 25" } };
  api.checkPoint = async () => ({ coverage: "covered", place, blocks: [], cells: [] });
  const linked = await linkedPlace("pt:3.02998,101.53667", { ...shown, coverage: Promise.resolve(null) }, api);
  assert.equal(linked.place, place);
  assert.equal(shown.section, null, "still the whole city");
});

// ---------- a plain area: the old path ----------

test("a plain default area (no sections) loads exactly as before: one data call, its premises, no sections or index", async () => {
  const api = fakeApi({ list: PLAIN_DEFAULT, defaultData: PLAIN_DATA });
  const shown = await start("?tab=business&place=node-90", api);
  assert.deepEqual(api.calls.slice().sort(), ["areas", "coverage", "default", "status"], "the same four calls as ever");
  assert.equal(isCityView(shown), false);
  assert.equal(shown.section, null);
  assert.equal(shown.index, null);
  assert.deepEqual(shown.sections, []);
  assert.equal(shown.page, shown.area, "the page's area is the area itself");
  assert.deepEqual(shown.premises.map(({ id }) => id), ["node-90", "node-91"]);
  const { linked, note } = await openLink(readUrl({ search: "?place=node-90" }), shown, api);
  assert.equal(linked.place.id, "node-90");
  assert.equal(note, null);
});

test("a plain area named in the link loads it alone; a section in its link is ignored with the note", async () => {
  const api = fakeApi();
  const shown = await start("?area=kuantan&section=seksyen-25", api);
  assert.ok(api.calls.includes("area:kuantan"));
  assert.ok(!api.calls.some((call) => call.startsWith("section:")));
  assert.equal(shown.area.id, "kuantan");
  assert.equal(shown.isSectionMissing, true);
  const plain = await start("?area=kuantan", fakeApi());
  assert.equal(plain.isSectionMissing, false);
});

test("the page's area is the section dressed as an area, and the area itself with no section", () => {
  assert.equal(pageArea(PLAIN_DATA.area, null), PLAIN_DATA.area);
  const page = pageArea(CITY_AREA, SECTIONS[1]);
  assert.deepEqual([page.id, page.name, page.display_name, page.section_id], ["shah-alam", "Seksyen 25", "Seksyen 25, Shah Alam", "seksyen-25"]);
});

test("the map of a plain area opens on its view and owns its squares, as before; a city's and a section's differ", async () => {
  const { mapFrame } = await import("../app/static/js/overview.js");
  assert.deepEqual(mapFrame(PLAIN_DATA.area, null), { view: PLAIN_SUMMARY.view, zoom: 15, ownedBox: PLAIN_SUMMARY.view, outline: null });
  const city = { section: null };
  assert.deepEqual(mapFrame(CITY_AREA, city), { view: CITY_AREA.view, zoom: 12, ownedBox: null, outline: null, fit: true }, "the whole city draws no squares of its own");
  const section = SECTIONS[1];
  assert.deepEqual(mapFrame(pageArea(CITY_AREA, section), { section }), { view: section.bbox, zoom: 15, ownedBox: section.bbox, outline: section.outline, fit: true });
});

test("an old area's link to a business goes to the business's own section, which may not be the alias's", async () => {
  const api = fakeApi({ sections: { "seksyen-24": { ...SECTION_DATA, section: SECTIONS[0], premises: [] }, "seksyen-25": SECTION_DATA } });
  const shown = await start("?area=sri-muda&tab=business&place=node-24", api);
  assert.deepEqual(api.calls.filter((call) => call.startsWith("section:") || call.startsWith("area:")), ["area:shah-alam", "section:shah-alam/seksyen-24"]);
  assert.equal(shown.section.id, "seksyen-24");
  const unknown = await start("?area=sri-muda&place=node-404");
  assert.equal(unknown.section.id, "seksyen-25", "a business the index does not hold: the alias's own section");
});
