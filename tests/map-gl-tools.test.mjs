// node --test tests/map-gl-tools.test.mjs
// The new map's pin and engineer mode (map.html): its link keeps a point in the fragment, a point's square and card, a
// checked point the map can use, and engineer mode drawing through the new map's drawer. No network, no MapLibre.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createEngineer } from "../app/static/js/engineer.js";
import { useLang } from "../app/static/js/i18n.js";
import { pointCard } from "../app/static/js/map-gl-card.js";
import { squareOutline, squaresGeo, withMapView } from "../app/static/js/map-gl-data.js";
import { glDrawer, imageCorners, marksGeo } from "../app/static/js/map-gl-eng.js";
import { isUsablePoint } from "../app/static/js/map-gl-pin.js";
import { installFakeDom } from "./fake_dom.mjs";

const BOUNDS = [101.5, 3.0, 101.5008, 3.0008];   // [west, south, east, north]
const POINT = { id: "pt:3.00042,101.50042", is_point: true, lat: 3.00042, lon: 101.50042, area_id: "shah-alam",
  section: { id: "sec-1", name: "Section 1" }, depth_m: { 10: 0.4, 20: 1.2, 50: 2.3 }, shelter: { name: "Dewan Server", distance_m: 2400 },
  cell: { grid: "jrc", row: 1, col: 2, bounds: BOUNDS } };
const LINKS = { details: "./?tab=business#place=pt:3.00042,101.50042", cost: "./?tab=cost#place=pt:3.00042,101.50042",
  directions: "https://www.google.com/maps/dir/?api=1&destination=3.00042,101.50042" };
const LAYER = { storms: [40, 70, 100], url: "/api/areas/shah-alam/layers/rain-pools-{mm}.png", bounds: [101.4, 2.9, 101.6, 3.2],
  classes: [], credit: "FABDEM", assumptions: { drains_mm: 30, runoff: 0.8, burn_m: 1 }, check: null };
const text = (nodes) => nodes.map((node) => node?.textContent ?? "").join(" ");

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

test("a point stays in the fragment, after the base map and the tilt, where the browser never sends it", () => {
  assert.equal(withMapView("?area=x&rp=50#place=pt:3.00042,101.50042", "dark", true), "?area=x&rp=50&base=dark&tilt=1#place=pt:3.00042,101.50042");
  assert.equal(withMapView("?rp=20", "map", false), "?rp=20");
  assert.equal(withMapView("?", "sat", false), "?base=sat");
});

test("a point's square is outlined from its bounds, and squares can be taller than wide", () => {
  assert.deepEqual(squareOutline(BOUNDS).geometry.coordinates[0], [[101.5, 3.0], [101.5008, 3.0], [101.5008, 3.0008], [101.5, 3.0008], [101.5, 3.0]]);
  const [square] = squaresGeo([[3, 101, 0.5, 1, 2]], 0.1, 0.2).features;
  assert.deepEqual(square.geometry.coordinates[0][2], [101.1, 3.2]);
});

test("only a point in the server's full shape is shown; a business or a part answer is not", () => {
  assert.equal(isUsablePoint(POINT), true);
  assert.equal(isUsablePoint({ ...POINT, id: "node-1", is_point: false }), false);
  assert.equal(isUsablePoint({ ...POINT, cell: { bounds: [1, 2, 3] } }), false);
  assert.equal(isUsablePoint({ ...POINT, depth_m: null }), false);
});

test("a point's card says the water on its square, each flood size, the server's relief centre, and moves the pin", () => {
  let moved = 0;
  const nodes = pointCard(POINT, { rp: "50", title: "Point in Section 1, Shah Alam", subline: "The 90 m flood square at 3.00042, 101.50042",
    links: LINKS, onClose() {}, onShare() {}, onMove: () => { moved += 1; } });
  const words = text(nodes);
  for (const want of ["Point in Section 1", "about 2.3 m of water on this square", "0.40 m", "1.20 m", "2.30 m", "Dewan Server", "2.4 km",
    "Full details", "Move the pin", "Directions"]) {
    assert.ok(words.includes(want), want);
  }
  const move = nodes.flatMap((node) => node.children ?? []).find((node) => node.textContent === "Move the pin");
  move.click();
  assert.equal(moved, 1);
});

test("a dry point says so, with what the model leaves out, in Malay too", () => {
  const dry = { ...POINT, depth_m: { 10: null, 20: null, 50: null }, shelter: null };
  const words = text(pointCard(dry, { rp: "10", title: "Point", subline: null, links: LINKS }));
  assert.ok(words.includes("no water on this square") && words.includes("flash floods"));
  useLang("ms");
  assert.ok(text(pointCard(dry, { rp: "10", title: "Titik", subline: null, links: LINKS })).includes("tidak menunjukkan air di petak ini"));
});

