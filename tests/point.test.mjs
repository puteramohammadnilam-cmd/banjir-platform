// Run from 11_Platform_Draft:  node --test tests/point.test.mjs
// What the tabs say about a point someone picked: the header and its notes (point.js), the cost tab's title (cost.js)
// and the chat's chips and news (chat.js). All plain data, so node needs no DOM. A point is one 90 m square of the flood
// model (app/places.py), not a mapped business: it has no name, kind or road, and lies in a listed area or in none.
import assert from "node:assert/strict";
import { test } from "node:test";

import { NEWS_NOTE, chipsFor, newsFor } from "../app/static/js/chat.js";
import { useLang } from "../app/static/js/i18n.js";
import { costTitle } from "../app/static/js/cost.js";
import { businessPlace } from "../app/static/js/place.js";
import { NO_WATER_NOTE, areaOf, pointHeader } from "../app/static/js/point.js";
import { pageArea } from "../app/static/js/start.js";
import { AREAS, FAR, HOME, point, shop } from "./point_fixtures.mjs";
import { CITY_AREA, SECTIONS } from "./fixtures/city_data.mjs";

test("a point in the page's own area is titled with that area, and says which square it is", () => {
  assert.deepEqual(pointHeader(point(), HOME, AREAS), {
    kicker: "A point you picked",
    title: "Point in Home Town, Some State",
    subline: "The 90 m flood square at 3.02998, 101.53667",
    tags: ["90 m model square", "Not a mapped business"],
    elsewhere: null,
  });
});

test("the square's centre is written with 5 decimals, whatever its digits", () => {
  const header = pointHeader(point({ id: "pt:1.50000,103.90000", lat: 1.5, lon: 103.9 }), HOME, AREAS);
  assert.equal(header.subline, "The 90 m flood square at 1.50000, 103.90000");
  assert.equal(pointHeader(point({ lat: 6.123456789, lon: 100.000004 }), HOME, AREAS).subline, "The 90 m flood square at 6.12346, 100.00000");
});

test("a point in another listed area names it and offers to open it", () => {
  const header = pointHeader(point({ area_id: "far" }), HOME, AREAS);
  assert.equal(header.title, "Point in Far Town centre, Other State");
  assert.deepEqual(header.elsewhere, { kind: "area", id: "far", text: "This point is in Far Town.", action: "Open Far Town" });
});

test("a point in no listed area is a point you picked, with nothing to open", () => {
  const nothing = { title: "Point you picked", elsewhere: null };
  for (const area_id of [null, undefined, "", "nowhere"]) {
    const { title, elsewhere } = pointHeader(point({ area_id }), HOME, AREAS);
    assert.deepEqual({ title, elsewhere }, nothing, String(area_id));
  }
  const unnamed = pointHeader(point({ area_id: "far" }), HOME);   // the list of areas did not load: no name to give
  assert.deepEqual({ title: unnamed.title, elsewhere: unnamed.elsewhere }, nothing);
});

test("a header is still made when the list of areas is null, an area has no display name or a square has no coordinates", () => {
  assert.equal(pointHeader(point({ area_id: "far" }), HOME, null).title, "Point you picked");
  assert.equal(areaOf(point({ area_id: "far" }), HOME, null), null);
  assert.equal(areaOf(point(), HOME, null), HOME);
  assert.equal(pointHeader(point(), { id: "home", name: "Home Town" }, AREAS).title, "Point in Home Town");
  for (const missing of [{ lat: undefined }, { lon: null }, { lat: NaN }, { lon: "101.5" }]) {
    assert.equal(pointHeader(point(missing), HOME, AREAS).subline, null, JSON.stringify(missing));
  }
});

test("a point's words never show its id, never say safe or will flood, and keep the note's exact wording", () => {
  const header = pointHeader(point(), HOME, AREAS);
  assert.ok(!JSON.stringify(header).includes("pt:"), "no raw id on the page");
  assert.equal(NO_WATER_NOTE, "The model maps river floods on land. It does not show flash floods, blocked drains or the sea.");
  assert.ok(!/safe|will flood/i.test(`${NO_WATER_NOTE} ${JSON.stringify(header)}`), "every depth is 'in the model': never safe, never will flood");
});

