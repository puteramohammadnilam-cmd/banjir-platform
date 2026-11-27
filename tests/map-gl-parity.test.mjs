// node --test tests/map-gl-parity.test.mjs
// The new map's last parts from the old page: the search finds sections (by name, other name or the area's word for a
// section), and the sections' shading by flash flood potential or score takes the old map's colours.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { FLASH_METRIC, SCORE_METRIC, STREET_WASH, STREET_ZOOM } from "../app/static/js/choropleth.js";
import { useLang } from "../app/static/js/i18n.js";
import { searchSections } from "../app/static/js/map-gl-data.js";
import { metricPaint } from "../app/static/js/map-gl-layers.js";
import { sectionFinder } from "../app/static/js/pick.js";
import { installFakeDom } from "./fake_dom.mjs";

const SECTIONS = [{ id: "seksyen-7", name: "Seksyen 7" }, { id: "seksyen-13", name: "Seksyen 13" }, { id: "u13", name: "Seksyen U13" }];
const ALIASES = [{ section: "seksyen-13", names: ["Taman Ilmu"] }];
const WORD = { en: "section", ms: "seksyen" };

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

test("the search finds sections by their name, another name, and the area's word for a section in full", () => {
  const finder = sectionFinder(SECTIONS, ALIASES, WORD, "City");
  assert.deepEqual(searchSections(finder, "seksyen 1").map((hit) => hit.section), ["seksyen-13"]);
  assert.deepEqual(searchSections(finder, "ilmu").map((hit) => hit.section), ["seksyen-13"]);
  assert.equal(searchSections(finder, "section 7")[0].section, "seksyen-7", "the English word for a Malay name, typed in full");
  assert.equal(new Set(searchSections(finder, "seksyen", 10).map((hit) => hit.section)).size, 3, "each section once");
  assert.deepEqual(searchSections(finder, "s"), [], "two letters at least");
  assert.deepEqual(searchSections(finder, "city"), [], "the city's name after a section's is not a match");
  assert.deepEqual(searchSections(null, "seksyen"), [], "an area with no sections finds none");
});

test("shading by flash flood potential or score gives each section the old map's class colour, and none for no figures", () => {
  const sections = [{ id: "a", indexes: { score: { value: 4.2 } } }, { id: "b" }];
  const { color, opacity } = metricPaint(sections, "score");
  const step = SCORE_METRIC.classes[SCORE_METRIC.class(4.2)];
  assert.deepEqual(color.slice(0, 4), ["match", ["get", "id"], "a", step.color]);
  assert.equal(color[5], SCORE_METRIC.classes[0].color, "a section with no score: the 'not worked out' class");
  assert.deepEqual(opacity.slice(0, 2), ["step", ["zoom"]]);
  assert.equal(opacity[2].at(-1), 0, "anything else: not drawn");
  assert.deepEqual(opacity.slice(3), [STREET_ZOOM, ["*", STREET_WASH, opacity[2]]], "a wash from street level in, as the old map");
  assert.equal(metricPaint(sections, "flash").color[3], FLASH_METRIC.classes[0].color, "no flash figures: the first class");
});

test("an area that sends no squares draws one depth picture per section at the flood size and theme on show", async () => {
  const { drawFloodDepth } = await import("../app/static/js/map-gl-layers.js");
  const calls = [];
  const drawer = { picture: (...args) => calls.push(["picture", ...args]), drop: (key) => calls.push(["drop", key]) };
  const depth = { url: "/api/areas/a/flood/{section}/{rp}/{theme}.png",
    pictures: [{ section: "d-1", bounds: [1, 2, 3, 4] }, { section: "d-2", bounds: [5, 6, 7, 8] }] };
  drawFloodDepth(drawer, depth, { rp: 20, isDark: true, isOn: true, opacity: 0.7 });
  assert.deepEqual(calls, [["picture", "d-1", "/api/areas/a/flood/d-1/20/dark.png", [1, 2, 3, 4], 0.7],
    ["picture", "d-2", "/api/areas/a/flood/d-2/20/dark.png", [5, 6, 7, 8], 0.7]]);
  calls.length = 0;
  drawFloodDepth(drawer, depth, { rp: 50, isDark: false, isOn: false, opacity: 0.7 });
  assert.deepEqual(calls, [["drop", "d-1"], ["drop", "d-2"]], "squares switched off: the pictures go too");
  calls.length = 0;
  drawFloodDepth(drawer, null, { rp: 50, isDark: false, isOn: true, opacity: 0.7 });
  assert.deepEqual(calls, [], "an area with squares of its own has no pictures");
});

test("the map names a section in the area's own word: a state's district, else a section", async () => {
  const { sectionCard, sectionWords } = await import("../app/static/js/map-gl-card.js");
  assert.deepEqual(sectionWords({ en: "District", ms: "Daerah" }), { word: "district" });
  assert.deepEqual(sectionWords(null), { word: "section" });
  const card = sectionCard({ name: "Muar", n: 3, s50: 0.2, w50: 1 }, { rp: "50", onOpen() {}, onClose() {}, words: { word: "district" } });
  const text = (nodes) => nodes.map((node) => node?.textContent ?? "").join(" ");
  assert.ok(text(card).includes("See this district's overview"));
  useLang("ms");
  assert.deepEqual(sectionWords({ en: "District", ms: "Daerah" }), { word: "daerah" });
});

test("an old area id that is now a section opens the whole area on that section, and other links are kept", async () => {
  const { areaForLink } = await import("../app/static/js/map-gl-data.js");
  const asked = [];
  const pages = { "kota-tinggi": { area: { id: "johor" }, section: { id: "kota-tinggi" }, sections: [{ id: "kota-tinggi", name: "Kota Tinggi" }] },
    johor: { area: { id: "johor" }, sections: [{ id: "kota-tinggi", counts: {} }] } };
  const api = { getAreaData: async (id) => { asked.push(id); return pages[id]; }, getDefaultData: async () => { asked.push("default"); return pages.johor; } };
  const old = await areaForLink({ area: "kota-tinggi", rp: "50", place: "node-1" }, api);
  assert.deepEqual(asked, ["kota-tinggi", "johor"]);
  assert.equal(old.data, pages.johor);
  assert.deepEqual(old.link, { area: "johor", rp: "50", place: "node-1", section: "kota-tinggi" });
  const named = await areaForLink({ area: "kota-tinggi", section: "mersing" }, api);
  assert.equal(named.link.section, "mersing", "a section the link names wins");
  asked.length = 0;
  const plain = await areaForLink({ area: "johor" }, api);
  assert.deepEqual([asked, plain.link], [["johor"], { area: "johor" }]);
  assert.equal((await areaForLink({}, api)).data, pages.johor);
});
