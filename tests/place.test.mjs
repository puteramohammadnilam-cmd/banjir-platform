// Run from 11_Platform_Draft:  node --test tests/place.test.mjs
// The expected point ids below were worked out by app/places.py snap() on the shipped N10_E100 files:
//   .venv/bin/python -c "from app import places; s = places.snap(3.0297599, 101.5364982); print(s.id, s.row, s.col)"
import assert from "node:assert/strict";
import { test } from "node:test";

import { TABS, businessPlace, isPoint, parseRef, pointId, readUrl, snapToGrid, writeUrl } from "../app/static/js/place.js";

// GET /api/coverage `grids`, as the server sends them for the shipped files.
const E100 = { name: "N10_E100", x0: 99.97625154437965, y0: 10.00706666666666, px: 0.0008333333356347339, py: 0.0008333333333325754, rows: 11999, cols: 11999 };
const GRIDS = [E100];
const ANETAS = "pt:3.02998,101.53667";   // the square of the business at 3.0297599, 101.5364982: 1.88 m at 1 in 100

/** Split a link written by writeUrl the way the browser would: {search, hash}. */
const asLocation = (link) => {
  const url = new URL(link, "https://example.test/");
  return { search: url.search, hash: url.hash };
};

test("business and point ids parse, and a point id is formatted with 5 decimals", () => {
  assert.deepEqual(parseRef("node-13414432501"), { kind: "business", id: "node-13414432501" });
  assert.deepEqual(parseRef("way-1"), { kind: "business", id: "way-1" });
  assert.deepEqual(parseRef("relation-1234567890123456789"), { kind: "business", id: "relation-1234567890123456789" });
  assert.deepEqual(parseRef(ANETAS), { kind: "point", id: ANETAS, lat: 3.02998, lon: 101.53667 });
  assert.deepEqual(parseRef("pt:-1.50000,-101.25000"), { kind: "point", id: "pt:-1.50000,-101.25000", lat: -1.5, lon: -101.25 });
  assert.equal(pointId(3.029983333339672, 101.53666821535569), ANETAS);
  assert.equal(pointId(1.5, 103.9), "pt:1.50000,103.90000");
  assert.equal(parseRef(pointId(1.72665, 103.9)).id, "pt:1.72665,103.90000");
});

test("anything else is not a place id", () => {
  const bad = [
    null, undefined, 42, {}, [], "", " ", "node-", "node-12a", "Node-1", "shop-1", "node-12345678901234567890",
    " node-1", "node-1 ", "node-1\n", "pt:", "pt:3.0299,101.53667", "pt:3.029980,101.53667", "pt:3.02998,101.5366",
    "pt:3.02998;101.53667", "pt:3.02998, 101.53667", "PT:3.02998,101.53667", "pt:123.00000,1.00000",
    "pt:91.00000,101.00000", "pt:3.00000,181.00000", "pt:3.02998,1015.36670", "pt:+3.02998,101.53667",
    "pt:3.02998,101.53667#x", "javascript:alert(1)", "pt:NaN,101.53667", "pt:٣.02998,101.53667",
  ];
  for (const ref of bad) assert.equal(parseRef(ref), null, JSON.stringify(ref));
});

test("isPoint takes an id or a place", () => {
  assert.equal(isPoint(ANETAS), true);
  assert.equal(isPoint("node-1"), false);
  assert.equal(isPoint("pt:bad"), false);
  assert.equal(isPoint(null), false);
  assert.equal(isPoint({ id: ANETAS, is_point: true }), true);
  assert.equal(isPoint({ id: "node-1", is_point: false }), false);
  assert.equal(isPoint(businessPlace({ id: "node-1", name: "A" }, "sri-muda")), false);
});

test("a business from premises.json takes the server's Place shape", () => {
  const premise = { id: "node-1", name: "A shop", depth_m: { 10: null, 100: 0.5, 500: 1 } };
  const place = businessPlace(premise, "kota-tinggi");
  assert.deepEqual(place, { ...premise, is_point: false, area_id: "kota-tinggi", cell: null });
  assert.notEqual(place, premise);
  assert.equal("is_point" in premise, false, "the premise itself is not changed");
});

