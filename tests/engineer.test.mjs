// node --test tests/engineer.test.mjs
// Engineer mode's panel (engineer.js): off unless asked for, no stray text, the layer's key and check, and the chart.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createEngineer, isWanted, profileChart } from "../app/static/js/engineer.js";
import { useLang } from "../app/static/js/i18n.js";
import { installFakeDom } from "./fake_dom.mjs";

const LAYER = { storms: [40, 70, 100], url: "/api/areas/shah-alam/layers/rain-pools-{mm}.png", bounds: [101.4, 2.9, 101.6, 3.2],
  classes: [], credit: "FABDEM credit", assumptions: { drains_mm: 30, runoff: 0.8, burn_m: 1 },
  check: { storm_mm: 70, auc: 0.53, baseline_low_ground_auc: 0.62, hotspot_percentile: 36.4, baseline_low_ground_hotspot_percentile: 60.1 } };

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

function mount(wanted) {
  const section = document.createElement("section");
  const button = document.createElement("button");
  createEngineer({ section, button, mapApi: null, area: { id: "shah-alam", layers: { rain_pools: LAYER } }, wanted });
  return { section, button };
}

test("engineer mode is off unless ?engineer=1 or turned on before", () => {
  assert.equal(isWanted("?engineer=1", null), true);
  assert.equal(isWanted("", { getItem: () => "1" }), true);
  assert.equal(isWanted("", { getItem: () => null }), false);
  const { section, button } = mount(false);
  assert.equal(section.hidden, true);
  assert.equal(button.getAttribute("aria-pressed"), "false");
});

test("the panel shows the layer's assumptions and check, and never a stray false", () => {
  const { section } = mount(true);
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /drains take only 30 mm/);
  assert.match(section.textContent, /AUC 0\.53, where 0\.5 is chance; low ground 0\.62/);
  assert.doesNotMatch(section.textContent, /\bfalse\b/);
});

test("a profile chart draws ground, standing water and river water", () => {
  const points = [{ d: 0, ground_m: 5, pool_m: { 70: 0.4 }, river_depth_m: { 50: 1 } }, { d: 500, ground_m: 3, pool_m: { 70: null }, river_depth_m: { 50: null } }];
  const svg = profileChart(points, "70");
  assert.equal(svg.querySelectorAll("path").length, 3);
  assert.match(svg.textContent, /0\.50 km/);
});

test("while a tool is on, the map's clicks are the tool's, and turning the mode off gives them back", async () => {
  const { toolClaim } = await import("../app/static/js/map.js");
  const section = document.createElement("section");
  const button = document.createElement("button");
  const panel = createEngineer({ section, button, mapApi: null, area: { id: "shah-alam", layers: { rain_pools: LAYER } }, wanted: true });
  assert.equal(toolClaim.active, false, "no tool picked yet");
  panel.state.tool = "inspect";
  panel.toggle(true);
  assert.equal(toolClaim.active, true);
  assert.equal(typeof toolClaim.onClick, "function");
  panel.toggle(false);
  assert.equal(toolClaim.active, false);
});
