// Run from 11_Platform_Draft:  node --test tests/flood3d.test.mjs
// The 3D page's data side (app/static/js/flood3d-data.js): reading a link, finding its shop through the API, and a
// section's bundle turned into the buildings and water the map draws. The bundle here is made by hand, small enough to
// check by eye; its corners are written to 6 decimals, as the flood model's squares are in town.json.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_PLACE, NEAR_M, contains, decodeBuildings, depthsAt, findShop, isBundle, metresApart, metresToRing, middle,
  readLink, scene, shopBuilding, waterGrid,
} from "../app/static/js/flood3d-data.js";

const SIZE = 0.0008333333356347339;   // town.json's cell_deg: 1/1200 of a degree, as float32 left it
const LON0 = 101.5;
const LAT0 = 3.0;
const corner = (k, from) => Number((from + k * SIZE).toFixed(6));
/** A wet square k rows north and j columns east of the first, with its depths for 1 in 10, 20 and 50 years. */
const wet = (k, j, depths) => [corner(k, LAT0), corner(j, LON0), ...depths];
/** A building of a box from (x1, y1) to (x2, y2), in millionths of a degree from the origin. */
const box = (h, src, x1, y1, x2, y2) => [h, src, x1, y1, x2, y1, x2, y2, x1, y2];

const SHOP = { id: "node-7", name: "A Shop", lat: 3.0005, lon: 101.5005, depth_m: { 10: 1.27, 20: 1.42, 50: null } };
const BUNDLE = {
  version: 1, area: "home", section: "s-7", box: [101.49, 2.99, 101.51, 3.01], origin: [LON0, LAT0],
  buildings: [
    box(6.4, 0, 450, 450, 550, 550),       // the shop stands in it
    box(9.6, 1, 700, 450, 800, 550),       // its neighbour, in the same wet square
    box(6.4, 2, 2050, 1200, 2120, 1300),   // a guessed height, on a dry square about 195 m away
    box(3.2, 0, 6000, 450, 6100, 550),     // 610 m east: out of the view
    box(0, 0, 900, 900, 950, 950),         // no height
    [3.2, 0, 1, 2, 3, 4],                  // too few points
    [3.2, 0, 1, 2, 3, 4, 5, 6, 7],         // half a point
  ],
  cell_deg: SIZE, return_periods: [10, 20, 50],
  water: [wet(0, 0, [0.5, 0.6, 0.7]), wet(0, 1, [0.1, 0.2, 0.3]), wet(1, 0, [null, 0.2, 0.4]), wet(0, 8, [1, 1, 1])],
  credit: "Buildings © OpenStreetMap contributors", fetched_on: "2026-10-12",
};
const DRY = { d10: 0, d20: 0, d50: 0 };

// ---------- the link

test("a link from the card names the area, section, shop and flood size", () => {
  assert.deepEqual(readLink("?area=home&section=s-7&place=node-7&rp=50"), { area: "home", section: "s-7", place: "node-7", rp: "50" });
});

test("the first links (?place= alone) and a bare page still name a shop, with no section", () => {
  assert.deepEqual(readLink("?place=node-5565878632"), { area: null, section: null, place: "node-5565878632", rp: null });
  assert.deepEqual(readLink(""), { area: null, section: null, place: DEFAULT_PLACE, rp: null });
});

test("anything that is not an id or a flood size is dropped, and a bad place names no shop", () => {
  assert.deepEqual(readLink("?area=../x&section=Big%20Section&place=pt:3.1,101.5&rp=100"),
    { area: null, section: null, place: null, rp: null });
  assert.equal(readLink("?section=-s").section, null);
  assert.equal(readLink("?place=").place, null);
});

// ---------- finding the shop

/** An api.js stand-in that answers from `answers` by call and records each call. */
function fakeApi(answers) {
  const calls = [];
  const answer = (name) => (...args) => {
    calls.push([name, ...args]);
    const found = answers[name];
    return found instanceof Error ? Promise.reject(found) : Promise.resolve(typeof found === "function" ? found(...args) : found);
  };
  return { calls, getAreas: answer("getAreas"), getAreaData: answer("getAreaData"),
    getDefaultData: answer("getDefaultData"), getSectionData: answer("getSectionData") };
}
const SECTION_DATA = { area: { id: "home" }, section: { id: "s-7", name: "Section 7" }, premises: [{ id: "node-1" }, SHOP] };
const CITY_DATA = { area: { id: "home" }, index: [{ id: "node-1", section: "s-1" }, { id: "node-7", section: "s-7" }], premises: [] };
const FOUND = { areaId: "home", sectionId: "s-7", sectionName: "Section 7", shop: SHOP };

test("a card's link asks for its section's data alone", async () => {
  const api = fakeApi({ getSectionData: SECTION_DATA });
  assert.deepEqual(await findShop(readLink("?area=home&section=s-7&place=node-7"), api), FOUND);
  assert.deepEqual(api.calls, [["getSectionData", "home", "s-7"]]);
});

