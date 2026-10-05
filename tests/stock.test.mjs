// Run from 11_Platform_Draft:  node --test tests/stock.test.mjs
// The "fill in from a photo of your stock" card on the Flood cost tab (stock.js, plan card G1), on the fake DOM.
// Gemini's guesses are shown as guesses, the items under the modelled water follow the flood size on show, and nothing
// reaches the cost form until the owner presses "Use these figures".
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { MAX_PHOTOS, combine, createStockCard, raiseStep } from "../app/static/js/stock.js";
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

const shown = (extra = {}) => ({ photos: [RESULT], off: [], ...extra });

function mount() {
  const calls = { photos: [], used: [], raised: [], toggled: [], cleared: 0 };
  const card = createStockCard({ onPhoto: (file) => calls.photos.push(file), onUse: (value) => calls.used.push(value),
    onRaise: (cm) => calls.raised.push(cm), onToggle: (key) => calls.toggled.push(key), onClear: () => { calls.cleared += 1; } });
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
  card.render(shown(), "20");
  const rows = card.node.querySelectorAll("tr").slice(1).map((row) => row.textContent);
  assert.equal(rows.length, 3);
  assert.match(rows[0], /Rice sacks.*on the floor.*RM\s?800.*RM\s?1,200.*Under water/);
  assert.match(rows[2], /Top shelf snacks.*150 cm.*Above the water/);
  assert.match(text(), /1 in 20 years.*0\.30 m of water above your floor.*2 of 3 items/);
  assert.match(text(), /Gemini's rough guess from 1 photo\(s\), not a valuation/);
  card.render(shown(), "50");
  assert.match(card.node.querySelectorAll("tr")[3].textContent, /Under water/);
  card.render(shown(), "10");
  assert.match(text(), /no water above your floor/);
});

test("Use these figures hands the midpoint to the form, and says what it is", () => {
  const { card, calls, button, text } = mount();
  card.render(shown(), "20");
  assert.match(text(), /RM\s?3,400/);
  button("Use these figures").click();
  assert.deepEqual(calls.used, [3400]);
});

test("a photo that is not the inside of a shop says so and offers nothing to use", () => {
  const { card, text, button } = mount();
  card.render({ photos: [], off: [], reject: "notInside" }, "20");
  assert.match(text(), /does not look like the inside of a shop/);
  assert.equal(button("Use these figures"), undefined);
});

test("busy and failed states say so, and a failure keeps the last result", () => {
  const { card, text } = mount();
  card.render({ busy: true }, "20");
  assert.match(text(), /Reading the photo…/);
  assert.equal(card.node.querySelector("input").disabled, true);
  card.render(shown({ error: "Too many requests. Please wait a few minutes." }), "20");
  assert.match(card.node.querySelector('[role="alert"]').textContent, /Too many requests/);
  assert.match(text(), /Rice sacks/);
});

// ---------- review fixes ----------

test("the photo picker is kept across renders", () => {
  const { card } = mount();
  card.render(undefined, "20");
  const input = card.node.querySelector("input");
  card.render(shown(), "20");
  assert.equal(card.node.querySelector("input"), input);
});

test("a shop with nothing seen offers nothing to use", () => {
  const { card, text, button } = mount();
  card.render({ photos: [], off: [], reject: "nothing" }, "20");
  assert.match(text(), /Gemini saw nothing that water could spoil/);
  assert.equal(button("Use these figures"), undefined);
});

