// Run from 11_Platform_Draft:  node --test tests/lowground.test.mjs
// The low ground layer (lowground.js) on the small fake DOM in tests/fake_dom.mjs: the box is off at first and the level
// choice hidden until it is ticked, a level fetches its own picture in a pane under flash flood potential's, a load
// error unticks and says so, and the key carries the honest note and the credit. Wired under the map by overview.js.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { h } from "../app/static/js/dom.js";
import { useLang, DEFAULT_LANG } from "../app/static/js/i18n.js";
import {
  DEFAULT_LEVEL, LOW_PANE_Z, LOW_RAMP, createLowGround, levelUrl, levelsOf, lowGroundKey,
} from "../app/static/js/lowground.js";
import { createIndexControls, renderLegend } from "../app/static/js/overview.js";
import { swatchStyle } from "../app/static/js/susceptibility.js";
import { installFakeDom } from "./fake_dom.mjs";

const LAYER = Object.freeze({
  levels: [1, 2, 3, 5], url: "/api/areas/test-city/layers/low-ground-{level}.png",
  bounds: [101.43, 2.95, 101.59, 3.23], credit: "Ground height: Copernicus GLO-30; rivers © OpenStreetMap contributors",
});

beforeEach(() => installFakeDom());

/** A stand-in for the map: addOverlay hands over a Leaflet map with panes, and L.imageOverlay records what it draws. */
function fakeMap() {
  const panes = new Map();
  const leaflet = {
    getPane: (name) => panes.get(name),
    createPane: (name) => { panes.set(name, { style: {} }); return panes.get(name); },
  };
  const drawn = [];
  globalThis.L = {
    imageOverlay: (url, bounds, options) => {
      const overlay = { url, bounds, options, onMap: false, events: new Map() };
      overlay.on = (type, listener) => { overlay.events.set(type, listener); return overlay; };
      overlay.addTo = () => { overlay.onMap = true; return overlay; };
      overlay.remove = () => { overlay.onMap = false; return overlay; };
      drawn.push(overlay);
      return overlay;
    },
  };
  return { map: { addOverlay: (build) => build({ map: leaflet, renderer: {}, isAiming: () => false }) }, drawn, panes };
}

function mount(layer = LAYER) {
  const fake = fakeMap();
  const keys = [];
  const low = createLowGround(fake.map, layer, { onChange: (key) => keys.push(key) });
  const slot = h("div");
  slot.append(...low.nodes);
  const box = slot.querySelector('[type="checkbox"]');
  const choice = slot.querySelector("fieldset");
  const tick = (isOn) => { box.checked = isOn; box.dispatch("change"); };
  const pick = (level) => slot.querySelectorAll('[type="radio"]').find((input) => input.getAttribute("value") === String(level)).dispatch("change");
  return { ...fake, low, slot, box, choice, keys, tick, pick };
}

test("the box is off at first, nothing is fetched, and the level choice waits until it is ticked", () => {
  const { box, choice, drawn, keys, slot } = mount();
  assert.equal(box.checked ?? false, false);
  assert.equal(choice.hidden, true);
  assert.equal(drawn.length, 0);
  assert.deepEqual(keys, []);
  assert.equal(slot.querySelector(".layer-toggle").textContent, "Show low ground");
  const radios = slot.querySelectorAll('[type="radio"]');
  assert.deepEqual(radios.map((r) => r.getAttribute("value")), ["1", "2", "3", "5"]);
  assert.deepEqual(radios.filter((r) => r.getAttribute("checked") !== null).map((r) => r.getAttribute("value")), [String(DEFAULT_LEVEL)]);
  assert.deepEqual(slot.querySelectorAll("label").slice(1).map((label) => label.textContent), ["1 m", "2 m", "3 m", "5 m"]);
});

test("ticking draws the default level in its own pane under flash flood potential's, and unticking takes it off", () => {
  const { tick, choice, drawn, panes, keys } = mount();
  tick(true);
  assert.equal(choice.hidden, false);
  assert.equal(drawn.length, 1);
  const [overlay] = drawn;
  assert.equal(overlay.url, "/api/areas/test-city/layers/low-ground-2.png");
  assert.deepEqual(overlay.bounds, [[2.95, 101.43], [3.23, 101.59]]);
  assert.equal(overlay.options.interactive, false);
  assert.match(overlay.options.className, /lowground-overlay/);
  const z = Number(panes.get(overlay.options.pane).style.zIndex);
  assert.equal(z, LOW_PANE_Z);
  assert.ok(z < 350, "under the flash flood picture's pane (350), so under the squares and dots (400) too");
  assert.notEqual(overlay.options.pane, "picture");
  assert.equal(overlay.onMap, true);
  assert.ok(keys.at(-1), "the key gains the layer's group");
  tick(false);
  assert.equal(overlay.onMap, false);
  assert.equal(choice.hidden, true);
  assert.equal(keys.at(-1), null);
});