test("areaOf finds the page's area or a listed one, and never invents one", () => {
  assert.equal(areaOf(point(), HOME, AREAS), HOME);
  assert.equal(areaOf(point({ area_id: "far" }), HOME, AREAS), FAR);
  assert.equal(areaOf(point({ area_id: "far" }), HOME), null);
  assert.equal(areaOf(point({ area_id: "home" }), HOME), HOME, "the page's area needs no list");
  for (const area_id of [null, undefined, "", "nowhere", "HOME"]) assert.equal(areaOf(point({ area_id }), HOME, AREAS), null, String(area_id));
  assert.equal(areaOf(null, HOME, AREAS), null);
  assert.equal(areaOf(shop, HOME, AREAS), HOME, "a business is in the area it was loaded with");
});

test("the words are made without changing the place, the page's area or the list of areas", () => {
  const frozen = (value) => Object.freeze(Array.isArray(value) ? value.map(frozen) : { ...value });
  const place = frozen({ ...point({ area_id: "far" }), cell: Object.freeze({ ...point().cell }), depth_m: Object.freeze({ ...point().depth_m }) });
  const areas = Object.freeze(AREAS.map(frozen));
  assert.equal(pointHeader(place, frozen(HOME), areas).title, "Point in Far Town centre, Other State");
  assert.equal(areaOf(place, frozen(HOME), areas).id, "far");
  assert.ok(Object.isFrozen(pointHeader(place, HOME, AREAS).tags), "the shared tag list cannot be changed by a caller");
});

test("the cost tab's title says 'this point' for a point and names a business", () => {
  assert.equal(costTitle(point()), "What a flood could cost at this point");
  assert.equal(costTitle(shop), "What a flood could cost A Shop");
});

test("with nothing picked, the chips ask only about the area", () => {
  assert.deepEqual(chipsFor(undefined, HOME, AREAS), ["Which businesses stay dry in a 1 in 50 years flood?", "Is heavy rain due today?"]);
});

test("a business keeps its five chips; a point gets its own, with no question a point cannot answer", () => {
  const business = chipsFor(shop, HOME, AREAS);
  assert.deepEqual(business, [
    "Would this shop get water in a big flood?",
    "Roughly how much could this shop lose in a flood?",
    "Which businesses stay dry in a 1 in 50 years flood?",
    "Is heavy rain due today?",
    "Is this shop still open?",
  ]);
  const outside = chipsFor(point({ area_id: null }), HOME, AREAS);
  assert.equal(outside[0], "Would this area get water in a big flood?");
  for (const chip of outside) assert.ok(!/shop|kedai|open|buka/i.test(chip), `${chip} is about a shop`);
  assert.ok(!outside.some((chip) => chip.includes("Which businesses")), "no area summary outside the listed areas");
});

test("in Bahasa Melayu every chip set is in Bahasa Melayu, with the same questions a point can and cannot answer", () => {
  useLang("ms");
  try {
    assert.deepEqual(chipsFor(shop, HOME, AREAS), [
      "Kedai ni kena air tak kalau banjir besar?",
      "Berapa anggaran rugi kedai ni kalau banjir?",
      "Perniagaan mana yang tak kena air dalam banjir 1 dalam 50 tahun?",
      "Hujan lebat tak hari ni?",
      "Kedai ni masih buka tak?",
    ]);
    const outside = chipsFor(point({ area_id: null }), HOME, AREAS);
    assert.equal(outside[0], "Kawasan ni kena air tak kalau banjir besar?");
    for (const chip of outside) assert.ok(!/shop|kedai|open|buka/i.test(chip), `${chip} is about a shop`);
    const inside = chipsFor(point({ area_id: "home" }), HOME, AREAS);
    assert.deepEqual(inside.filter((chip) => !outside.includes(chip)), ["Perniagaan mana di kawasan ini yang tak kena air dalam banjir 1 dalam 50 tahun?"]);
    assert.equal(chipsFor(shop, HOME, AREAS), chipsFor(shop, HOME, AREAS), "the same frozen list, so the chat rebuilds nothing");
  } finally {
    useLang("en");
  }
});

