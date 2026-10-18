// Run from 11_Platform_Draft:  node --test tests/gauge.test.mjs
// The still picture of a flood depth (miniGauge) and the size of the water in the full shop-front drawing.
import assert from "node:assert/strict";
import { test } from "node:test";

import { BANDS, DOOR_M } from "../app/static/js/dom.js";
import { TOP_M, gauge, miniGauge } from "../app/static/js/gauge.js";
import { installFakeDom } from "./fake_dom.mjs";

// The water is one watery blue (the third band's) whatever the depth: deeper bands are indigo and plum, which do not read as water.
const WATER = BANDS[2].color;
const num = (node, name) => Number(node.getAttribute(name));
/** SVG units per metre, read off the drawing itself: the door is 2.1 m tall. */
const unitsPerMetre = (svg) => num(svg.querySelector(".door"), "height") / DOOR_M;
const GROUND = (svg) => num(svg.querySelector(".street"), "y1");

test("the small gauge's water is as tall as the depth, to scale with the door", () => {
  installFakeDom();
  const svg = miniGauge(1.2);
  const water = svg.querySelector(".water");
  assert.ok(Math.abs(num(water, "height") / unitsPerMetre(svg) - 1.2) < 1e-9);
  assert.equal(num(water, "y") + num(water, "height"), GROUND(svg));   // it stands on the street
  assert.equal(water.getAttribute("fill"), WATER);
});

test("the small gauge cuts the water off at one storey", () => {
  installFakeDom();
  const svg = miniGauge(5.4);
  const height = num(svg.querySelector(".water"), "height");
  assert.ok(Math.abs(height / unitsPerMetre(svg) - 3) < 1e-9);
  assert.equal(svg.querySelector(".water").getAttribute("fill"), WATER);
});

test("the small gauge draws no water when the model has none", () => {
  installFakeDom();
  for (const depth of [0, null, undefined, -1]) assert.equal(miniGauge(depth).querySelector(".water"), null);
});

test("the small gauge is a silent picture: hidden from screen readers, no text, the scene's three objects", () => {
  installFakeDom();
  const svg = miniGauge(0.5);
  assert.equal(svg.getAttribute("aria-hidden"), "true");
  assert.equal(svg.getAttribute("role"), null);
  assert.ok((svg.getAttribute("class") ?? "").split(" ").includes("gauge-mini"));
  assert.equal(svg.querySelectorAll("text").length, 0);
  assert.equal(svg.querySelectorAll(".door").length + svg.querySelectorAll(".counter").length + svg.querySelectorAll(".figure").length, 3);
});

test("drawing the small gauge does not disturb the animated gauge", () => {
  installFakeDom();
  const premise = { depth_m: { 10: 0.5, 20: 1.5, 50: 2 } };
  gauge(premise, "20", 0);   // the water now stands at 1.5 m
  miniGauge(2.5);
  const next = gauge(premise, "10", 0);
  assert.equal(next.querySelector(".water").style.transform, `scaleY(${1.5 / TOP_M})`);   // it falls from 1.5 m, not from the mini's 2.5 m
});

test("water and waterline stop short of the right-hand labels", () => {
  installFakeDom();
  const svg = gauge({ depth_m: { 10: 0.5, 20: 1, 50: 2 } }, "20", 0);
  const water = svg.querySelector(".water");
  const labelX = Math.min(...svg.querySelectorAll(".level").map((label) => num(label, "x")));
  const reach = num(water, "x") + num(water, "width");
  // the labels end at labelX and run left: room for 11 characters of bold 12px ("1 dalam 50" is 10), about 6.6 units each
  assert.ok(labelX - reach >= 11 * 6.6, `labels ending at ${labelX} must be clear of water ending at ${reach}`);
  assert.equal(num(svg.querySelector(".waterline"), "x2"), reach);
  assert.equal(num(svg.querySelector(".other-level"), "x2"), reach);
});

test("the water is the same blue at every depth, in the full drawing and the small one", () => {
  installFakeDom();
  for (const depth of [0.1, 0.8, 1.4, 1.9, 2.5, 3.5, 7]) {
    assert.equal(miniGauge(depth).querySelector(".water").getAttribute("fill"), WATER, `mini at ${depth} m`);
    const full = gauge({ depth_m: { 10: depth, 20: depth, 50: depth } }, "20", 0);
    assert.equal(full.querySelector(".water").getAttribute("fill"), WATER, `full at ${depth} m`);
  }
});
