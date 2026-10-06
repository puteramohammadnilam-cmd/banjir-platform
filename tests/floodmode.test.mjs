// Run from 11_Platform_Draft:  node --test tests/floodmode.test.mjs
// "Flood is coming" (floodmode.js): six steps filled in from what the page knows about the place.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { checklist, createFloodMode, liftCm } from "../app/static/js/floodmode.js";
import { installFakeDom } from "./fake_dom.mjs";
import { point, shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

const spot = { lat: 3.02579, lon: 101.54278, road: "Jalan Dua", distance_m: 80, bearing: 74 };
const dry = { spots: { 10: spot, 20: spot, 50: spot, credit: "c" } };
const text = (context) => checklist(context).map((node) => node.textContent).join(" | ");
const stockPhoto = { estimate: { is_shop_inside: true, confidence: "medium", items: [
  { item: "Rice sacks", kind: "stock", lowest_cm: 0, value_rm_low: 1, value_rm_high: 2 },
  { item: "Top shelf", kind: "stock", lowest_cm: 150, value_rm_low: 1, value_rm_high: 2 }] },
  floor_height_cm: 0, per_flood: { 50: { water_above_floor_m: 1, under_water: [0], value_rm_low: 1, value_rm_high: 2 } } };

test("the lift height is the water above the floor, rounded up to 5 cm; none when the floor is above it", () => {
  assert.equal(liftCm(0.26), 30);
  assert.equal(liftCm(1, 30), 70);
  assert.equal(liftCm(0.2, 30), 0);
  assert.equal(liftCm(null), 0);
});

test("the six steps name the place, the lift height, the things to lift first, the dry street and the relief centre", () => {
  const words = text({ premise: { ...shop, shelter: { name: "SK Satu", distance_m: 450 } }, rp: "50", floorCm: 0,
    stock: { photos: [stockPhoto], off: [] }, dry });
  assert.match(words, /For A Shop, worked out for a 1 in 50 years flood in the model/);
  assert.match(words, /1Lift stock and machines.*At least 100 cm off the floor.*1\.00 m of water at street level/);
  assert.match(words, /Lift these first \(from your stock photo\): Rice sacks\./);
  assert.doesNotMatch(words, /Top shelf/);
  assert.match(words, /2Move the car.*80 m away east.*Jalan Dua/);
  assert.match(words, /3Switch off the power/);
  assert.match(words, /6Close early and go.*SK Satu, 450 m away.*999/);
});

test("a floor above the water, and no dry-spot answer yet, still give plain steps", () => {
  const words = text({ premise: point(), rp: "10", floorCm: 300, stock: undefined, dry: undefined });
  assert.match(words, /For A spot I checked/);
  assert.match(words, /no water above your floor in a 1 in 10 years flood/);
  assert.match(words, /Move cars to higher ground early/);
  assert.match(words, /ask the council or the district office/);
});

test("the dialog opens with the checklist and gives focus back to its opener when closed", () => {
  const mode = createFloodMode({ body: { append() {} } });
  let shown = 0;
  mode.dialog.showModal = () => { shown += 1; };
  mode.dialog.close = () => mode.dialog.dispatch("close");
  const opener = { isConnected: true, focus() { this.focused = true; } };
  mode.open({ premise: shop, rp: "20", floorCm: 0, dry }, opener);
  assert.equal(shown, 1);
  assert.match(mode.dialog.textContent, /What to do now/);
  mode.dialog.querySelector("button").click();
  assert.equal(opener.focused, true);
});

// ---------- review fixes ----------

test("leaving comes first when the water is already rising, and the power is not switched back on unchecked", () => {
  const words = text({ premise: shop, rp: "50", floorCm: 0, dry });
  assert.match(words, /If water is already rising, or the authorities tell you to leave, leave now/);
  assert.match(words, /If the floor or the switchboard is already wet, do not go near it/);
  assert.match(words, /do not switch the power back on until an electrician has checked it/);
});

test("the lift height and the things to lift first use the same floor, from the shop-front photo", () => {
  // 1.00 m in the street, the floor 60 cm up: 40 cm above the floor; rice on the floor is under it, a fridge at 50 cm is not
  const photo = { ...stockPhoto, estimate: { ...stockPhoto.estimate, items: [stockPhoto.estimate.items[0],
    { item: "Fridge", kind: "equipment", lowest_cm: 50, value_rm_low: 1, value_rm_high: 2 }] } };
  const words = text({ premise: shop, rp: "50", floorCm: 60, stock: { photos: [photo], off: [] }, dry });
  assert.match(words, /At least 40 cm off the floor/);
  assert.match(words, /your floor is about 60 cm above the street, from your shop-front photo/);
  assert.match(words, /Lift these first \(from your stock photo\): Rice sacks\./);
});

test("more than five things to lift first are counted, not cut silently", () => {
  const items = Array.from({ length: 7 }, (_, i) => ({ item: `Thing ${i + 1}`, kind: "stock", lowest_cm: 0, value_rm_low: 1, value_rm_high: 2 }));
  const words = text({ premise: shop, rp: "50", floorCm: 0, stock: { photos: [{ ...stockPhoto, estimate: { ...stockPhoto.estimate, items } }], off: [] }, dry });
  assert.match(words, /Thing 5 and 2 more\./);
});

test("the car step says it is being found, then fills in when the answer comes, keeping the ticks", () => {
  const mode = createFloodMode({ body: { append() {} } });
  mode.dialog.showModal = () => { mode.dialog.open = true; };
  mode.open({ premise: shop, rp: "50", floorCm: 0, dry: { busy: true } });
  const step = () => mode.dialog.querySelector('[data-step="car"]');
  assert.match(step().textContent, /Finding the nearest dry street/);
  const tick = mode.dialog.querySelector('[type="checkbox"]');
  tick.checked = true;
  mode.refresh({ premise: shop, rp: "50", floorCm: 0, dry });
  assert.match(step().textContent, /80 m away east/);
  assert.equal(mode.dialog.querySelector('[type="checkbox"]').checked, true);
});

test("when the button that opened it was rebuilt, closing focuses the one now on the page", () => {
  const current = { focus() { this.focused = true; } };
  const mode = createFloodMode({ body: { append() {} }, querySelector: (selector) => (selector === ".mode-open" ? current : null) });
  mode.dialog.showModal = () => {};
  mode.open({ premise: shop, rp: "20", floorCm: 0, dry }, { isConnected: false, focus() { throw new Error("gone"); } });
  mode.dialog.dispatch("close");
  assert.equal(current.focused, true);
});