test("snapping agrees with app/places.py on fixed coordinates", () => {
  const cases = [   // [lat, lon, id, row, col] from places.snap()
    [3.0297599, 101.5364982, ANETAS, 8372, 1872],                  // a Taman Sri Muda business
    [3.1478, 101.6953, "pt:3.14748,101.69500", 8231, 2062],        // central Kuala Lumpur
    [1.7267455, 103.8999676, "pt:1.72665,103.90000", 9936, 4708],  // a Kota Tinggi business
    [5.4141, 100.3288, "pt:5.41415,100.32917", 5511, 423],         // George Town
    [1.55, 109.9, "pt:1.54998,109.90000", 10148, 11908],           // western Sarawak, still inside the E100 file
    [10.00706666666666, 99.97625154437965, "pt:10.00665,99.97667", 0, 0],   // the grid's north-west corner
  ];
  for (const [lat, lon, id, row, col] of cases) {
    const snap = snapToGrid(lat, lon, GRIDS);
    assert.deepEqual({ id: snap.id, row: snap.row, col: snap.col, grid: snap.grid }, { id, row, col, grid: "N10_E100" }, `${lat}, ${lon}`);
  }
});

test("a point on a square's edge goes east and south, to the last bit, as in Python", () => {
  const cases = [   // edges built as y0 - 8400 * py and x0 + 1850 * px, then moved by one or two units in the last place
    [3.007066666673026, 101.5364982, "pt:3.00665,101.53667", 8400, 1872],    // on the edge: the square to the south
    [3.007066666673027, 101.5364982, "pt:3.00748,101.53667", 8399, 1872],    // two steps north: the square to the north
    [3.0297599, 101.51791821530391, "pt:3.02998,101.51833", 8372, 1850],     // on the edge: the square to the east
    [3.0297599, 101.5179182153039, "pt:3.02998,101.51750", 8372, 1849],      // one step west: the square to the west
    [3.199567, 101.5364982, "pt:3.19998,101.53667", 8168, 1872],             // a town.json edge, rounded to 6 decimals
  ];
  for (const [lat, lon, id, row, col] of cases) {
    const snap = snapToGrid(lat, lon, GRIDS);
    assert.deepEqual([snap.id, snap.row, snap.col], [id, row, col], `${lat}, ${lon}`);
  }
});

test("the snapped centre snaps back to the same square, and its id reads back as the centre", () => {
  const first = snapToGrid(3.0297599, 101.5364982, GRIDS);
  assert.deepEqual([first.lat, first.lon], [3.029983333339672, 101.53666821535569]);
  const again = snapToGrid(first.lat, first.lon, GRIDS);
  const fromId = snapToGrid(parseRef(first.id).lat, parseRef(first.id).lon, GRIDS);
  assert.deepEqual([again.id, again.row, again.col], [first.id, first.row, first.col]);
  assert.deepEqual([fromId.id, fromId.row, fromId.col], [first.id, first.row, first.col]);
});

test("no square outside the loaded grids, and none for input that is not a number", () => {
  const south = E100.y0 - E100.rows * E100.py;
  const east = E100.x0 + E100.cols * E100.px;
  const outside = [[1.5535, 110.3593], [35.68, 139.69], [6.33, 99.84], [south, 101], [3, east], [10.1, 101]];
  for (const [lat, lon] of outside) assert.equal(snapToGrid(lat, lon, GRIDS), null, `${lat}, ${lon}`);
  const junk = [[NaN, 101.5], [3.02, NaN], [Infinity, 101.5], [3.02, -Infinity], ["3.02", "101.5"], [null, 101.5], [3.02, undefined]];
  for (const [lat, lon] of junk) assert.equal(snapToGrid(lat, lon, GRIDS), null, `${lat}, ${lon}`);
  assert.equal(snapToGrid(3.0297599, 101.5364982, []), null);
  assert.equal(snapToGrid(3.0297599, 101.5364982, undefined), null);
});

test("the first grid in coverage order that holds the point wins", () => {
  const east = { ...E100, name: "N10_E110", x0: E100.x0 + E100.cols * E100.px };
  const kuching = snapToGrid(1.5535, 110.3593, [E100, east]);
  assert.equal(kuching.grid, "N10_E110");
  const overlap = { ...E100, name: "AAA_overlap" };
  assert.equal(snapToGrid(3.0297599, 101.5364982, [overlap, E100]).grid, "AAA_overlap");
  assert.equal(snapToGrid(3.0297599, 101.5364982, [E100, overlap]).grid, "N10_E100");
});

