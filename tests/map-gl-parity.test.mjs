// node --test tests/map-gl-parity.test.mjs
// The new map's last parts from the old page: the search finds sections (by name, other name or the area's word for a
// section), and the sections' shading by flash flood potential or score takes the old map's colours.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { FLASH_METRIC, SCORE_METRIC } from "../app/static/js/choropleth.js";
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
  assert.deepEqual(searchSections(null, "seksyen"), [], "an area with no sections finds none");
});

test("shading by flash flood potential or score gives each section the old map's class colour, and none for no figures", () => {
  const sections = [{ id: "a", indexes: { score: { value: 4.2 } } }, { id: "b" }];
  const { color, opacity } = metricPaint(sections, "score");
  const step = SCORE_METRIC.classes[SCORE_METRIC.class(4.2)];
  assert.deepEqual(color.slice(0, 4), ["match", ["get", "id"], "a", step.color]);
  assert.equal(color[5], SCORE_METRIC.classes[0].color, "a section with no score: the 'not worked out' class");
  assert.equal(opacity.at(-1), 0, "anything else: not drawn");
  assert.equal(metricPaint(sections, "flash").color[3], FLASH_METRIC.classes[0].color, "no flash figures: the first class");
});
