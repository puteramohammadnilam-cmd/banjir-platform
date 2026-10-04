// Run from 11_Platform_Draft:  node --test tests/overview.test.mjs
// The Area overview's list of businesses (overview.js createDirectory) and the words that name the area, on the small
// fake DOM in tests/fake_dom.mjs: a search that could mean several businesses shows them all and says how many, one that
// matches none says why and what to do next, and the search's heading names the area it covers.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { SQUARE_RAMP } from "../app/static/js/cells.js";
import { BANDS, h } from "../app/static/js/dom.js";
import { createDirectory, renderAreaLabels, renderLegend } from "../app/static/js/overview.js";
import { installFakeDom } from "./fake_dom.mjs";
import { HOME, shop } from "./point_fixtures.mjs";

const dobi = (id, name) => ({ ...shop, id, name });
const PREMISES = [dobi("d-1", "DOBI DHOLPIN"), dobi("d-2", "Dobi DIY Selesa"), dobi("d-3", "Dobi Queen"), shop];

beforeEach(() => installFakeDom());

/** The list with its filter, status line, next steps and column heads; `ways(calls)` gives the optional ways on. */
function mount(ways = {}) {
  const parts = { list: h("ol"), filter: h("input"), status: h("p"), next: h("div"), head: h("div") };
  const opened = [];
  const calls = [];
  const directory = createDirectory(parts, PREMISES, { area: HOME, onOpen: (id) => opened.push(id), ...ways(calls) });
  return { ...parts, directory, opened, calls };
}

const shownNames = (list) => list.children.filter((item) => !item.hidden).map((item) => item.querySelector(".name").textContent);
const buttonTexts = (node) => node.querySelectorAll("button").map((button) => button.textContent);
const BOTH_WAYS = (calls) => ({ onCheckPoint: (button) => calls.push(["check", button]), onOtherArea: () => calls.push(["area"]) });

test("a search several businesses match shows them all, says how many, and each row opens its business", () => {
  const { list, filter, status, next, head, directory, opened } = mount(BOTH_WAYS);
  directory.showMatches("dobi");
  assert.equal(filter.value, "dobi", "the filter box holds the search");
  assert.deepEqual(shownNames(list), ["DOBI DHOLPIN", "Dobi DIY Selesa", "Dobi Queen"]);
  assert.equal(status.textContent, "3 businesses match “dobi”. Pick yours.");
  assert.equal(next.hidden, true, "no next steps while the list has rows");
  assert.equal(head.hidden, false);
  list.children.find((item) => !item.hidden && item.textContent.includes("Queen")).querySelector("button").click();
  assert.deepEqual(opened, ["d-3"]);
});

test("a search that matches nothing says the list misses shops, with a way to check the spot and to pick another area", () => {
  const { list, status, next, head, directory, calls } = mount(BOTH_WAYS);
  directory.showMatches("Kedai Runcit Pak Ali");
  assert.deepEqual(shownNames(list), []);
  assert.equal(status.textContent, `Not on our list for ${HOME.name}. Our list comes from a public map and misses some shops.`);
  assert.equal(head.hidden, true, "no column heads over an empty list");
  assert.equal(next.hidden, false);
  assert.deepEqual(buttonTexts(next), ["Check the spot on the map", "Pick another area"]);
  const [check, area] = next.querySelectorAll("button");
  check.dispatch("click", { currentTarget: check });   // the button, for focus to go back to on Cancel
  area.click();
  assert.deepEqual(calls, [["check", check], ["area"]]);
});

test("the next steps leave out what this build or this area cannot do", () => {
  const { next, directory } = mount(() => ({ onCheckPoint: null, onOtherArea: () => {} }));
  directory.showMatches("nothing");
  assert.deepEqual(buttonTexts(next), ["Pick another area"]);
  const bare = mount(() => ({}));
  bare.directory.showMatches("nothing");
  assert.equal(bare.next.hidden, true, "with no way on, no empty row of buttons");
});

test("a search one business matches says so in the singular", () => {
  const { status, directory } = mount(() => ({}));
  directory.showMatches(shop.name);
  assert.equal(status.textContent, `1 business matches “${shop.name}”.`);
});

test("typing in the filter filters quietly, with the plain message when nothing matches and no search's count", () => {
  const { list, filter, status, next, directory } = mount(BOTH_WAYS);
  directory.showMatches("dobi");
  filter.value = "queen";
  filter.dispatch("input");
  assert.deepEqual(shownNames(list), ["Dobi Queen"]);
  assert.equal(status.textContent, "", "the search's count goes once the filter is typed in");
  filter.value = "zzz";
  filter.dispatch("input");
  assert.equal(status.textContent, "No business matches that filter.");
  assert.equal(next.hidden, false, "the ways on are there for a typed filter too");
  filter.value = "";
  filter.dispatch("input");
  assert.equal(shownNames(list).length, PREMISES.length);
  assert.equal(status.textContent, "");
  assert.equal(next.hidden, true);
});

test("the search's heading names the area it covers, by its short name", () => {
  const elements = new Map();
  globalThis.document.getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, h(id === "finder-hero-label" ? "label" : "p"));
    return elements.get(id);
  };
  renderAreaLabels(HOME);
  assert.equal(elements.get("finder-hero-label").textContent, `Find your shop in ${HOME.name}`);
});

// ---------- the map's key ----------

test("the key has two groups: the dots' five classes with no water and the relief centre, and the squares' ramp", () => {
  const legend = h("ul");
  renderLegend(legend, true);
  const [dots, squares] = legend.querySelectorAll(".legend-group");
  assert.deepEqual(legend.children.map((group) => group.querySelector(".legend-heading").textContent),
    ["Dots: water at each business", "Squares: the model's 90 m squares, darker = deeper"]);
  assert.deepEqual(dots.querySelectorAll(".swatch").map((swatch) => swatch.getAttribute("class")),
    [...BANDS.map((_, i) => `swatch band-${i + 1}`), "swatch swatch-dry"]);
  assert.ok(dots.querySelector(".shelter-pin"), "the relief centre is a dot's kind of mark");
  assert.deepEqual(squares.querySelector(".square-strip").children.map((step) => step.getAttribute("class")),
    SQUARE_RAMP.map((_, i) => `sq-${i + 1}`), "one step for each step of the ramp, shallowest first");
  assert.deepEqual(squares.querySelectorAll(".muted").map((end) => end.textContent), ["under 0.9 m", "3 m or more"]);
  assert.equal(squares.querySelector(".square-strip").getAttribute("aria-hidden"), "true", "the heading and the two ends say it all");
});

test("the key leaves out the relief centre when the area has none", () => {
  const legend = h("ul");
  renderLegend(legend, false);
  assert.equal(legend.querySelector(".shelter-pin"), null);
  assert.equal(legend.querySelectorAll(".swatch").length, BANDS.length + 1);
});