test("an old link finds the shop's section in the default area's index first", async () => {
  const api = fakeApi({ getDefaultData: CITY_DATA, getSectionData: SECTION_DATA });
  assert.deepEqual(await findShop(readLink("?place=node-7"), api), FOUND);
  assert.deepEqual(api.calls, [["getDefaultData"], ["getSectionData", "home", "s-7"]]);
});

test("a link with an area and no section looks in that area; one with a section and no area, in the default", async () => {
  const byArea = fakeApi({ getAreaData: CITY_DATA, getSectionData: SECTION_DATA });
  assert.deepEqual(await findShop(readLink("?area=home&place=node-7"), byArea), FOUND);
  assert.deepEqual(byArea.calls, [["getAreaData", "home"], ["getSectionData", "home", "s-7"]]);
  const bySection = fakeApi({ getAreas: { default: "home", areas: [] }, getSectionData: SECTION_DATA });
  assert.deepEqual(await findShop(readLink("?section=s-7&place=node-7"), bySection), FOUND);
  assert.deepEqual(bySection.calls, [["getAreas"], ["getSectionData", "home", "s-7"]]);
});

test("an old area id answers with its section's data, which is used as it is", async () => {
  const api = fakeApi({ getAreaData: SECTION_DATA });
  assert.deepEqual(await findShop(readLink("?area=old-town&place=node-7"), api), FOUND);
  assert.deepEqual(api.calls, [["getAreaData", "old-town"]]);
});

test("a shop the server does not hold, or a link with no shop, finds nothing", async () => {
  const api = fakeApi({ getDefaultData: CITY_DATA, getSectionData: SECTION_DATA });
  assert.equal(await findShop(readLink("?place=node-99"), api), null);   // in no section of the index
  assert.equal(await findShop(readLink("?area=home&section=s-7&place=node-99"), api), null);
  assert.equal(await findShop(readLink("?place=bad"), api), null);
  const plain = fakeApi({ getDefaultData: { area: { id: "home" }, premises: [SHOP] } });   // an area with no sections
  assert.equal(await findShop(readLink("?place=node-7"), plain), null);
});

test("a server that cannot be asked is the caller's to say", async () => {
  const api = fakeApi({ getSectionData: new Error("Unknown section.") });
  await assert.rejects(findShop(readLink("?area=home&section=s-9&place=node-7"), api), /Unknown section/);
});

// ---------- the bundle

test("a bundle needs its origin, buildings, water and square size", () => {
  assert.ok(isBundle(BUNDLE));
  for (const bad of [null, {}, { ...BUNDLE, version: 2 }, { ...BUNDLE, origin: [1] }, { ...BUNDLE, origin: [1, "2"] },
    { ...BUNDLE, buildings: null }, { ...BUNDLE, water: {} }, { ...BUNDLE, cell_deg: 0 }]) assert.ok(!isBundle(bad));
});

test("buildings decode to closed rings in degrees, and malformed rows are left out", () => {
  const found = decodeBuildings(BUNDLE);
  assert.equal(found.length, 4);
  const [shopHouse] = found;
  assert.equal(shopHouse.h, 6.4);
  assert.equal(shopHouse.src, 0);
  assert.equal(shopHouse.ring.length, 5);
  assert.deepEqual(shopHouse.ring[0], shopHouse.ring[4]);
  const expected = [[101.50045, 3.00045], [101.50055, 3.00045], [101.50055, 3.00055], [101.50045, 3.00055]];
  shopHouse.ring.slice(0, 4).forEach(([lon, lat], i) => {
    assert.ok(Math.abs(lon - expected[i][0]) < 1e-12 && Math.abs(lat - expected[i][1]) < 1e-12, `point ${i}`);
  });
  const [lon, lat] = middle(shopHouse.ring);
  assert.ok(Math.abs(lon - 101.5005) < 1e-12 && Math.abs(lat - 3.0005) < 1e-12);
});

test("a point takes the depths of the wet square under it, and 0 where none is", () => {
  const grid = waterGrid(BUNDLE);
  assert.deepEqual(depthsAt(grid, 101.5005, 3.0005), { d10: 0.5, d20: 0.6, d50: 0.7 });
  assert.deepEqual(depthsAt(grid, 101.5012, 3.0004), { d10: 0.1, d20: 0.2, d50: 0.3 });
  assert.deepEqual(depthsAt(grid, 101.5004, 3.0012), { d10: 0, d20: 0.2, d50: 0.4 });   // no number: 0
  assert.deepEqual(depthsAt(grid, 101.5012, 3.0012), DRY);                             // a dry square
  assert.deepEqual(depthsAt(grid, 101.4999, 3.0005), DRY);                             // west of every square
  assert.deepEqual(depthsAt(waterGrid({ ...BUNDLE, water: [] }), 101.5005, 3.0005), DRY);
});

test("depths follow the bundle's own order of flood sizes", () => {
  const grid = waterGrid({ ...BUNDLE, return_periods: [50, 10, 20], water: [wet(0, 0, [0.7, 0.5, 0.6])] });
  assert.deepEqual(depthsAt(grid, 101.5005, 3.0005), { d10: 0.5, d20: 0.6, d50: 0.7 });
});

