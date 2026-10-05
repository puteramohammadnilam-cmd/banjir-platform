// Run from 11_Platform_Draft:  node --test tests/stock.test.mjs
// The "fill in from a photo of your stock" card on the Flood cost tab (stock.js, plan card G1), on the fake DOM.
// Gemini's guesses are shown as guesses, the items under the modelled water follow the flood size on show, and nothing
// reaches the cost form until the owner presses "Use these figures".
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createStockCard } from "../app/static/js/stock.js";
import { installFakeDom } from "./fake_dom.mjs";

const ITEMS = [
  { item: "Rice sacks", kind: "stock", lowest_cm: 0, value_rm_low: 800, value_rm_high: 1200 },
  { item: "Drinks fridge", kind: "equipment", lowest_cm: 10, value_rm_low: 1500, value_rm_high: 2500 },
  { item: "Top shelf snacks", kind: "stock", lowest_cm: 150, value_rm_low: 300, value_rm_high: 500 },
];
const RESULT = {
  estimate: { is_shop_inside: true, items: ITEMS, confidence: "medium", reasoning: "A small grocery." },
  floor_height_cm: 30,
  total: { value_rm_low: 2600, value_rm_high: 4200 },
  suggested_value_rm: 3400,
  per_flood: {
    10: { water_above_floor_m: 0, under_water: [], value_rm_low: 0, value_rm_high: 0 },
    20: { water_above_floor_m: 0.3, under_water: [0, 1], value_rm_low: 2300, value_rm_high: 3700 },
    50: { water_above_floor_m: 1.7, under_water: [0, 1, 2], value_rm_low: 2600, value_rm_high: 4200 },
  },
};

beforeEach(() => installFakeDom());

function mount() {
  const calls = { photos: [], used: [] };
  const card = createStockCard({ onPhoto: (file) => calls.photos.push(file), onUse: (value) => calls.used.push(value) });
  return { card, calls, text: () => card.node.textContent, button: (words) => card.node.querySelectorAll("button").find((b) => b.textContent === words) };
}

test("before a photo it explains itself and offers only the photo picker", () => {
  const { card, text, button } = mount();
  card.render(undefined, "20");
  assert.match(text(), /Gemini lists what it sees and guesses a rough value/);
  assert.match(text(), /not saved by this tool/);
  assert.equal(button("Use these figures"), undefined);
  const input = card.node.querySelector("input");
  assert.equal(input.getAttribute("accept"), "image/jpeg,image/png,image/webp");
});

test("a picked file goes to onPhoto", () => {
  const { card, calls } = mount();
  card.render(undefined, "20");
  const input = card.node.querySelector("input");
  input.dispatch("change", { target: { files: ["the-file"] } });
  assert.deepEqual(calls.photos, ["the-file"]);
});

