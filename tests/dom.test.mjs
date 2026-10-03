// Run from 11_Platform_Draft:  node --test tests/dom.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { BANDS, band, chanceWithin, depthWords } from "../app/static/js/dom.js";
import { floodCounts, tickYears } from "../app/static/js/history.js";

// The floods are an area's data, not the page's: area.json is what GET /api/areas/{id}/data sends as `area`.
const SRI_MUDA = JSON.parse(readFileSync(new URL("../app/data/areas/sri-muda/area.json", import.meta.url), "utf8"));
const HISTORY = SRI_MUDA.history;

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
  for (const flood of HISTORY.floods) {
    assert.ok(flood.when && flood.what && flood.source, flood.when);
    assert.ok(flood.year >= HISTORY.first_year && flood.year < HISTORY.last_year + 1, flood.when);
  }
  assert.deepEqual(HISTORY.floods.map((f) => f.year), [...HISTORY.floods.map((f) => f.year)].sort((a, b) => a - b));
  assert.equal(HISTORY.floods.filter((f) => !f.account).length, 9);   // dated reports; one undated account is kept apart
});

test("the counts come from the area's own record, with an undated account left out", () => {
  assert.deepEqual(floodCounts(HISTORY), { dated: 9, recent: 7, since: 1995, recentFrom: 2019 });
  const other = { first_year: 2010, recent_from: 2020, last_year: 2026, floods: [
    { when: "2012", year: 2012.5, account: true, what: "A memory.", source: "One person" },
    { when: "May 2020", year: 2020.4, what: "A flood.", source: "A paper" },
    { when: "2024", year: 2024.1, what: "Another.", source: "A paper" },
  ] };
  assert.deepEqual(floodCounts(other), { dated: 2, recent: 2, since: 2010, recentFrom: 2020 });
  assert.equal(HISTORY.floods.length, 10, "counting does not change the record");
});

test("an area with no flood record collected has no counts, whatever form that takes", () => {
  const noRecord = [null, undefined, {}, { first_year: 2000, recent_from: 2019, last_year: 2026, floods: [] }];
  for (const history of noRecord) assert.equal(floodCounts(history), null, JSON.stringify(history));
});

test("the strip is labelled every 5 years from a round year, and every 10 for a long record", () => {
  assert.deepEqual(tickYears(HISTORY.first_year, HISTORY.last_year), [1995, 2000, 2005, 2010, 2015, 2020, 2025]);
  assert.deepEqual(tickYears(2003, 2026), [2005, 2010, 2015, 2020, 2025]);
  assert.deepEqual(tickYears(1900, 2026), [1900, 1910, 1920, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]);
  assert.deepEqual(tickYears(2026, 2026), []);
});
