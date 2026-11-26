// node --test tests/map-gl.test.mjs
// The new map preview (map.html): the link it reads, the GeoJSON it draws, where our water goes in the base map, the
// place card's badge, distances, search, totals, and the cards themselves in both languages.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { sectionCard, shopCard, summaryCard } from "../app/static/js/map-gl-card.js";
import { badge, depthRamp, distanceKm, nearestShelter, readMapLink, searchIndex, sectionsGeo, shopsGeo, squaresGeo,
  underRoads, wetShops, wetTotals } from "../app/static/js/map-gl-data.js";
import { installFakeDom } from "./fake_dom.mjs";

const SECTION = { id: "sec-1", name: "Section 1", bbox: [101.5, 3.0, 101.51, 3.01], outline: { type: "Polygon", coordinates: [] },
  counts: { businesses: 40, cells: 200, wet_cells: { 10: 0, 20: 10, 50: 50 }, wet_businesses: { 10: 0, 20: 4, 50: 12 } } };
const SHOP = { id: "node-1", name: "Kedai Satu", kind: "restaurant", sector: "eatery", section: "sec-1", lat: 3.03, lon: 101.53,
  depth_m: { 10: 1.35, 20: 1.54, 50: 1.76 }, road: { name: "a road with no name" }, map_last_edited: "2025-12-28" };
const SHELTERS = [{ name: "Far hall", lat: 3.1, lon: 101.6 }, { name: "Near school", lat: 3.031, lon: 101.531 }];
const LINKS = { details: "./?place=node-1", cost: "./?tab=cost", see3d: null, directions: "https://www.google.com/maps/dir/?api=1&destination=3.03,101.53" };
const text = (nodes) => nodes.map((node) => node?.textContent ?? "").join(" ");

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

test("the link keeps the main page's area, section, place and flood size, and adds the base map", () => {
  const link = readMapLink("?area=shah-alam&section=seksyen-25&place=node-1&rp=20&base=dark&tilt=1");
  assert.deepEqual([link.area, link.section, link.place, link.rp, link.base, link.tilt], ["shah-alam", "seksyen-25", "node-1", "20", "dark", true]);
});

test("a link without a flood size or with an unknown base map falls back to 1 in 50 years on the light map", () => {
  const link = readMapLink("?base=moon");
  assert.equal(link.rp, "50");
  assert.equal(link.base, "map");
  assert.equal(link.tilt, false);
});

test("sections carry their share of wet squares and wet businesses for each flood size", () => {
  const [feature] = sectionsGeo([SECTION, { ...SECTION, id: "no-shape", outline: null }]).features;
  assert.equal(sectionsGeo([SECTION]).features.length, 1);
  assert.deepEqual([feature.properties.s10, feature.properties.s20, feature.properties.s50], [0, 0.05, 0.25]);
  assert.deepEqual([feature.properties.w20, feature.properties.n], [4, 40]);
});

test("a square is a closed polygon its size, and a missing depth becomes -1 so the paint rule leaves it clear", () => {
  const [square] = squaresGeo([[3.0, 101.5, null, 0.4, 1.2]], 0.001).features;
  const ring = square.geometry.coordinates[0];
  assert.deepEqual(ring[0], ring[4]);
  assert.ok(Math.abs(ring[2][0] - 101.501) < 1e-9 && Math.abs(ring[2][1] - 3.001) < 1e-9);
  assert.deepEqual([square.properties.d10, square.properties.d20, square.properties.d50], [-1, 0.4, 1.2]);
});

test("shops without a position are left off the map", () => {
  const found = shopsGeo([SHOP, { ...SHOP, id: "node-2", lat: null }]);
  assert.deepEqual(found.features.map((f) => f.properties.id), ["node-1"]);
  assert.deepEqual(found.features[0].geometry.coordinates, [101.53, 3.03]);
});

test("the depth ramp reads the picked flood size and turns brighter-is-deeper on the dark maps", () => {
  const light = depthRamp("20", false);
  const dark = depthRamp("20", true);
  assert.deepEqual(light[1], ["get", "d20"]);
  assert.notDeepEqual(light.slice(4), dark.slice(4));
});

test("our water goes under the first building, road or name layer of a base map", () => {
  assert.equal(underRoads([{ id: "background" }, { id: "water" }, { id: "building", type: "fill" }, { id: "place", type: "symbol" }]), "building");
  assert.equal(underRoads([{ id: "background" }, { id: "place_city", type: "symbol" }]), "place_city");
  assert.equal(underRoads([{ id: "photo", type: "raster" }]), undefined);
});

