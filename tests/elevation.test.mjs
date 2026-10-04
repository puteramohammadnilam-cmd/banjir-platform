// Run from 11_Platform_Draft:  node --test tests/elevation.test.mjs
// The height of the ground (elevation.js): bands on whole metres, the words behind them, "not loaded" where the server
// has no height, and the fact in the My business tab with its limits.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createBusiness } from "../app/static/js/card.js";
import { elevationFact, elevationWords, riverBand } from "../app/static/js/elevation.js";
import { useLang } from "../app/static/js/i18n.js";
import en from "../app/static/js/strings/en.js";
import { installFakeDom } from "./fake_dom.mjs";
import { AREAS, HOME, point, shop } from "./point_fixtures.mjs";

const textOf = (node) => node.textContent;

test("bands go on the whole metres shown: under 1 m near, 1 to 3 m mid, more than 3 m high", () => {
  const cases = [[-4.2, "near"], [-0.4, "near"], [0, "near"], [0.4, "near"], [0.5, "mid"], [1, "mid"], [3, "mid"],
    [3.4, "mid"], [3.5, "high"], [12.7, "high"]];
  for (const [metres, band] of cases) assert.equal(riverBand(metres), band, String(metres));
  assert.equal(riverBand(null), null);
  assert.equal(riverBand(undefined), null);
});

test("the words give the band, then the surface and the river in whole metres", () => {
  useLang("en");
  assert.deepEqual(elevationWords({ ground_m: 6.5, above_river_m: 4.0 }), {
    value: en["business.elevationHigh"],
    note: "The surface is about 7 m above sea level. That is about 4 m above the nearest mapped river's level.",
  });
  assert.equal(elevationWords({ ground_m: 3.2, above_river_m: 1.6 }).value, en["business.elevationMid"]);
  const near = elevationWords({ ground_m: 2.1, above_river_m: -1.6 });
  assert.equal(near.value, en["business.elevationNear"]);
  assert.match(near.note, /about 2 m below the nearest mapped river's level\.$/);
  assert.match(elevationWords({ ground_m: 2.1, above_river_m: 0.3 }).note, /about level with the nearest mapped river\.$/);
});

test("no river within reach, a surface at sea level, and nothing loaded each say so", () => {
  useLang("en");
  assert.deepEqual(elevationWords({ ground_m: 40.2, above_river_m: null }),
    { value: "No mapped river within 3 km", note: "The surface is about 40 m above sea level." });
  assert.equal(elevationWords({ ground_m: -17.3, above_river_m: -19.9 }).note.split(". ")[0],
    en["business.elevationGroundLow"].replace(/\.$/, ""));
  for (const missing of [null, undefined]) {
    assert.deepEqual(elevationWords(missing),
      { value: "Not loaded for this spot yet", note: en["business.elevationNotLoadedNote"] });
  }
});

test("the fact carries the limits wherever it shows a height, and only there", () => {
  useLang("en");
  installFakeDom();
  const shown = elevationFact({ elevation: { ground_m: 6.5, above_river_m: 4.0 } });
  assert.equal(textOf(shown.querySelector(".fact-label")), "Height of the ground");
  assert.equal(textOf(shown.querySelector(".fineprint")), en["business.elevationLimits"]);
  assert.match(en["business.elevationLimits"], /roofs and trees/);
  assert.match(en["business.elevationLimits"], /may not be the one that floods here/);
  assert.match(en["business.elevationLimits"], /Not a survey/);
  assert.equal(elevationFact({ elevation: null }).querySelector(".fineprint"), null);
});

test("the My business tab shows the height for a business and 'not loaded' for a point without one, in Bahasa Melayu too", () => {
  installFakeDom();
  useLang("ms");
  const panel = document.createElement("section");
  const card = createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {} });
  card.render({ premise: { ...shop, elevation: { ground_m: 6.5, above_river_m: 4.0 } }, rp: "100" });
  assert.ok(panel.textContent.includes("Lebih 3 m di atas sungai terdekat"));
  card.render({ premise: point({ elevation: null }), rp: "100" });
  assert.ok(panel.textContent.includes("Belum dimuatkan untuk lokasi ini"));
  useLang("en");
});