test("a point on a written corner is in that corner's square, far from the first square too", () => {
  // every corner over 400 squares each way: each written to 6 decimals, so up to half a millionth of a degree off
  const far = Array.from({ length: 41 }, (_, i) => i * 10);
  const water = far.flatMap((k) => far.map((j) => wet(k, j, [k, j, 1])));
  const grid = waterGrid({ ...BUNDLE, water });
  for (const [south, west, k, j] of water) {
    assert.deepEqual(depthsAt(grid, west, south), { d10: k, d20: j, d50: 1 }, `the corner of square ${k}, ${j}`);
    assert.deepEqual(depthsAt(grid, west + SIZE / 2, south + SIZE / 2), { d10: k, d20: j, d50: 1 }, "its middle");
    assert.deepEqual(depthsAt(grid, west - 1e-5, south), DRY, "a metre west: the square before it, dry");
    assert.deepEqual(depthsAt(grid, west, south - 1e-5), DRY, "a metre south");
    assert.deepEqual(depthsAt(grid, west + SIZE - 1e-5, south + SIZE - 1e-5), { d10: k, d20: j, d50: 1 }, "inside its far corner");
  }
});

// ---------- the shop's building

const square = (lon, lat, half) =>
  [[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half], [lon - half, lat + half], [lon - half, lat - half]];

test("ray casting finds a point inside a ring and not one outside", () => {
  const ring = square(101.5, 3, 0.0001);
  assert.ok(contains(ring, 101.5, 3));
  assert.ok(!contains(ring, 101.5002, 3));
  assert.ok(!contains(ring, 101.5, 2.9998));
});

test("the distance to a ring is to its nearest wall, in metres", () => {
  const ring = square(101.5, 3, 0.0001);
  const east = metresToRing(ring, 101.5003, 3);   // 0.0002 degrees east of the east wall
  assert.ok(Math.abs(east - 0.0002 * 111_320 * Math.cos((3 * Math.PI) / 180)) < 0.01);
  assert.ok(Math.abs(metresApart([101.5, 3], [101.5, 3.001]) - 111.32) < 1e-9);
});

test("the shop's building is the one it stands in, else the nearest within 30 m, else none", () => {
  const near = square(101.5, 3, 0.0001);                // its east wall about 11 m from the shop at 101.5002
  const nearer = square(101.5004, 3, 0.0001);           // its west wall about 11 m the other way, a hair closer
  const holding = square(101.5002, 3, 0.00005);
  assert.equal(shopBuilding([near, holding], 3, 101.5002), 1);
  assert.equal(shopBuilding([near, square(101.5005, 3, 0.0001)], 3, 101.5002), 0);
  assert.equal(shopBuilding([near, nearer], 3, 101.50021), 1);
  const lonFar = 101.5001 + (NEAR_M + 1) / (111_320 * Math.cos((3 * Math.PI) / 180));
  assert.equal(shopBuilding([near], 3, lonFar), null);
  assert.equal(shopBuilding([], 3, 101.5), null);
});

// ---------- what the map draws

test("the scene keeps what is within the view, the shop's building wet to the shop's own depths", () => {
  const { buildings, water, hasShopBuilding } = scene(BUNDLE, SHOP);
  assert.ok(hasShopBuilding);
  const props = buildings.features.map((feature) => feature.properties);
  assert.deepEqual(props, [
    { h: 6.4, hsrc: "osm", guessed: false, shop: true, d10: 1.27, d20: 1.42, d50: 0 },
    { h: 9.6, hsrc: "google", guessed: false, shop: false, d10: 0.5, d20: 0.6, d50: 0.7 },
    { h: 6.4, hsrc: "guess", guessed: true, shop: false, d10: 0, d20: 0, d50: 0 },
  ]);
  assert.ok(buildings.features.every((feature) => feature.type === "Feature" && feature.geometry.type === "Polygon"));
  assert.equal(water.type, "FeatureCollection");
  assert.deepEqual(water.features.map((feature) => feature.properties), [
    { d10: 0.5, d20: 0.6, d50: 0.7 }, { d10: 0.1, d20: 0.2, d50: 0.3 }, { d10: 0, d20: 0.2, d50: 0.4 }]);   // not the far one
  const [first] = water.features[0].geometry.coordinates;
  assert.deepEqual(first, [[101.5, 3], [101.5 + SIZE, 3], [101.5 + SIZE, 3 + SIZE], [101.5, 3 + SIZE], [101.5, 3]]);
});

test("a smaller view keeps fewer buildings, and a shop with no building near says so", () => {
  assert.equal(scene(BUNDLE, SHOP, 100).buildings.features.length, 2);
  const away = { ...SHOP, lat: 3.004, lon: 101.5005 };   // 390 m north of every building
  const found = scene(BUNDLE, away);
  assert.ok(!found.hasShopBuilding);
  assert.ok(found.buildings.features.every((feature) => !feature.properties.shop));
});