test("a point inside a listed area also gets the area question", () => {
  const outside = chipsFor(point({ area_id: null }), HOME, AREAS);
  for (const area_id of ["home", "far"]) {
    const inside = chipsFor(point({ area_id }), HOME, AREAS);
    assert.deepEqual(inside.filter((chip) => !outside.includes(chip)), ["Which businesses in this area stay dry in a 1 in 50 years flood?"], area_id);
    assert.equal(inside.length, outside.length + 1);
  }
});

test("the same kind of place gets the very same list, which is how the chat knows nothing changed", () => {
  const other = businessPlace({ id: "node-2", name: "B Shop", depth_m: {} }, "home");
  assert.equal(chipsFor(shop, HOME, AREAS), chipsFor(other, HOME, AREAS));
  assert.equal(chipsFor(point({ area_id: "home" }), HOME, AREAS), chipsFor(point({ area_id: "far" }), HOME, AREAS));
  assert.equal(chipsFor(point({ area_id: null }), HOME, AREAS), chipsFor(point({ area_id: "nowhere" }), HOME, AREAS));
  assert.notEqual(chipsFor(shop, HOME, AREAS), chipsFor(point(), HOME, AREAS));
  for (const place of [shop, point({ area_id: null }), point()]) assert.ok(Object.isFrozen(chipsFor(place, HOME, AREAS)));
});

test("every chip fits the question box, and none repeats", () => {
  const kinds = [shop, point({ area_id: null }), point({ area_id: "home" }), point({ area_id: "far" })];
  for (const place of kinds) {
    const chips = chipsFor(place, HOME, AREAS);
    assert.equal(new Set(chips).size, chips.length);
    for (const chip of chips) assert.ok(chip.length > 0 && chip.length <= 500, chip);   // the question input's maxlength
  }
});

test("flood news follows the place: a business's area, a point's area, nothing for a point in none", () => {
  assert.deepEqual(newsFor(shop, HOME, AREAS), { areaId: "home", name: "Home Town" });
  assert.deepEqual(newsFor(point(), HOME, AREAS), { areaId: "home", name: "Home Town" });
  assert.deepEqual(newsFor(point({ area_id: "far" }), HOME, AREAS), { areaId: "far", name: "Far Town" });
  for (const area_id of [null, "nowhere"]) assert.equal(newsFor(point({ area_id }), HOME, AREAS), null, String(area_id));
  assert.equal(NEWS_NOTE, "Flood news is available for the listed areas.");
});

// ---------- a point in a city split into sections ----------

const IN_25 = { id: "seksyen-25", name: "Seksyen 25" };
const cityPoint = (section = IN_25) => point({ area_id: "shah-alam", section });
const CITY_LIST = [{ id: "shah-alam", name: "Shah Alam", display_name: "Shah Alam, Selangor" }, FAR];

test("on the whole city's page a point names its section and offers to open it: never opened on its own", () => {
  const header = pointHeader(cityPoint(), CITY_AREA, CITY_LIST);
  assert.equal(header.title, "Point in Seksyen 25, Shah Alam");
  assert.deepEqual(header.elsewhere, { kind: "section", id: "seksyen-25", text: "This point is in Seksyen 25.", action: "Open Seksyen 25" });
});

test("on its own section's page a point names the section and offers nothing; in another section it offers that one", () => {
  const here = pointHeader(cityPoint(), pageArea(CITY_AREA, SECTIONS[1]), CITY_LIST);
  assert.equal(here.title, "Point in Seksyen 25, Shah Alam");
  assert.equal(here.elsewhere, null);
  const next = pointHeader(cityPoint(), pageArea(CITY_AREA, SECTIONS[0]), CITY_LIST);
  assert.equal(next.title, "Point in Seksyen 25, Shah Alam");
  assert.equal(next.elsewhere.kind, "section");
  assert.equal(next.elsewhere.id, "seksyen-25");
});

test("a point of the city in no section is titled with the city, with nothing to open", () => {
  const header = pointHeader(cityPoint(null), CITY_AREA, CITY_LIST);
  assert.equal(header.title, "Point in Shah Alam, Selangor");
  assert.equal(header.elsewhere, null);
});

test("a point in a section of another listed city offers that city, not the section", () => {
  const header = pointHeader(cityPoint(), HOME, CITY_LIST);
  assert.equal(header.title, "Point in Seksyen 25, Shah Alam");
  assert.equal(header.elsewhere.kind, "area");
  assert.equal(header.elsewhere.id, "shah-alam");
});