const NOTHING = { area: null, place: null, tab: null, rp: null, lang: null, chat: false, pointInQuery: false };

test("an old ?shop= link names the place; tab and rp keep their old rules", () => {
  assert.deepEqual(readUrl({ search: "?tab=business&shop=node-13414432501&rp=500", hash: "" }),
    { ...NOTHING, place: "node-13414432501", tab: "business", rp: "500" });
  assert.deepEqual(readUrl({ search: "?shop=node-1", hash: "" }), { ...NOTHING, place: "node-1" });
  assert.deepEqual(readUrl({ search: "", hash: "" }), NOTHING);
  assert.deepEqual(readUrl({}), NOTHING);
});

test("the fragment's place comes first, then ?place=, then ?shop=", () => {
  assert.equal(readUrl({ search: "?place=node-2&shop=node-1", hash: "" }).place, "node-2");
  assert.equal(readUrl({ search: "?place=node-2&shop=node-1", hash: `#place=${ANETAS}` }).place, ANETAS);
  assert.equal(readUrl({ search: "", hash: "#place=pt%3A3.02998%2C101.53667" }).place, ANETAS);
  assert.equal(readUrl({ search: "?area=kota-tinggi", hash: "" }).area, "kota-tinggi");
});

test("a point is read only from the fragment: one in the query is flagged, never used", () => {
  assert.deepEqual(readUrl({ search: `?tab=business&place=${ANETAS}&rp=100`, hash: "" }),
    { ...NOTHING, tab: "business", rp: "100", pointInQuery: true });
  assert.deepEqual(readUrl({ search: "?shop=pt:3.0297599,101.5364982", hash: "" }), { ...NOTHING, pointInQuery: true },
    "anything that claims to be a point, even malformed, which may hold a precise position");
  assert.deepEqual(readUrl({ search: `?place=${ANETAS}`, hash: "#place=pt:1.72665,103.90000" }),
    { ...NOTHING, place: "pt:1.72665,103.90000", pointInQuery: true });
  assert.deepEqual(readUrl({ search: "?place=node-1&shop=pt:3.02998,101.53667", hash: "" }), { ...NOTHING, place: "node-1", pointInQuery: true });
  assert.deepEqual(readUrl({ search: "?place=pt:3.02998,101.53667&shop=node-1", hash: "" }), { ...NOTHING, place: "node-1", pointInQuery: true });
});

test("a link's tab and rp are kept only when valid; area and place are passed on to be checked", () => {
  const url = readUrl({ search: "?area=Nowhere&tab=admin&rp=50&place=<b>", hash: "#tab=cost" });
  assert.deepEqual(url, { ...NOTHING, area: "Nowhere", place: "<b>" });
  assert.deepEqual(readUrl({ search: "?area=&place=&tab=&rp=", hash: "#place=" }), NOTHING);
  for (const tab of TABS) assert.equal(readUrl({ search: `?tab=${tab}` }).tab, tab);
  assert.deepEqual(TABS, ["overview", "business", "cost"], "Ask AI is the floating chat, not a tab");
  for (const rp of ["10", "100", "500"]) assert.equal(readUrl({ search: `?rp=${rp}` }).rp, rp);
});

test("an old ?tab=ask link asks for the chat and no tab; the link written from it never carries it", () => {
  const url = readUrl({ search: "?area=sri-muda&tab=ask&place=node-1", hash: "" });
  assert.deepEqual(url, { ...NOTHING, area: "sri-muda", place: "node-1", chat: true });
  assert.equal(writeUrl({ ...url, tab: url.tab ?? "business" }), "?area=sri-muda&tab=business&place=node-1");
  assert.equal(readUrl({ search: "?tab=cost", hash: "" }).chat, false);
});

