// Run from 11_Platform_Draft:  node --test tests/kpis.test.mjs
// The figure tiles on the Area overview (kpis.js): the rain tile only when Google Weather is set up, and the picture
// in the typical-depth tile only when some business is wet.
import assert from "node:assert/strict";
import { test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { createKpis } from "../app/static/js/kpis.js";
import { installFakeDom } from "./fake_dom.mjs";

const premise = (id, d10, d20, d50) => ({ id, depth_m: { 10: d10, 20: d20, 50: d50 } });
const PREMISES = [premise("a", null, 0.4, 1.0), premise("b", 0.2, 1.0, 2.0), premise("c", null, 2.2, 3.5), premise("d", null, null, null)];
const RAIN = { configured: true, data: { total_mm: 24, max_chance_pct: 60, hours: 12 } };

function mount(overrides = {}) {
  installFakeDom();
  useLang("en");
  const container = document.createElement("div");
  const kpis = createKpis(container, { history: null, areaName: "Test Area", premises: PREMISES, ...overrides });
  const [wet, depth, flood, rain] = container.children;
  return { container, kpis, wet, depth, flood, rain };
}
const figure = (tile) => tile.querySelector(".kpi-figure").textContent;
const art = (tile) => tile.querySelector(".kpi-art");

test("the rain tile is out of the grid until the page knows Google Weather is set up", () => {
  const { container, rain } = mount();
  assert.equal(rain.hidden, true);
  assert.equal(container.dataset.tiles, "3");
});

test("the rain tile stays hidden when Google Weather is not configured", () => {
  const { container, kpis, rain } = mount();
  kpis.setRain({ configured: false, data: null });
  assert.equal(rain.hidden, true);
  assert.equal(container.dataset.tiles, "3");
});

test("the rain tile shows its figure when Google Weather is configured", () => {
  const { container, kpis, rain } = mount();
  kpis.setRain(RAIN);
  assert.equal(rain.hidden, false);
  assert.equal(container.dataset.tiles, "4");
  assert.match(figure(rain), /24/);
  assert.match(rain.textContent, /60%/);
});

test("the rain tile shows while it is asked, and with a dash when the answer failed", () => {
  const { kpis, rain } = mount();
  kpis.setRain({ configured: true, busy: true });
  assert.equal(rain.hidden, false);
  assert.equal(figure(rain), "…");
  kpis.setRain({ configured: true, error: true });
  assert.equal(rain.hidden, false);
  assert.equal(figure(rain), "–");
});

test("a rain tile that was shown goes away again if the answer says it is not configured", () => {
  const { container, kpis, rain } = mount();
  kpis.setRain(RAIN);
  kpis.setRain({ configured: false, data: null });
  assert.equal(rain.hidden, true);
  assert.equal(container.dataset.tiles, "3");
});

test("the typical-depth tile gets a picture of the median depth when businesses are wet", () => {
  const { kpis, depth } = mount();
  kpis.setScenario("20");   // wet depths 0.4, 1.0, 1.0, 2.2: the median is 1.0
  assert.equal(figure(depth), "1.0 m");
  const picture = art(depth).querySelector("svg");
  assert.ok(picture, "the slot holds a drawing");
  assert.equal(picture.getAttribute("aria-hidden"), "true");
  assert.equal(art(depth).hidden, false);
  assert.ok(Math.abs(Number(picture.querySelector(".water").getAttribute("height")) / 62 - 1.0) < 1e-9);
});

test("the picture follows the flood size and is cleared when no business is wet", () => {
  const { kpis, depth } = mount({ premises: [premise("a", null, 0.4, 1.0), premise("b", null, null, null)] });
  kpis.setScenario("20");
  assert.ok(art(depth).querySelector("svg"));
  const before = art(depth).querySelector(".water").getAttribute("height");
  kpis.setScenario("50");
  assert.notEqual(art(depth).querySelector(".water").getAttribute("height"), before);
  kpis.setScenario("10");   // nothing is wet in the 1 in 10 flood
  assert.equal(figure(depth), "–");
  assert.equal(art(depth).querySelector("svg"), null);
  assert.equal(art(depth).hidden, true);
});

test("the typical-depth tile has no picture before a flood size is chosen", () => {
  const { depth } = mount();
  assert.equal(art(depth).querySelector("svg"), null);
});

test("the headline tile counts the wet businesses", () => {
  const { kpis, wet } = mount();
  kpis.setScenario("20");
  assert.match(wet.textContent, /3 of 4/);
});