test("the base map copies keep the layer our water goes under", () => {
  for (const name of ["positron", "dark"]) {
    const style = JSON.parse(readFileSync(new URL(`../app/static/vendor/openfreemap/${name}.json`, import.meta.url), "utf8"));
    assert.ok(underRoads(style.layers), name);
    assert.ok(Object.values(style.sources).some((source) => String(source.url ?? "").startsWith("https://tiles.openfreemap.org/")), name);
  }
});

test("the badge uses the main page's depth bands, and no water or a missing depth is dry", () => {
  assert.deepEqual([null, -1, 0, 0.2, 0.89, 1.0, 1.76, 2.5].map((d) => badge(d).tone), ["dry", "dry", "dry", "watch", "watch", "high", "deep", "deep"]);
  assert.deepEqual([0.5, 1.0, 1.76].map((d) => badge(d).key), ["band.1.words", "band.2.words", "band.3.words"]);
});

test("an area with no sections counts its wet shops itself", () => {
  const premises = [SHOP, { ...SHOP, id: "node-2", depth_m: { 10: null, 20: null, 50: null } }, { ...SHOP, id: "node-3", depth_m: {} }];
  assert.equal(wetShops(premises, "50"), 1);
});

test("the nearest relief centre is the closest by distance, and none listed gives null", () => {
  assert.equal(nearestShelter(SHOP, SHELTERS).shelter.name, "Near school");
  assert.equal(nearestShelter(SHOP, []), null);
  assert.ok(Math.abs(distanceKm({ lat: 0, lon: 0 }, { lat: 1, lon: 0 }) - 111.19) < 0.1);
});

test("search finds names holding the words typed, any case, and needs two letters", () => {
  const index = [{ id: "a", name: "Kedai Satu" }, { id: "b", name: "Restoran Dua" }, { id: "c", name: null }];
  assert.deepEqual(searchIndex(index, "SATU").map((e) => e.id), ["a"]);
  assert.deepEqual(searchIndex(index, "k"), []);
});

test("the totals add up wet businesses across sections for the flood size picked", () => {
  assert.deepEqual(wetTotals([SECTION, SECTION], "50"), { wet: 24, all: 80 });
});

test("a shop's card says the depth in words, lists each flood size and the nearest centre, and links on", () => {
  const nodes = shopCard(SHOP, { rp: "50", sectionName: "Section 1", shelters: SHELTERS, links: LINKS, onClose() {}, onShare() {} });
  const words = text(nodes);
  for (const want of ["Kedai Satu", "Over an adult's head", "about 1.8 m of water", "1.76 m", "1.35 m", "Near school", "Full details", "Directions",
    "2025-12-28", "straight line"]) {
    assert.ok(words.includes(want), want);
  }
  assert.ok(!words.includes("a road with no name"));
});

test("the card uses the server's nearest relief centre when the shop has one, and opens outside links safely", () => {
  const shop = { ...SHOP, shelter: { name: "Dewan Server", distance_m: 3773 } };
  const nodes = shopCard(shop, { rp: "50", sectionName: "", shelters: SHELTERS, links: LINKS });
  const words = text(nodes);
  assert.ok(words.includes("Dewan Server") && words.includes("3.8 km") && !words.includes("Near school"));
  const away = nodes.flatMap((node) => node.children ?? []).find((node) => node.getAttribute?.("target") === "_blank");
  assert.equal(away.getAttribute("rel"), "noopener noreferrer");
});

test("a dry shop's card says so, in Malay too", () => {
  const dry = { ...SHOP, depth_m: { 10: null, 20: null, 50: null } };
  assert.ok(text(shopCard(dry, { rp: "10", sectionName: "", shelters: [], links: LINKS })).includes("no water at this door"));
  useLang("ms");
  assert.ok(text(shopCard(dry, { rp: "10", sectionName: "", shelters: [], links: LINKS })).includes("Kering dalam model"));
});

test("a section's card gives its share of wet squares and its wet businesses", () => {
  const props = sectionsGeo([SECTION]).features[0].properties;
  const words = text(sectionCard(props, { rp: "50", link: "./?section=sec-1", onClose() {} }));
  assert.ok(words.includes("25% of squares wet") && words.includes("12 of its 40 businesses"));
  const tiny = { ...props, s50: 0.003 };
  assert.ok(text(sectionCard(tiny, { rp: "50", link: "./", onClose() {} })).includes("Under 1% of squares wet"));
});

test("the flood size card counts wet businesses and marks the size picked", () => {
  const nodes = summaryCard({ wet: 571, all: 2445, rp: "50", onPick() {} });
  assert.ok(text(nodes).includes("571 of 2,445"));
  assert.ok(text(nodes).includes("businesses get water in the model"));
  const sizes = nodes.find((node) => node.getAttribute?.("class") === "mg-rp");
  const picked = sizes.children.filter((button) => button.getAttribute("aria-pressed") === "true");
  assert.deepEqual(picked.map((button) => button.getAttribute("data-rp")), ["50"]);
});
