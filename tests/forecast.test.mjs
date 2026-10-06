// Run from 11_Platform_Draft:  node --test tests/forecast.test.mjs
// "River forecast" (forecast.js): a link to Google Flood Hub at the place, rounded to about 1 km.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { floodHubLink, forecastFact } from "../app/static/js/forecast.js";
import { installFakeDom } from "./fake_dom.mjs";
import { point, shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

test("the link is Flood Hub's map at the place rounded to two decimals, never the exact point", () => {
  assert.equal(floodHubLink(point()), "https://sites.research.google/floods/l/3.03/101.54/11");
  assert.doesNotMatch(floodHubLink(point()), /3\.02998|101\.53667/);
  assert.equal(floodHubLink({}), null);
});

test("the card names Google Flood Hub, links to it, and says it is not an official warning", () => {
  const fact = forecastFact({ ...shop, lat: 3.0256, lon: 101.5421 });
  assert.match(fact.textContent, /River forecast.*Google Flood Hub.*See Google's forecast near here/);
  assert.match(fact.textContent, /not a flood warning/);
  assert.equal(fact.querySelector("a").getAttribute("rel"), "noopener noreferrer");
  assert.equal(forecastFact({ name: "no place" }), null);
});