test("the water line names the floor height it was worked out with", () => {
  const { card, text } = mount();
  card.render(shown(), "20");
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
  card.render(shown(), "20");
  assert.equal(input.disabled, false);
  assert.equal(document.activeElement, input);

  card.render(shown({ busy: true }), "20");
  const elsewhere = {};
  document.activeElement = elsewhere;
  card.render(shown({ error: "x" }), "20");
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

// ---------- several photos, unticking, raising, saving ----------

const FREEZER = { item: "Chest freezer", kind: "equipment", lowest_cm: 0, value_rm_low: 1000, value_rm_high: 2000 };
const SECOND = { ...RESULT, estimate: { ...RESULT.estimate, items: [FREEZER], confidence: "low" } };

test("photos add up into one list, judged by the latest photo's water", () => {
  const sum = combine([RESULT, SECOND], [], "20");
  assert.deepEqual(sum.items.map((item) => item.key), ["0-0", "0-1", "0-2", "1-0"]);
  assert.equal(sum.count, 4);
  assert.deepEqual([sum.low, sum.high], [3600, 6200]);
  assert.deepEqual(sum.under, { count: 3, low: 3300, high: 5700 });
  assert.equal(sum.suggested, 4900);
  assert.equal(sum.raiseCm, 30, "rice and the freezer stand on the floor under 0.30 m");
  assert.equal(sum.confidence, "low");
});

test("an unticked item is listed but not counted", () => {
  const sum = combine([RESULT, SECOND], ["0-1"], "20");
  assert.equal(sum.items.find((item) => item.key === "0-1").isCounted, false);
  assert.deepEqual([sum.count, sum.low, sum.high], [3, 2100, 3700]);
  assert.equal(sum.under.count, 2);
});

test("the item lowest under the water sets how high things must go, and the form's answer that clears it", () => {
  const raised = { ...RESULT, estimate: { ...RESULT.estimate, items: [{ ...ITEMS[1] }] } };   // the fridge, 10 cm up
  assert.equal(combine([raised], [], "20").raiseCm, 20);
  assert.equal(combine([raised], [], "10").raiseCm, 0, "no water above the floor: nothing to raise");
  assert.deepEqual([raiseStep(20), raiseStep(15), raiseStep(51), raiseStep(100), raiseStep(160)], [50, 15, 100, 100, null]);
});

test("the card offers the raise answer, or says to move things out when no shelf is high enough", () => {
  const { card, calls, button, text } = mount();
  card.render(shown(), "20");
  assert.match(text(), /would need to go up 30 cm to stay dry/);
  button("Check 50 cm higher in the form").click();
  assert.deepEqual(calls.raised, [50]);
  card.render(shown(), "50");   // 1.70 m above the floor
  assert.match(text(), /go up 170 cm, more than a high shelf/);
  assert.equal(card.node.querySelectorAll("button").find((b) => /higher in the form/.test(b.textContent)), undefined);
});

test("a tick box per item hands its key to onToggle, and an unticked row says so", () => {
  const { card, calls } = mount();
  card.render(shown({ off: ["0-2"] }), "20");
  const boxes = card.node.querySelectorAll('[type="checkbox"]');
  assert.equal(boxes.length, 3);
  assert.equal(boxes[2].getAttribute("checked"), null);
  assert.equal(boxes[0].getAttribute("checked"), "");
  assert.match(card.node.querySelectorAll("tr")[3].getAttribute("class"), /is-off/);
  boxes[1].dispatch("change");
  assert.deepEqual(calls.toggled, ["0-1"]);
});

test("Use these figures counts only the ticked items", () => {
  const { card, calls, button } = mount();
  card.render(shown({ photos: [RESULT, SECOND], off: ["0-1"] }), "20");
  button("Use these figures").click();
  assert.deepEqual(calls.used, [2900]);
});

test("with everything unticked there is nothing to use or save", () => {
  const { card, button } = mount();
  card.render(shown({ off: ["0-0", "0-1", "0-2"] }), "20");
  assert.equal(button("Use these figures"), undefined);
  assert.equal(button("Save this list"), undefined);
});

test("the list saves as a text file of the ticked items, through a blob: link", async () => {
  const { card, button } = mount();
  const blobs = [];
  const real = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  URL.createObjectURL = (blob) => { blobs.push(blob); return "blob:test"; };
  URL.revokeObjectURL = () => {};
  try {
    card.render(shown({ off: ["0-2"] }), "20");
    button("Save this list").click();
  } finally {
    Object.assign(URL, { createObjectURL: real.create, revokeObjectURL: real.revoke });
  }
  assert.equal(blobs.length, 1);
  const file = await blobs[0].text();
  assert.match(file, /- Rice sacks: on the floor, RM\s?800 to RM\s?1,200/);
  assert.doesNotMatch(file, /Top shelf snacks/);
  assert.match(file, /Total, by Gemini's rough guess: RM\s?2,300 to RM\s?3,700/);
});

test("while a photo is read the list cannot change, and a short status line says what is counted", () => {
  const { card, button } = mount();
  card.render(shown({ busy: true, off: ["0-2"] }), "20");
  assert.ok(card.node.querySelectorAll('[type="checkbox"]').every((box) => box.disabled));
  assert.equal(button("Start again").disabled, true);
  const status = card.node.querySelector(".stock-status");
  assert.equal(status.getAttribute("aria-live"), "polite");
  assert.match(status.textContent, /2 of 3 items counted, worth RM\s?2,300 to RM\s?3,700/);
  assert.equal(card.node.querySelector(".stock-findings").getAttribute("aria-live"), null, "the long list is not read out again");
});

test("Start again moves focus to the card's heading", () => {
  const { card, button } = mount();
  card.render(shown(), "20");
  const heading = card.node.querySelector("h2");
  let focused = null;
  heading.focus = () => { focused = heading; };
  button("Start again").click();
  assert.equal(focused, heading);
  assert.equal(heading.getAttribute("tabindex"), "-1");
});

test("another place that is not busy does not take focus as if its photo was just read", () => {
  const { card } = mount();
  const input = card.node.querySelector('[type="file"]');
  let focused = 0;
  input.focus = () => { focused += 1; };
  document.body = {};
  document.activeElement = document.body;
  card.render({ busy: true }, "20", "a");
  card.render(undefined, "20", "b");
  assert.equal(focused, 0);
  card.render({ busy: true }, "20", "b");
  card.render(shown(), "20", "b");
  assert.equal(focused, 1);
});

test("the picker counts the photos and stops at the most, and Start again clears", () => {
  const { card, calls, button } = mount();
  card.render(shown(), "20");
  const input = card.node.querySelector("[type=\"file\"]");
  assert.match(card.node.querySelector(".photo-button").textContent, /Add another photo \(2 of 4\)/);
  card.render(shown({ photos: Array(MAX_PHOTOS).fill(RESULT) }), "20");
  assert.equal(input.disabled, true);
  assert.match(card.node.textContent, /That is 4 photos, the most/);
  button("Start again").click();
  assert.equal(calls.cleared, 1);
});

test("a photo that adds nothing keeps the list and says why", () => {
  const { card, text } = mount();
  assert.equal(combine([], [], "20"), null);
  card.render(shown({ reject: "nothing" }), "20");
  assert.match(text(), /Gemini saw nothing that water could spoil/);
  assert.match(text(), /Rice sacks/);
});