test("a picture goes on its four corners, and clicked points are dots joined by a line", () => {
  assert.deepEqual(imageCorners([101.4, 2.9, 101.6, 3.2]), [[101.4, 3.2], [101.6, 3.2], [101.6, 2.9], [101.4, 2.9]]);
  assert.equal(marksGeo([{ lat: 3, lng: 101 }]).features.length, 1);
  const two = marksGeo([{ lat: 3, lng: 101 }, { lat: 3.1, lng: 101.1 }]).features;
  assert.deepEqual(two.map((f) => f.geometry.type), ["LineString", "Point", "Point"]);
});

test("clearing the marks empties them, and never removes a source its layers still use", () => {
  const calls = [];
  const map = { isStyleLoaded: () => true, getSource: (id) => (id === "mg-eng-marks" ? { setData: (data) => calls.push(["data", data.features.length]) } : undefined),
    getLayer: () => undefined, removeSource: (id) => calls.push(["remove", id]), removeLayer() {} };
  glDrawer({ getMap: () => map, beforeId: () => undefined, hasOurLayers: () => true }).drop("marks");
  assert.deepEqual(calls, [["data", 0]]);
});

test("a picture is taken off even while tiles or the picture itself are still loading", () => {
  const removed = [];
  const map = { isStyleLoaded: () => false, getLayer: () => ({}), getSource: () => ({}), removeLayer: (id) => removed.push(id),
    removeSource() {}, addSource() {}, addLayer() {} };
  const drawer = glDrawer({ getMap: () => map, beforeId: () => undefined, hasOurLayers: () => true });
  drawer.picture("pools", "/pools-70.png", LAYER.bounds, 0.8);
  removed.length = 0;
  drawer.drop("pools");
  assert.deepEqual(removed, ["mg-eng-pools"]);
});

test("a click goes to the tool that is on, as the panel reads it, and to nothing when none is", () => {
  const drawer = glDrawer({ getMap: () => null, beforeId: () => undefined, hasOurLayers: () => true });
  assert.equal(drawer.click({ lat: 3, lng: 101 }), false);
  const got = [];
  drawer.setTool(true, (event) => got.push(event.latlng));
  assert.equal(drawer.click({ lat: 3, lng: 101 }), true);
  assert.deepEqual(got, [{ lat: 3, lng: 101 }]);
  drawer.setTool(false, () => {});
  assert.equal(drawer.click({ lat: 3, lng: 101 }), false);
});

test("what engineer mode drew comes back after a base map change", () => {
  const added = [];
  const map = { isStyleLoaded: () => false, getSource: () => undefined, getLayer: () => undefined,
    addSource: (id, source) => added.push(["source", id, source.type]), addLayer: (layer, before) => added.push(["layer", layer.id, before]) };
  const drawer = glDrawer({ getMap: () => map, beforeId: () => "road", hasOurLayers: () => false });
  drawer.picture("pools", "/pools-70.png", LAYER.bounds, 0.8);   // another base map is still loading: nothing added yet
  assert.equal(added.length, 0);
  drawer.redraw(map);
  assert.deepEqual(added.slice(0, 2), [["source", "mg-eng-pools", "image"], ["layer", "mg-eng-pools", "road"]]);
  assert.ok(!added.some(([, id]) => id === "mg-eng-marks-line"), "no marks drawn, none brought back");
  const named = [];
  const other = glDrawer({ getMap: () => ({ ...map, addLayer: (layer, before) => named.push([layer.id, before]) }), beforeId: (_map, key) => `under-${key}`,
    hasOurLayers: () => true, prefix: "mg-layer" });
  other.picture("low", "/low.png", LAYER.bounds, 0.65);
  assert.deepEqual(named, [["mg-layer-low", "under-low"]], "its own prefix, and where each picture goes by its key");
});

test("engineer mode draws its rain pools through the map's drawer, and a tool takes the clicks", () => {
  const calls = [];
  const drawer = { picture: (...args) => calls.push(["picture", ...args]), drop: (key) => calls.push(["drop", key]), marks() {},
    setTool: (isOn) => calls.push(["tool", isOn]), isAiming: () => false };
  const section = document.createElement("section");
  const button = document.createElement("button");
  const panel = createEngineer({ section, button, area: { id: "shah-alam", layers: { rain_pools: LAYER } }, wanted: true, drawer });
  const layerBox = section.querySelectorAll("input").find((input) => input.getAttribute("type") === "checkbox");
  layerBox.dispatch("change", { target: { checked: true } });
  assert.deepEqual(calls.find(([kind]) => kind === "picture"), ["picture", "pools", "/api/areas/shah-alam/layers/rain-pools-70.png", LAYER.bounds, 0.8]);
  panel.state.tool = "inspect";
  panel.toggle(true);
  assert.deepEqual(calls.filter(([kind]) => kind === "tool").at(-1), ["tool", true]);
  panel.toggle(false);
  assert.deepEqual(calls.filter(([kind]) => kind === "tool").at(-1), ["tool", false]);
  assert.ok(calls.some(([kind, key]) => kind === "drop" && key === "pools"));
});
