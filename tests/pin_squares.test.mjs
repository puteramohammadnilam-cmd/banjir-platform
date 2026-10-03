// Run from 11_Platform_Draft:  node --test tests/pin_squares.test.mjs
// The pin and the flood squares around a checked point (pin.js), under node:test, with the stand-ins of tests/pin_page.mjs.
// The squares come with the point, in the answer to POST /api/point (`blocks` and `cells`), so a point flow is one request
// and no block is asked for by an address that names the area; what is late is dropped.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { COVERAGE } from "./pin_dom.mjs";
import { BLOCKS, CELLS, KL, NORTH_OF_KL, SQUARES, SRI_MUDA, aim, covering, deferred, flush, placeAt, serve, setup } from "./pin_page.mjs";
import { SQUARES_FAILED, createCellLayer } from "../app/static/js/cells.js";

beforeEach(() => {
  serve(covering);
});

// ---------- the pin and the squares around it ----------

test("a point that is the selected place gets its pin once, and the squares that came with it, drawn without a request", async () => {
  const page = setup();
  const asked = serve(() => { throw new Error("nothing is asked for: the squares came with the point"); });
  const place = placeAt(...KL);
  page.pin.render({ tab: "business", place, squares: SQUARES });
  await flush();
  assert.deepEqual(page.map.calls.filter(([name]) => name === "showPoint"), [["showPoint", place.id]]);
  assert.deepEqual(page.map.calls.find(([name]) => name === "showSquares"), ["showSquares", "N10_E100", 2, 2]);
  assert.equal(page.squaresSay(), "");
  page.pin.render({ tab: "business", place, squares: SQUARES });
  page.pin.render({ tab: "cost", place, squares: SQUARES });
  await flush();
  assert.equal(page.map.count("showPoint"), 1, "the same point is not dropped again");
  assert.equal(page.map.count("showSquares"), 1);
  assert.deepEqual(asked, []);
});

test("a point inside the area's own view gets a pin but no squares, as the area draws them", async () => {
  const page = setup();
  page.pin.render({ tab: "business", place: placeAt(...SRI_MUDA), squares: SQUARES });
  await flush();
  assert.equal(page.map.count("showPoint"), 1);
  assert.equal(page.map.count("showSquares"), 0);
  assert.equal(page.squaresSay(), "");
});

test("a point that came with no squares gets its pin and says nothing about squares", async () => {
  const page = setup();
  page.pin.render({ tab: "business", place: placeAt(...KL), squares: null });
  page.pin.render({ tab: "business", place: placeAt(...NORTH_OF_KL) });
  await flush();
  assert.equal(page.map.count("showPoint"), 2);
  assert.equal(page.map.count("showSquares"), 0);
  assert.equal(page.squaresSay(), "");
});

test("a business, and a point that is not a usable Place, get no pin", async () => {
  const page = setup();
  const point = placeAt(...KL);
  const broken = [null, undefined, { id: "node-13414432501", is_point: false, lat: 3.02, lon: 101.53 },
    { ...point, cell: null }, { ...point, cell: { ...point.cell, bounds: [1, 2, 3] } }, { ...point, id: "pt:bad" }, { ...point, lat: NaN }];
  for (const place of broken) page.pin.render({ tab: "business", place, squares: SQUARES });
  await flush();
  assert.equal(page.map.count("showPoint"), 0);
  assert.equal(page.map.count("showSquares"), 0);
});

test("the squares line says when there are none near the point, and nothing when there are some", async () => {
  const page = setup();
  page.map.wet = 0;
  page.pin.render({ tab: "business", place: placeAt(...KL), squares: SQUARES });
  await flush();
  assert.equal(page.squaresSay(), "No flood squares near this point in the model");
  page.map.wet = 12;
  page.pin.render({ tab: "business", place: placeAt(...NORTH_OF_KL), squares: SQUARES });
  await flush();
  assert.equal(page.squaresSay(), "", "the note was about the point before");
});

test("a point whose blocks hold no wet squares says there are none near it", async () => {
  const page = setup();
  page.pin.render({ tab: "business", place: placeAt(...KL), squares: { blocks: BLOCKS, cells: [] } });
  await flush();
  assert.deepEqual(page.map.calls.find(([name]) => name === "showSquares"), ["showSquares", "N10_E100", 2, 0]);
  assert.equal(page.squaresSay(), "No flood squares near this point in the model");
});

