// Run from 11_Platform_Draft:  node --test tests/cells_layer.test.mjs
// The flood squares around a checked point (cells.js) against a fake Leaflet `L`. The squares come with the point, in the
// answer to POST /api/point (`blocks` and `cells`), so the layer asks the server for nothing: each square is drawn once on
// the canvas, painted for the flood size on show, kept for at most four neighbourhoods, and a square that is malformed is
// skipped. The real map is checked in the browser (checklist 6A).
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { SQUARES_FAILED, SQUARE_RAMP, createCellLayer, squareStyle, squaresOf } from "../app/static/js/cells.js";
import { BANDS, DRY_COLOR } from "../app/static/js/dom.js";

const GRID = { name: "N10_E100", px: 0.001, py: 0.002 };
const FLOOD_SIZES = ["10", "20", "50"];

class FakeRectangle {
  constructor(bounds, options) {
    Object.assign(this, { bounds, options, style: {}, map: null });
  }

  addTo(map) {
    this.map = map;
    map.layers.add(this);
    return this;
  }

  remove() {
    this.map?.layers.delete(this);
    this.map = null;
  }

  setStyle(style) {
    this.style = { ...this.style, ...style };
  }
}

let map;
let requested;    // every request made while a test runs: the layer makes none
let shown;        // the index of the flood size on show

beforeEach(() => {
  map = { layers: new Set() };
  requested = [];
  shown = 1;
  globalThis.L = { canvas: (options) => ({ kind: "canvas", options }), rectangle: (bounds, options) => new FakeRectangle(bounds, options) };
  globalThis.fetch = async (path) => {
    requested.push(path);
    throw new Error("the squares of a point come with it: nothing is asked for");
  };
});

const cell = (south, west, d10 = null, d100 = 0.5, d500 = 1.2) => [south, west, d10, d100, d500];
const layer = (isOwned) => createCellLayer(map, () => shown, isOwned);
const block = (bi, bj) => ({ grid: GRID.name, bi, bj });
const drawn = () => [...map.layers];

// ---------- what came with a point ----------

test("the squares that came with a point are its blocks and its cells, and nothing when the answer has none", () => {
  const blocks = [block(348, 77), block(348, 78)];
  const cells = [cell(3.0, 101.5, 0.5, 1.0, 2.0)];
  assert.deepEqual(squaresOf({ coverage: "covered", region: "peninsula", place: { id: "pt:3.02998,101.53667" }, blocks, cells }), { blocks, cells });
  assert.deepEqual(squaresOf({ blocks: [], cells: [] }), { blocks: [], cells: [] }, "a point with no water near it has blocks and no cells");
  for (const answer of [null, undefined, "x", {}, { blocks }, { cells }, { blocks: "x", cells }, { blocks, cells: {} }, { blocks: null, cells: null }]) {
    assert.equal(squaresOf(answer), null, JSON.stringify(answer));
  }
});

test("a covered point whose squares the server could not read is marked failed, not taken for dry land", () => {
  const answer = { coverage: "covered", region: "peninsula", place: { id: "pt:3.02998,101.53667" }, blocks: null, cells: null };
  assert.equal(squaresOf(answer), SQUARES_FAILED);
  assert.equal(squaresOf({ ...answer, coverage: "outside" }), null, "a spot that was not checked has no squares to fail");
  assert.equal(squaresOf({ coverage: "covered", place: null }), null, "no keys at all is not a failure the server reported");
});

// ---------- drawing ----------

test("a wet square is a rectangle on the canvas, one square wide and high, painted for the flood size on show", () => {
  const squares = layer();
  assert.equal(squares.show(GRID, [block(1, 1)], [cell(3.0, 101.5, 0.5, 1.0, 2.0)]), 1);
  const [only] = drawn();
  assert.deepEqual(only.bounds, [[3.0, 101.5], [3.0 + GRID.py, 101.5 + GRID.px]]);
  assert.equal(only.options.stroke, false);
  assert.equal(only.options.interactive, false);
  assert.equal(only.options.renderer.kind, "canvas", "one canvas for all of them, not an element each");
  assert.equal(only.options.fillColor, SQUARE_RAMP[1].color, "1.0 m at the second flood size is the second step");
  assert.equal(only.options.fillOpacity, SQUARE_RAMP[1].opacity);
});

test("the squares' ramp has a step for each depth band, on the same thresholds, darker and thicker with depth", () => {
  assert.equal(SQUARE_RAMP.length, BANDS.length);
  SQUARE_RAMP.forEach((step, i) => {
    assert.equal(step.below, BANDS[i].below, `step ${i + 1} changes at the depth the dots' band does`);
    if (i) assert.ok(step.opacity > SQUARE_RAMP[i - 1].opacity, `step ${i + 1} is laid thicker than the one before`);
  });
  assert.ok(SQUARE_RAMP.every((step) => !BANDS.some((b) => b.color === step.color)), "the squares do not borrow the dots' colours");
});

test("a square is painted the step of its depth for the flood size on show, and clear when it is dry there", () => {
  assert.deepEqual(squareStyle([null, 0, 0.5], 0), { fillColor: DRY_COLOR, fillOpacity: 0 });
  assert.deepEqual(squareStyle([null, 0, 0.5], 2), { fillColor: SQUARE_RAMP[0].color, fillOpacity: SQUARE_RAMP[0].opacity });
  assert.deepEqual(squareStyle([1, 2, 3.5], 5), { fillColor: DRY_COLOR, fillOpacity: 0 }, "a flood size that is not there is dry");
  const depths = [0.5, 1.0, 1.8, 2.5, 3.5];   // one in each band
  depths.forEach((_, i) => assert.deepEqual(squareStyle(depths, i), { fillColor: SQUARE_RAMP[i].color, fillOpacity: SQUARE_RAMP[i].opacity }, `band ${i + 1}`));
});