test("the items are listed with Gemini's guesses, and the ones under water follow the flood size on show", () => {
  const { card, text } = mount();
  card.render({ result: RESULT }, "20");
  const rows = card.node.querySelectorAll("tr").slice(1).map((row) => row.textContent);
  assert.equal(rows.length, 3);
  assert.match(rows[0], /Rice sacks.*on the floor.*RM\s?800.*RM\s?1,200.*Under water/);
  assert.match(rows[2], /Top shelf snacks.*150 cm.*Above the water/);
  assert.match(text(), /1 in 20 years.*0\.30 m of water above your floor.*2 of 3 items/);
  assert.match(text(), /Gemini's rough guess from one photo, not a valuation/);
  card.render({ result: RESULT }, "50");
  assert.match(card.node.querySelectorAll("tr")[3].textContent, /Under water/);
  card.render({ result: RESULT }, "10");
  assert.match(text(), /no water above your floor/);
});

test("Use these figures hands the midpoint to the form, and says what it is", () => {
  const { card, calls, button, text } = mount();
  card.render({ result: RESULT }, "20");
  assert.match(text(), /RM\s?3,400/);
  button("Use these figures").click();
  assert.deepEqual(calls.used, [3400]);
});

test("a photo that is not the inside of a shop says so and offers nothing to use", () => {
  const { card, text, button } = mount();
  const outside = { ...RESULT, estimate: { ...RESULT.estimate, is_shop_inside: false, items: [] }, per_flood: null, suggested_value_rm: null, total: null };
  card.render({ result: outside }, "20");
  assert.match(text(), /does not look like the inside of a shop/);
  assert.equal(button("Use these figures"), undefined);
});

test("busy and failed states say so, and a failure keeps the last result", () => {
  const { card, text } = mount();
  card.render({ busy: true }, "20");
  assert.match(text(), /Reading the photo…/);
  assert.equal(card.node.querySelector("input").disabled, true);
  card.render({ error: "Too many requests. Please wait a few minutes.", result: RESULT }, "20");
  assert.match(card.node.querySelector('[role="alert"]').textContent, /Too many requests/);
  assert.match(text(), /Rice sacks/);
});

// ---------- review fixes ----------

test("the photo picker is kept across renders", () => {
  const { card } = mount();
  card.render(undefined, "20");
  const input = card.node.querySelector("input");
  card.render({ result: RESULT }, "20");
  assert.equal(card.node.querySelector("input"), input);
});

test("a shop with nothing seen offers nothing to use", () => {
  const { card, text, button } = mount();
  const empty = { ...RESULT, estimate: { ...RESULT.estimate, items: [] }, total: { value_rm_low: 0, value_rm_high: 0 }, suggested_value_rm: 0,
    per_flood: { 10: RESULT.per_flood[10], 20: { ...RESULT.per_flood[100], under_water: [], value_rm_low: 0, value_rm_high: 0 }, 50: RESULT.per_flood[10] } };
  card.render({ result: empty }, "20");
  assert.match(text(), /Gemini saw nothing that water could spoil/);
  assert.equal(button("Use these figures"), undefined);
});

test("the water line names the floor height it was worked out with", () => {
  const { card, text } = mount();
  card.render({ result: RESULT }, "20");
  assert.match(text(), /with the floor 30 cm above the street/);
});

// ---------- review batch 3 ----------

test("the photo picker gets focus back when the photo has been read, if the page took it", () => {
  const { card } = mount();
  const body = {};
  document.body = body;
  card.render(undefined, "20");
  const input = card.node.querySelector("input");
  input.focus = () => { document.activeElement = input; };
  document.activeElement = input;
  card.render({ busy: true }, "20");
  assert.equal(input.disabled, true);
  document.activeElement = body;   // the disabled picker lost it
  card.render({ result: RESULT }, "20");
  assert.equal(input.disabled, false);
  assert.equal(document.activeElement, input);

  card.render({ busy: true, result: RESULT }, "20");
  const elsewhere = {};
  document.activeElement = elsewhere;
  card.render({ result: RESULT, error: "x" }, "20");
  assert.equal(document.activeElement, elsewhere, "focus the user moved is left alone");
});

test("with the AI switched off the photo picker is off and a line says why", () => {
  const card = createStockCard({ onPhoto() {}, onUse() {}, isReady: false });
  card.render(undefined, "20");
  const input = card.node.querySelector("input");
  assert.equal(input.disabled, true);
  assert.equal(card.node.querySelector(".photo-button").getAttribute("aria-disabled"), "true");
  assert.match(card.node.textContent, /Needs the AI assistant, which is switched off in this test build\./);
  card.render({ busy: false }, "50");   // a later render does not switch it back on
  assert.equal(input.disabled, true);
});

test("with the AI on the picker is on and there is no such line", () => {
  const { card, text } = mount();
  card.render(undefined, "20");
  assert.equal(card.node.querySelector("input").disabled, false);
  assert.equal(card.node.querySelector(".photo-button").getAttribute("aria-disabled"), null);
  assert.doesNotMatch(text(), /switched off/);
});
