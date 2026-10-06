// Run from 11_Platform_Draft:  node --test tests/car.test.mjs
// "Where to move your car" (car.js): the nearest street the model keeps dry, or the place's own street, or none near.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { carFact, directionWords } from "../app/static/js/car.js";
import { installFakeDom } from "./fake_dom.mjs";
import { point, shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

const spot = { lat: 3.02579, lon: 101.54278, road: "Jalan Dua", distance_m: 80, bearing: 74 };
const spots = { 10: spot, 20: spot, 50: { ...spot, road: null }, credit: "Streets: OSM." };

test("bearings become the eight compass words", () => {
  assert.deepEqual([0, 44, 74, 180, 300, 359].map(directionWords), ["north", "north-east", "east", "south", "north-west", "north"]);
});

test("a shop whose street gets water is sent to the nearest dry street, with directions", () => {
  const fact = carFact(shop, "50", { spots });   // the shop's road has 0.9 m in a 1 in 50
  assert.match(fact.textContent, /80 m away east/);
  assert.match(fact.textContent, /keeps dry in a 1 in 50 years flood: a street with no name\./);
  const link = fact.querySelector("a");
  assert.equal(link.getAttribute("href"), "https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=3.02579,101.54278");
  assert.match(fact.textContent, /Streets: OSM\./);
  assert.match(fact.querySelector(".car-warning").textContent, /never drive through water/);
});

test("a business with no street on the map is not taken as dry: it gets the nearest dry street", () => {
  assert.match(carFact({ ...shop, road: null }, "20", { spots }).textContent, /80 m away east.*Jalan Dua/);
});

test("a street with no water says so, and none near says to move early", () => {
  const dryRoad = { ...shop, road: { ...shop.road, depth_m: { 10: null, 20: null, 50: null } } };
  assert.match(carFact(dryRoad, "50", { spots }).textContent, /No water on your street in the model.*does not model drains/);
  assert.match(carFact(point({ depth_m: { 10: null, 20: null, 50: null } }), "50", { spots }).textContent, /No water at this spot in the model/);
  const fact = carFact(point(), "50", { spots: { 10: null, 20: null, 50: null, credit: "c" } });
  assert.match(fact.textContent, /No dry street near.*Move cars out early/);
  assert.equal(fact.getAttribute("data-tone"), "high");
});

test("while it is asked, after an error, and for an area without spots", () => {
  assert.match(carFact(shop, "50", { busy: true }).textContent, /Finding the nearest dry street/);
  assert.match(carFact(shop, "50", { error: "Too many requests." }).textContent, /Too many requests\./);
  assert.equal(carFact(shop, "50", { spots: null }), null);
  assert.equal(carFact(shop, "50", undefined), null);
});
