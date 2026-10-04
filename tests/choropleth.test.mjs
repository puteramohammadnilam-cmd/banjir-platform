// Run from 11_Platform_Draft:  node --test tests/choropleth.test.mjs
// The whole-city map (choropleth.js): each section shaded by the share of its 90 m squares with water at the flood size
// on show, in six classes on the squares' own ramp (cells.js), one canvas path per section, a tooltip in words, a click
// that opens the section (never while a point is being aimed at), and the key. Leaflet is a stand-in.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { SQUARE_RAMP } from "../app/static/js/cells.js";
import { SHARE_CLASSES, choroplethKey, createChoropleth, shareClass, shareOf, shareText, tooltipLines } from "../app/static/js/choropleth.js";
import { useLang } from "../app/static/js/i18n.js";
import { installFakeDom } from "./fake_dom.mjs";
import { SECTIONS, SECTION_WORD } from "./fixtures/city_data.mjs";

class FakePath {
  constructor(geometry, options) {
    Object.assign(this, { geometry, options, style: {}, events: new Map(), tooltip: null, fronted: 0 });
  }

  setStyle(style) {
    this.style = { ...this.style, ...style };
    return this;
  }

  on(type, listener) {
    this.events.set(type, listener);
    return this;
  }

  fire(type) {
    this.events.get(type)?.({ target: this });
  }

  bindTooltip(content, options) {
    this.tooltip = { content, options };
    return this;
  }

  bringToFront() {
    this.fronted += 1;
    return this;
  }

  addTo(map) {
    map.layers.push(this);
    return this;
  }
}

let map;
beforeEach(() => {
  installFakeDom();
  map = { layers: [] };
  globalThis.L = { geoJSON: (geometry, options) => new FakePath(geometry, options) };
});

const RENDERER = { kind: "canvas" };
function mount({ aiming = false } = {}) {
  const opened = [];
  const choropleth = createChoropleth(map, RENDERER, SECTIONS, { onOpen: (id) => opened.push(id), isAiming: () => aiming });
  return { choropleth, opened };
}

// ---------- the classes ----------

test("a section's share is its wet squares over its squares at the flood size, 0 when it has none", () => {
  assert.equal(shareOf(SECTIONS[1], "50"), 870 / 1500);
  assert.equal(shareOf(SECTIONS[1], "10"), 300 / 1500);
  assert.equal(shareOf(SECTIONS[2], "50"), 0);
  assert.equal(shareOf({ counts: { cells: 0, wet_cells: { 50: 0 } } }, "50"), 0, "no squares: no share, not NaN");
  assert.equal(shareOf({}, "50"), 0, "no counts at all reads as none");
});

test("six classes: none, under 5%, 5-15%, 15-30%, 30-50%, over 50%, edges going to the class above except 50%", () => {
  const cases = [[0, 0], [0.0001, 1], [0.0499, 1], [0.05, 2], [0.1499, 2], [0.15, 3], [0.2999, 3], [0.3, 4], [0.5, 4], [0.5001, 5], [1, 5]];
  for (const [share, expected] of cases) assert.equal(shareClass(share), expected, String(share));
  assert.equal(SHARE_CLASSES.length, 6);
});

test("the shading is the squares' own ramp, one step per class, and a section with none is outlined only", () => {
  assert.deepEqual(SHARE_CLASSES.slice(1).map(({ color, opacity }) => [color, opacity]), SQUARE_RAMP.map(({ color, opacity }) => [color, opacity]));
  assert.equal(SHARE_CLASSES[0].opacity, 0);
});

test("shares read in whole percent, and a share under 1% never reads as 0%", () => {
  assert.equal(shareText(0), "0%");
  assert.equal(shareText(0.004), "under 1%");
  assert.equal(shareText(0.58), "58%");
  assert.equal(shareText(1), "100%");
});

// ---------- the map ----------