test("a point whose squares the server could not read gets its pin and says the squares could not load", async () => {
  const page = setup();
  page.pin.render({ tab: "business", place: placeAt(...KL), squares: SQUARES_FAILED });
  await flush();
  assert.equal(page.map.count("showPoint"), 1);
  assert.equal(page.map.count("showSquares"), 0);
  assert.equal(page.squaresSay(), "Flood squares could not load.");
  assert.equal(page.squares.querySelector("button"), null, "no Retry: asking again reads the same damaged file");
  page.pin.render({ tab: "business", place: placeAt(...NORTH_OF_KL), squares: SQUARES });
  await flush();
  assert.equal(page.squaresSay(), "", "the next point's squares replace the failure");
});

test("a point inside the area's own view says nothing about squares that failed, as the area draws its own", async () => {
  const page = setup();
  page.pin.render({ tab: "business", place: placeAt(...SRI_MUDA), squares: SQUARES_FAILED });
  await flush();
  assert.equal(page.squaresSay(), "");
});

test("when the coverage cannot be had the squares fail in words, with Retry, and the pin does not need it", async () => {
  let works = false;
  const page = setup({ getCoverage: async () => { if (!works) throw new Error("offline"); return COVERAGE; } });
  page.pin.render({ tab: "business", place: placeAt(...KL), squares: SQUARES });
  await flush();
  assert.equal(page.map.count("showPoint"), 1, "the pin does not need the coverage");
  assert.equal(page.map.count("showSquares"), 0);
  assert.ok(page.squaresSay().startsWith("Flood squares could not load."));
  const retry = page.squares.querySelector("button");
  assert.equal(retry.textContent, "Retry");
  works = true;
  retry.click();
  await flush();
  assert.equal(page.map.count("showSquares"), 1);
  assert.equal(page.squaresSay(), "");
});

test("a later point has its own squares: an older one still waiting for the coverage draws nothing and says nothing", async () => {
  const slow = deferred();
  let asks = 0;
  const page = setup({ getCoverage: () => (asks++ === 0 ? slow.promise : Promise.resolve(COVERAGE)) });
  page.pin.render({ tab: "business", place: placeAt(...KL), squares: SQUARES });            // waits for the coverage
  page.pin.render({ tab: "business", place: placeAt(...NORTH_OF_KL), squares: SQUARES });   // asks again, and has it at once
  await flush();
  assert.equal(page.map.count("showSquares"), 1);
  slow.resolve(COVERAGE);
  await flush();
  assert.equal(page.map.count("showSquares"), 1, "the old point's squares are not drawn after the new one's");
  assert.equal(page.squaresSay(), "");
});

test("a point checked in aim mode gets its pin through the page's own render, not from the flow", async () => {
  const page = setup();
  await aim(page);
  page.map.moveTo(...KL);
  page.check.click();
  await flush();
  assert.equal(page.checked.length, 1);
  assert.equal(page.map.count("showPoint"), 0, "the pin follows when the page shows the Place as its selected one");
  assert.equal(page.map.count("showSquares"), 0, "and so do the squares");
  page.pin.render({ tab: "business", place: page.checked[0], squares: page.squared[0] });
  await flush();
  assert.equal(page.map.count("showPoint"), 1);
  assert.equal(page.map.count("showSquares"), 1);
});

test("the whole of a point flow is one request, POST /api/point, and the map draws the squares of its answer", async () => {
  const rectangles = [];
  globalThis.L = {
    canvas: () => ({}),
    rectangle: (bounds, options) => ({ bounds, options, addTo(map) { rectangles.push(this); return this; }, remove() {} }),
  };
  try {
    const page = setup();
    const layer = createCellLayer({}, () => 1);   // the page's own layer, with a stand-in for Leaflet under it
    page.map.showSquares = (grid, blocks, cells) => layer.show(grid, blocks, cells);
    const asked = serve(covering);
    await aim(page);
    page.map.moveTo(...KL);
    page.check.click();
    await flush();
    page.pin.render({ tab: "business", place: page.checked[0], squares: page.squared[0] });
    page.pin.render({ tab: "cost", place: page.checked[0], squares: page.squared[0] });
    await flush();
    assert.deepEqual(asked.map(({ path }) => path), ["/api/point"], "no request for a block, whose address would name the area");
    assert.equal(rectangles.length, CELLS.length);
    assert.deepEqual(rectangles.map(({ bounds }) => bounds[0]), CELLS.map(([south, west]) => [south, west]));
  } finally {
    delete globalThis.L;
  }
});
