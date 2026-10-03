// Run from 11_Platform_Draft:  node --test tests/dom.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { BANDS, band, chanceWithin, depthWords } from "../app/static/js/dom.js";
import { FLOODS } from "../app/static/js/history.js";

test("bands break at the counter, an adult's head, the door and a storey", () => {
  assert.deepEqual([null, 0, -0.1].map(band), [0, 0, 0]);
  assert.deepEqual([0.05, 0.89, 0.9, 1.64, 1.65, 2.09, 2.1, 2.99, 3, 5.95].map(band), [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]);
  assert.equal(BANDS.length, 5);
});

test("depth words follow an adult about 1.65 m tall", () => {
  assert.equal(depthWords(null), "no water in the model");
  assert.equal(depthWords(0.1), "ankle-deep");
  assert.equal(depthWords(1.35), "up to the neck");
  assert.equal(depthWords(1.88), "over an adult's head");
  assert.equal(depthWords(2.11), "over the top of a door");
  assert.equal(depthWords(5.05), "a storey or more");
});

test("chance of at least one flood in 10 years", () => {
  assert.deepEqual(["10", "100", "500"].map((rp) => Math.round(chanceWithin(Number(rp), 10) * 100)), [65, 10, 2]);
});

test("every recorded flood has a date, a year in range and a source, oldest first", () => {
  for (const flood of FLOODS) {
    assert.ok(flood.when && flood.what && flood.source, flood.when);
    assert.ok(flood.year >= 1995 && flood.year < 2027, flood.when);
  }
  assert.deepEqual(FLOODS.map((f) => f.year), [...FLOODS.map((f) => f.year)].sort((a, b) => a - b));
  assert.equal(FLOODS.filter((f) => !f.account).length, 9);   // dated reports; one undated account is kept apart
});