test("a change of level swaps the picture, fetching each level once", () => {
  const { tick, pick, drawn, keys } = mount();
  tick(true);
  pick(5);
  assert.deepEqual(drawn.map((o) => o.url), ["/api/areas/test-city/layers/low-ground-2.png", "/api/areas/test-city/layers/low-ground-5.png"]);
  assert.deepEqual(drawn.map((o) => o.onMap), [false, true]);
  assert.match(keys.at(-1).querySelectorAll(".fineprint")[0].textContent, /within 5 m/);
  pick(2);
  assert.equal(drawn.length, 2, "the 2 m picture comes back; nothing is fetched again");
  assert.deepEqual(drawn.map((o) => o.onMap), [true, false]);
  tick(false);
  pick(1);
  assert.equal(drawn.length, 2, "a level picked while off waits for the tick");
  tick(true);
  assert.equal(drawn.at(-1).url, "/api/areas/test-city/layers/low-ground-1.png");
});

test("a picture that fails to load unticks the box and says so, and the next tick tries again", () => {
  const { tick, box, choice, drawn, keys, slot } = mount();
  tick(true);
  drawn[0].events.get("error")();
  assert.equal(box.checked, false);
  assert.equal(choice.hidden, true);
  assert.equal(drawn[0].onMap, false);
  const alert = slot.querySelector('[role="alert"]');
  assert.equal(alert.hidden, false);
  assert.match(alert.textContent, /low ground layer could not be loaded/);
  assert.equal(keys.at(-1), null);
  tick(true);
  assert.equal(drawn.length, 2);
  assert.equal(alert.hidden, true);
});

test("an error from a level no longer on show changes nothing", () => {
  const { tick, pick, box, drawn } = mount();
  tick(true);
  pick(3);
  drawn[0].events.get("error")();
  assert.equal(box.checked, true);
  assert.equal(drawn[1].onMap, true);
});

test("the key shows the tones up to the level, the honest note, the 3 km limit and the credit", () => {
  const key = lowGroundKey(3);
  assert.equal(key.querySelector(".legend-heading").textContent, "Low ground: height above the nearest mapped river");
  assert.deepEqual(key.querySelectorAll("li").map((item) => item.textContent), ["Up to 1 m", "1 to 2 m", "2 to 3 m"]);
  assert.deepEqual(key.querySelectorAll(".ramp-swatch").map((s) => s.getAttribute("style")), LOW_RAMP.slice(0, 3).map(swatchStyle));
  const notes = key.querySelectorAll(".fineprint").map((p) => p.textContent);
  assert.equal(notes[0], "Shaded: land within 3 m of the nearest mapped river's level. Not a flood forecast; unshaded land can still flood from rain or drains.");
  assert.equal(notes[1], "No shading beyond 3 km of a mapped river.");
  assert.equal(notes[2], LAYER.credit);
  assert.equal(lowGroundKey(5).querySelectorAll(".ramp-swatch").length, 4);
  assert.equal(lowGroundKey(1).querySelectorAll(".ramp-swatch").length, 1);
});

test("the key reads in Bahasa Melayu too, with no word of safety", () => {
  useLang("ms");
  try {
    const text = lowGroundKey(2).textContent;
    assert.match(text, /Tanah rendah/);
    assert.match(text, /2 m/);
    assert.doesNotMatch(text, /selamat/i);
  } finally {
    useLang(DEFAULT_LANG);
  }
});

test("no layer, or one the page cannot draw: no controls", () => {
  for (const layer of [null, undefined, { ...LAYER, url: null }, { ...LAYER, levels: [4] }, { ...LAYER, bounds: null }]) {
    assert.deepEqual(createLowGround(fakeMap().map, layer).nodes, []);
  }
  assert.deepEqual(levelsOf({ ...LAYER, levels: [5, 1, 4] }), [1, 5]);
  assert.equal(levelUrl(LAYER, 3), "/api/areas/test-city/layers/low-ground-3.png");
});

test("a layer without 2 m starts at its lowest level", () => {
  const { tick, drawn } = mount({ ...LAYER, levels: [3, 5] });
  tick(true);
  assert.equal(drawn[0].url, "/api/areas/test-city/layers/low-ground-3.png");
});

test("under the map: the controls show even without flash flood potential, and the key takes the group", () => {
  const fake = fakeMap();
  const slot = h("div");
  const low = createLowGround(fake.map, LAYER);
  createIndexControls(slot, { map: fake.map, layer: null, metrics: [], onChange: () => {}, extra: low.nodes });
  assert.equal(slot.hidden, false);
  assert.equal(slot.querySelector(".layer-toggle").textContent, "Show low ground");
  const legend = h("ul");
  renderLegend(legend, true, null, { lowKey: lowGroundKey(2) });
  assert.equal(legend.children.length, 3);
  assert.match(legend.children[2].getAttribute("class"), /lowground-key/);
  renderLegend(legend, true);
  assert.equal(legend.children.length, 2);
});