test("one path per section on the canvas it is given, shaded for the flood size on show", () => {
  const { choropleth } = mount();
  assert.equal(map.layers.length, SECTIONS.length);
  assert.ok(map.layers.every((path) => path.options.renderer === RENDERER), "on the shared canvas");
  assert.deepEqual(map.layers.map((path) => path.geometry), SECTIONS.map(({ outline }) => outline));
  choropleth.show("50");
  const [s24, s25, u1] = map.layers;
  assert.equal(s24.style.fillColor, SHARE_CLASSES[shareClass(66 / 600)].color);
  assert.equal(s25.style.fillColor, SHARE_CLASSES[5].color, "58% is over half");
  assert.equal(u1.style.fillOpacity, 0);
  choropleth.show("10");
  assert.equal(s25.style.fillColor, SHARE_CLASSES[3].color, "20% at 1 in 10");
});

test("a click opens the section, but not while a point is being aimed at, where a tap moves the map", () => {
  const { opened } = mount();
  map.layers[1].fire("click");
  assert.deepEqual(opened, ["seksyen-25"]);
  const aiming = mount({ aiming: true });
  map.layers.at(-1).fire("click");
  assert.deepEqual(aiming.opened, []);
});

test("the tooltip names the section, its share of squares and its businesses with water, at the size on show", () => {
  const { choropleth } = mount();
  choropleth.show("50");
  const tip = map.layers[1].tooltip;
  assert.equal(tip.options.sticky, true);
  const node = tip.content();
  assert.equal(node.textContent, tooltipLines(SECTIONS[1], "50").join(""));
  assert.deepEqual(tooltipLines(SECTIONS[1], "50"), ["Seksyen 25", "58% of its 90 m squares get water", "2 of 3 businesses get water", "Tap to open"]);
  assert.deepEqual(tooltipLines(SECTIONS[2], "50").slice(1, 3), ["0% of its 90 m squares get water", "0 of 1 businesses get water"]);
  choropleth.show("10");
  assert.match(map.layers[1].tooltip.content().textContent, /20% of its/);
});

test("hovering or a row of the table lifts one section's outline, and only one at a time", () => {
  const { choropleth } = mount();
  choropleth.show("50");
  map.layers[0].fire("mouseover");
  assert.ok(map.layers[0].style.weight > 1);
  choropleth.highlight("seksyen-25");
  assert.ok(map.layers[1].style.weight > 1);
  assert.equal(map.layers[0].style.weight, 1, "the last one lifted goes back");
  choropleth.highlight(null);
  assert.equal(map.layers[1].style.weight, 1);
  assert.equal(map.layers[1].fronted, 1);
});

// ---------- the key ----------

test("the key has a heading in the area's own word for a section and one swatch per class", () => {
  const key = choroplethKey(SECTION_WORD);
  assert.match(key.querySelector(".legend-heading").textContent, /each section's 90 m squares/);
  const items = key.querySelectorAll("li").map((item) => item.textContent);
  assert.deepEqual(items, ["None", "Under 5%", "5–15%", "15–30%", "30–50%", "Over 50%"]);
  assert.deepEqual(key.querySelectorAll(".choro-swatch").map((swatch) => swatch.getAttribute("class")),
    ["choro-swatch sq-0", "choro-swatch sq-1", "choro-swatch sq-2", "choro-swatch sq-3", "choro-swatch sq-4", "choro-swatch sq-5"]);
});

test("in Bahasa Melayu the key and tooltip read naturally, with the area's own word", () => {
  useLang("ms");
  try {
    assert.match(choroplethKey(SECTION_WORD).querySelector(".legend-heading").textContent, /setiap seksyen/);
    assert.deepEqual(tooltipLines(SECTIONS[1], "50").slice(1), ["58% petak 90 m di sini dinaiki air", "2 daripada 3 perniagaan dimasuki air", "Ketik untuk buka"]);
  } finally {
    useLang("en");
  }
});