test("all the squares of a neighbourhood's blocks are drawn together, and no request is made", () => {
  const squares = layer();
  const wet = squares.show(GRID, [block(10, 20), block(10, 21), block(11, 20), block(11, 21)],
    [cell(3.0, 101.0), cell(3.1, 101.0), cell(3.0, 101.1), cell(3.2, 101.1)]);
  assert.equal(wet, 4);
  assert.equal(drawn().length, 4);
  assert.deepEqual(requested, []);
});

test("a point with no water near it draws nothing and says so with zero", () => {
  assert.equal(layer().show(GRID, [block(1, 1), block(1, 2)], []), 0);
  assert.equal(drawn().length, 0);
});

test("a square two neighbourhoods share is drawn once", () => {
  const squares = layer();
  squares.show(GRID, [block(1, 1)], [cell(3.0, 101.0), cell(3.0, 101.1)]);
  squares.show(GRID, [block(1, 2)], [cell(3.0, 101.1), cell(3.0, 101.2)]);
  assert.equal(drawn().length, 3);
});

test("showing a neighbourhood again draws nothing twice and still says how many squares are wet", () => {
  const squares = layer();
  const cells = [cell(3.0, 101.0), cell(3.0, 101.1)];
  assert.equal(squares.show(GRID, [block(1, 1)], cells), 2);
  assert.equal(squares.show(GRID, [block(1, 1)], cells), 2);
  assert.equal(drawn().length, 2);
});

test("the blocks a neighbourhood is named by are what tell it from another, in whatever order they come", () => {
  const squares = layer();
  const cells = [cell(3.0, 101.0)];
  squares.show(GRID, [block(1, 1), block(1, 2)], cells);
  squares.show(GRID, [block(1, 2), block(1, 1)], cells);
  assert.equal(drawn().length, 1);
  squares.show({ ...GRID, name: "N10_E110" }, [block(1, 1), block(1, 2)], [cell(3.0, 101.0)]);
  assert.equal(drawn().length, 2, "the same block numbers in another grid are another neighbourhood, with squares of its own");
});

test("a square something else draws already is counted as wet but not drawn a second time", () => {
  const owned = (grid, south, west) => west < 101.15;
  const squares = layer(owned);
  assert.equal(squares.show(GRID, [block(1, 1)], [cell(3.0, 101.0), cell(3.0, 101.1), cell(3.0, 101.2)]), 3, "the point has wet squares near it, whoever draws them");
  assert.deepEqual(drawn().map((rectangle) => rectangle.bounds[0][1]), [101.2]);
});

// ---------- keeping the last four neighbourhoods ----------

test("at most four neighbourhoods stay on the map, and the oldest squares go first", () => {
  const squares = layer();
  const show = (at) => squares.show(GRID, [block(at, at)], [cell(at, 101.0), cell(at, 101.1)]);   // south = which neighbourhood
  for (let at = 1; at <= 4; at += 1) show(at);
  assert.equal(drawn().length, 8);
  show(5);
  const souths = drawn().map((rectangle) => rectangle.bounds[0][0]).sort((a, b) => a - b);
  assert.deepEqual(souths, [2, 2, 3, 3, 4, 4, 5, 5], "the fifth came, and the first one's two squares went");
});

test("a square that a newer neighbourhood still holds stays when the older one that held it goes", () => {
  const squares = layer();
  squares.show(GRID, [block(1, 1)], [cell(3.0, 101.0), cell(3.0, 101.1)]);
  squares.show(GRID, [block(2, 2)], [cell(3.0, 101.1)]);
  for (let at = 3; at <= 5; at += 1) squares.show(GRID, [block(at, at)], [cell(4.0 + at, 101.0)]);
  const west = drawn().filter((rectangle) => rectangle.bounds[0][0] === 3.0).map((rectangle) => rectangle.bounds[0][1]);
  assert.deepEqual(west, [101.1], "101.0 left with the first neighbourhood, 101.1 stays with the second");
});

// ---------- when the answer is not what it should be ----------

test("a square that is malformed is skipped and the rest are drawn", () => {
  const squares = layer();
  const wet = squares.show(GRID, [block(1, 1)], [cell(3.0, 101.0), [3.0], ["x", 101.1, 1, 1, 1], null, cell(3.0, 101.2)]);
  assert.equal(wet, 2);
  assert.equal(drawn().length, 2);
});

test("blocks or cells that are not lists draw nothing and ask for nothing", () => {
  const squares = layer();
  assert.equal(squares.show(GRID, [block(1, 1)], "none"), 0);
  assert.equal(squares.show(GRID, "none", [cell(3.0, 101.0)]), 0);
  assert.equal(drawn().length, 0);
  assert.deepEqual(requested, []);
});

// ---------- the flood size on show ----------

test("changing the flood size repaints every square on the map, and squares drawn after it are painted for it", () => {
  const squares = layer();
  squares.show(GRID, [block(1, 1)], [cell(3.0, 101.0, 0.5, 1.0, 2.5)]);
  assert.equal(drawn()[0].options.fillColor, SQUARE_RAMP[1].color);
  shown = 2;
  squares.restyle();
  assert.equal(drawn()[0].style.fillColor, SQUARE_RAMP[3].color, "2.5 m is over the door");
  assert.equal(drawn()[0].style.fillOpacity, SQUARE_RAMP[3].opacity);
  squares.show(GRID, [block(2, 2)], [cell(3.1, 101.0, 0.5, 1.0, 2.5)]);
  assert.equal(drawn()[1].options.fillColor, SQUARE_RAMP[3].color);
  assert.equal(FLOOD_SIZES[shown], "50");
  assert.deepEqual(requested, []);
});