test("a business goes in the query; a point goes in the fragment and never in the query", () => {
  assert.equal(writeUrl({ area: null, tab: "overview", place: "node-13414432501", rp: "100" }), "?tab=overview&place=node-13414432501&rp=100");
  assert.equal(writeUrl({ area: "kota-tinggi", tab: "business", place: "node-1", rp: "10" }), "?area=kota-tinggi&tab=business&place=node-1&rp=10");
  assert.equal(writeUrl({ area: null, tab: "business", place: ANETAS, rp: "100" }), `?tab=business&rp=100#place=${ANETAS}`);
  assert.equal(writeUrl({ area: "kota-tinggi", tab: "cost", place: "pt:1.72665,103.90000", rp: "500" }), "?area=kota-tinggi&tab=cost&rp=500#place=pt:1.72665,103.90000");
  assert.equal(writeUrl({ tab: "overview", place: "javascript:alert(1)", rp: "100" }), "?tab=overview&rp=100");
  assert.equal(writeUrl({}), "?");
});

test("no point, wherever it is, puts a coordinate in the query", () => {
  for (let i = 0; i < 500; i += 1) {
    const lat = 1 + ((i * 7919) % 6000) / 1000;
    const lon = 100 + ((i * 104729) % 9000) / 1000;
    const snap = snapToGrid(lat, lon, GRIDS);
    const { search, hash } = asLocation(writeUrl({ area: "sri-muda", tab: "business", place: snap.id, rp: "100" }));
    assert.ok(!search.includes("pt") && !search.includes(snap.id.slice(3, 8)), search);
    assert.equal(readUrl({ search, hash }).place, snap.id);
  }
});

test("a link round-trips through the browser's URL", () => {
  const views = [
    { area: null, tab: "overview", place: "node-13414432501", rp: "100" },
    { area: "kota-tinggi", tab: "business", place: "node-11075038761", rp: "10" },
    { area: null, tab: "business", place: ANETAS, rp: "100" },
    { area: "kota-tinggi", tab: "cost", place: "pt:1.72665,103.90000", rp: "500" },
    { area: "kota-tinggi", tab: "cost", place: null, rp: "10" },
  ];
  for (const view of views) assert.deepEqual(readUrl(asLocation(writeUrl(view))), { lang: null, chat: false, ...view, pointInQuery: false }, JSON.stringify(view));
  const inMalay = { area: "kota-tinggi", tab: "business", place: ANETAS, rp: "100", lang: "ms" };
  assert.deepEqual(readUrl(asLocation(writeUrl(inMalay))), { ...inMalay, chat: false, pointInQuery: false });
});

test("the language is kept in a link when set, after the flood size and before a point's fragment", () => {
  assert.equal(writeUrl({ tab: "overview", place: "node-1", rp: "100", lang: "ms" }), "?tab=overview&place=node-1&rp=100&lang=ms");
  assert.equal(writeUrl({ tab: "business", place: ANETAS, rp: "10", lang: "ms" }), `?tab=business&rp=10&lang=ms#place=${ANETAS}`);
  assert.equal(writeUrl({ tab: "overview", rp: "100", lang: "en" }), "?tab=overview&rp=100&lang=en");
  assert.equal(writeUrl({ tab: "overview", rp: "100", lang: null }), "?tab=overview&rp=100", "no language: the reader's own choice applies");
  assert.equal(writeUrl({ tab: "overview", lang: "fr" }), "?tab=overview", "a language the page does not have is left out");
  assert.equal(readUrl({ search: "?lang=ms" }).lang, "ms");
  assert.equal(readUrl({ search: "?lang=en&tab=cost" }).lang, "en");
  for (const odd of ["fr", "MS", "", "ms-MY"]) assert.equal(readUrl({ search: `?lang=${odd}` }).lang, null, odd);
  const read = readUrl({ search: `?tab=business&place=${ANETAS}&rp=100&lang=ms`, hash: "" });
  assert.equal(writeUrl(read), "?tab=business&rp=100&lang=ms", "cleaning a point out of the query keeps the language");
});

test("writing a link again drops a point from the query, so the page can clean its address before any request", () => {
  const read = readUrl({ search: `?area=kota-tinggi&tab=business&place=${ANETAS}&rp=100`, hash: "" });
  assert.equal(writeUrl(read), "?area=kota-tinggi&tab=business&rp=100");
  const both = readUrl({ search: "?shop=pt:3.0297599,101.5364982", hash: "#place=pt:1.72665,103.90000" });
  assert.equal(writeUrl(both), "?#place=pt:1.72665,103.90000");
});
