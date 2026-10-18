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

function mount(overrides = {}, language = "en") {
  installFakeDom();
  useLang(language);
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
  const unitsPerMetre = Number(picture.querySelector(".door").getAttribute("height")) / 2.1;   // the door is 2.1 m tall
  assert.ok(Math.abs(Number(picture.querySelector(".water").getAttribute("height")) / unitsPerMetre - 1.0) < 1e-9);
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

// ---------- a city split into sections ----------

test("the whole city's tiles count its lean index, named after the city, and a section's its own businesses", async () => {
  const { INDEX, CITY_HISTORY } = await import("./fixtures/city_data.mjs");
  const { SECTION_DATA } = await import("./fixtures/section_data.mjs");
  const city = mount({ premises: INDEX, areaName: "Shah Alam", history: CITY_HISTORY });
  city.kpis.setScenario("50");
  assert.match(city.wet.textContent, /3 of 5/);
  assert.match(city.wet.textContent, /businesses in Shah Alam get water/);
  assert.equal(figure(city.depth), "0.9 m", "the median over the city's wet businesses");
  const section = mount({ premises: SECTION_DATA.premises, areaName: "Seksyen 25", history: SECTION_DATA.area.history });
  section.kpis.setScenario("50");
  assert.match(section.wet.textContent, /2 of 3/);
  assert.match(section.wet.textContent, /businesses in Seksyen 25 get water/);
});

test("a section with no businesses mapped shows a dash, not 0 of 0", () => {
  const { kpis, wet, depth } = mount({ premises: [], areaName: "Seksyen U1" });
  kpis.setScenario("50");
  assert.equal(figure(wet), "–");
  assert.match(wet.textContent, /No businesses mapped here yet/);
  assert.equal(figure(depth), "–");
});

test("a section searched with no flood found says none was found in the sources checked, not that none was collected", () => {
  const searched = { first_year: 1992, recent_from: 2019, last_year: 2026, floods: [] };
  const { flood } = mount({ history: searched, areaName: "Seksyen U1" });
  assert.equal(figure(flood), "–");
  assert.match(flood.textContent, /None found in the sources we checked \(1992–2026\)/);
  assert.doesNotMatch(flood.textContent, /collected/);
  assert.match(mount({ history: null }).flood.textContent, /No flood record collected yet/, "an area never searched, as before");
  try {
    assert.match(mount({ history: searched }, "ms").flood.textContent, /Tiada ditemui dalam sumber yang kami semak \(1992–2026\)/);
  } finally {
    useLang("en");
  }
});
