// Run from 11_Platform_Draft:  node --test tests/cost_form.test.mjs
// The Flood cost form (cost.js) on the fake DOM: it starts ready to answer, so one press of Estimate gives a figure.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createCost, estimateState, isOwnAnswer, needsFirstLook } from "../app/static/js/cost.js";
import { planFigures } from "../app/static/js/plan.js";
import { installFakeDom } from "./fake_dom.mjs";
import { shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

/** The tab with a place on show. */
function mount(options = {}) {
  const sent = [];
  const panel = document.createElement("section");
  const cost = createCost(panel, { onEstimate: (figures) => sent.push(figures), ...options });
  const form = panel.querySelector("form");
  form.reportValidity = () => true;
  cost.render(shop, null, undefined, undefined, "20");
  return { panel, cost, form, sent };
}

/** The radio of answer `value` in question group `name` (worth, floor, customers, spend, days, raise, measureCost). */
const radio = (panel, name, value) => panel.querySelectorAll("input").find((input) => input.getAttribute("name") === `cost-${name}` && input.getAttribute("value") === value);
const picked = (panel, name) => panel.querySelectorAll("input").find((input) => input.getAttribute("name") === `cost-${name}` && input.checked)?.getAttribute("value");
/** Tap an answer, as the owner does. */
function tap(panel, name, value) {
  for (const input of panel.querySelectorAll("input").filter((one) => one.getAttribute("name") === `cost-${name}`)) input.checked = false;
  const chosen = radio(panel, name, value);
  chosen.checked = true;
  chosen.dispatch("change");
}
const box = (panel, name) => panel.querySelectorAll("input").find((input) => input.getAttribute("name") === name);
const shown = (node) => !node.hidden && !node.parent?.hidden && !node.parent?.parent?.hidden;

test("the form starts ready: not sure of the value (a medium shop's typical figure), floor level, lost sales not sure, no measure", () => {
  const { panel } = mount();
  assert.deepEqual(["worth", "floor", "customers", "raise"].map((name) => picked(panel, name)), ["size", "0", "unsure", "0"]);
  assert.equal(panel.querySelector("select").value, "medium");
  assert.ok(shown(panel.querySelector("select")));
  assert.ok(!shown(box(panel, "value_at_risk_rm")), "no box to type in until Type my own");
  assert.notEqual(box(panel, "value_at_risk_rm").required, true, "an empty value box cannot block Estimate");
  assert.match(panel.textContent, /Not sure is fine: we use a typical figure for your shop's size\./);
  assert.match(panel.textContent, /Not sure is fine: we add 30% of the damage/);
});

test("the four questions come in order, each with its answers to tap", () => {
  const { panel } = mount();
  assert.deepEqual(panel.querySelectorAll(".question-title").map((legend) => legend.textContent), [
    "Things in your shop that water can spoil", "How high is your shop floor above the road?",
    "On a normal day, how many customers?", "What if you put things higher?"]);
  assert.match(panel.textContent, /kedai runcit has shelves of goods/, "an example that is not only a kedai runcit's");
});

test("each follow-on question is its own fieldset with a legend, so its answers are named", () => {
  const { panel } = mount();
  assert.deepEqual(panel.querySelectorAll(".sub-question").map((set) => [set.tagName.toLowerCase(), set.querySelector("legend").textContent]), [
    ["fieldset", "Each spends about"],
    ["fieldset", "If water comes in, how long would you close? Cleaning, drying, fixing and restocking."],
    ["fieldset", "What would that cost?"]]);
});

test("a box out of sight is switched off, so a figure left in it never blocks Estimate unseen", () => {
  const { panel } = mount();
  tap(panel, "floor", "own");
  box(panel, "floor_height_cm").value = "999";   // over the 300 cm limit
  assert.equal(box(panel, "floor_height_cm").disabled, false);
  tap(panel, "floor", "15");
  assert.equal(box(panel, "floor_height_cm").disabled, true);
  for (const name of ["value_at_risk_rm", "daily_takings_rm", "measure_cost_rm"]) assert.equal(box(panel, name).disabled, true, name);
  tap(panel, "raise", "50");
  tap(panel, "measureCost", "own");
  assert.equal(box(panel, "measure_cost_rm").disabled, false);
  tap(panel, "raise", "0");
  assert.equal(box(panel, "measure_cost_rm").disabled, true, "hidden with its question, though Type my own is still picked");
});

test("ringgit boxes start at 1, as the server takes them, and a measure cost under 1 is asked for again", () => {
  const { panel, cost } = mount();
  assert.deepEqual(["value_at_risk_rm", "measure_cost_rm", "floor_height_cm"].map((name) => box(panel, name).getAttribute("min")), ["1", "1", "0"]);
  tap(panel, "worth", "30000");
  tap(panel, "raise", "15");
  tap(panel, "measureCost", "own");
  box(panel, "measure_cost_rm").value = "0.5";
  assert.equal(cost.figures(), null);
});

test("Over RM 150k says it is a round figure, not a middle", () => {
  const { panel } = mount();
  tap(panel, "worth", "200000");
  assert.match(panel.textContent, /We count RM\s?200,000, a round figure for more than RM 150k\./);
  assert.ok(!/about the middle/.test(panel.textContent));
});

test("the 30% line shows only for Not sure, not while the owner's own sales box is empty", () => {
  const { panel } = mount();
  tap(panel, "customers", "own");
  assert.ok(!/Not sure is fine: we add 30%/.test(panel.textContent));
  box(panel, "daily_takings_rm").value = "400";
  box(panel, "daily_takings_rm").dispatch("input");
  assert.match(panel.textContent, /About RM\s?400 a day for 7 days: RM\s?2,800 of lost sales\./);
});

test("a tap on question 1 or 2 clears the photo's note on it", () => {
  const { panel, cost } = mount();
  cost.render(shop, 30, undefined, undefined, "20");
  assert.match(panel.textContent, /Filled in from your shop-front photo/);
  tap(panel, "floor", "0");
  assert.ok(!/Filled in from your shop-front photo/.test(panel.textContent));
});

test("every ready answer stays inside what the server takes (floodtools.ESTIMATE_MAX)", () => {
  const { panel, cost } = mount();
  const most = { value_at_risk_rm: 50_000_000, floor_height_cm: 300, daily_takings_rm: 1_000_000, closed_days: 365, raise_cm: 300, measure_cost_rm: 50_000_000 };
  tap(panel, "worth", "200000");
  tap(panel, "floor", "45");
  tap(panel, "customers", "150");
  tap(panel, "spend", "50");
  tap(panel, "days", "30");
  tap(panel, "raise", "100");
  tap(panel, "measureCost", "3500");
  const figures = cost.figures();
  for (const [name, limit] of Object.entries(most)) assert.ok(figures[name] <= limit, name);
  assert.deepEqual([figures.daily_takings_rm, figures.closed_days], [7500, 30]);
});

test("pressing Estimate with nothing tapped sends a medium shop's typical figure", () => {
  const { form, sent } = mount();
  form.dispatch("submit");
  assert.deepEqual(sent, [{ value_at_risk_rm: 0, shop_size: "medium", floor_height_cm: 0, daily_takings_rm: 0, closed_days: 0, raise_cm: 0, measure_cost_rm: 0 }]);
});

test("a range counts as about its middle and says so; a step counts as its height", () => {
  const { panel, cost } = mount();
  tap(panel, "worth", "30000");
  tap(panel, "floor", "15");
  assert.match(panel.textContent, /We count RM\s?30,000, about the middle of what you picked\./);
  assert.ok(!shown(panel.querySelector("select")), "the shop size goes away once a value is picked");
  assert.deepEqual(cost.figures(), { value_at_risk_rm: 30000, shop_size: "", floor_height_cm: 15, daily_takings_rm: 0, closed_days: 0, raise_cm: 0, measure_cost_rm: 0 });
});

test("customers times what each spends gives the day's sales, times the days closed the lost sales", () => {
  const { panel, cost } = mount();
  const [spend, days] = panel.querySelectorAll(".sub-question");
  assert.ok(!shown(spend) && !shown(days), "no spend or days closed until the customers are answered");
  tap(panel, "customers", "35");
  assert.ok(shown(spend) && shown(days));
  tap(panel, "spend", "15");
  tap(panel, "days", "14");
  assert.match(panel.textContent, /About RM\s?525 a day for 14 days: RM\s?7,350 of lost sales\./);
  assert.deepEqual([cost.figures().daily_takings_rm, cost.figures().closed_days], [525, 14]);
  tap(panel, "customers", "own");
  box(panel, "daily_takings_rm").value = "800";
  assert.deepEqual([cost.figures().daily_takings_rm, cost.figures().closed_days], [800, 14]);
  tap(panel, "customers", "unsure");
  assert.deepEqual([cost.figures().daily_takings_rm, cost.figures().closed_days], [0, 0], "not sure: the guideline's 30% on the server");
});

test("putting things higher needs a value, not Not sure, and counts the picked cost", () => {
  const { panel, cost, form } = mount();
  tap(panel, "raise", "50");
  assert.equal(cost.figures(), null);
  form.dispatch("submit");
  assert.match(panel.querySelector(".form-error").textContent, /pick a value in question 1, not Not sure/);
  tap(panel, "worth", "100000");
  assert.deepEqual([cost.figures().raise_cm, cost.figures().measure_cost_rm], [50, 1250]);
  tap(panel, "measureCost", "own");
  assert.equal(cost.figures(), null, "Type my own with nothing typed");
  box(panel, "measure_cost_rm").value = "900";
  assert.equal(cost.figures().measure_cost_rm, 900);
  tap(panel, "raise", "0");
  assert.deepEqual([cost.figures().raise_cm, cost.figures().measure_cost_rm], [0, 0]);
});

test("Use these figures from the photo inside the shop picks Type my own with Gemini's value, said to be its guess", () => {
  const { panel, cost } = mount();
  const items = [{ item: "Rice", kind: "stock", lowest_cm: 0, value_rm_low: 2000, value_rm_high: 3000 }];
  const flood = { water_above_floor_m: 0.3, under_water: [0], value_rm_low: 2000, value_rm_high: 3000 };
  const result = { estimate: { is_shop_inside: true, items, confidence: "medium", reasoning: "" }, floor_height_cm: 0,
    total: { value_rm_low: 2000, value_rm_high: 3000 }, suggested_value_rm: 2500, per_flood: { 10: flood, 20: flood, 50: flood } };
  cost.render(shop, null, undefined, { result }, "20");
  panel.querySelectorAll("button").find((button) => button.textContent === "Use these figures").click();
  assert.equal(picked(panel, "worth"), "own");
  assert.equal(cost.figures().value_at_risk_rm, 2500);
  assert.match(panel.textContent, /Filled in from your photo inside the shop: Gemini's rough guess/);
});

test("the shop-front photo's floor fills question 2 until the owner answers it", () => {
  const { panel, cost } = mount();
  cost.render(shop, 30, undefined, undefined, "20");
  assert.equal(picked(panel, "floor"), "own");
  assert.equal(cost.figures().floor_height_cm, 30);
  tap(panel, "floor", "45");
  cost.render(shop, 60, undefined, undefined, "20");
  assert.equal(cost.figures().floor_height_cm, 45, "the owner's own answer stays");
});

test("each place keeps its own answers, and a new place starts ready", () => {
  const { panel, cost } = mount();
  tap(panel, "worth", "200000");
  cost.render({ ...shop, id: "node-9", name: "Other" }, null, undefined, undefined, "20");
  assert.equal(picked(panel, "worth"), "size");
  cost.render(shop, null, undefined, undefined, "20");
  assert.equal(picked(panel, "worth"), "200000");
});

// ---------- the tab opens with an answer ----------

const DEFAULT_FIGURES = { value_at_risk_rm: 0, shop_size: "medium", floor_height_cm: 0, daily_takings_rm: 0, closed_days: 0, raise_cm: 0, measure_cost_rm: 0 };

test("figures() gives what Estimate would send, so the tab can work out a first look when it opens", () => {
  const { cost, sent } = mount();
  assert.deepEqual(cost.figures(), DEFAULT_FIGURES);
  assert.equal(sent.length, 0, "asking for the figures sends nothing");
});

test("figures() gives none while the form holds a problem", () => {
  const { cost, form } = mount();
  form.checkValidity = () => false;        // a required value left empty, as the browser reports it
  assert.equal(cost.figures(), null);
});

test("the heading has the size of flood on show, and picking another one tells the page", () => {
  const picked = [];
  const { panel } = mount({ onPick: (rp) => picked.push(rp) });
  const buttons = panel.querySelector(".cost-picker").querySelectorAll("button");
  assert.deepEqual(buttons.map((button) => button.getAttribute("aria-pressed")), ["false", "true", "false"]);
  buttons[2].dispatch("click");
  assert.deepEqual(picked, ["50"]);
});

test("another size of flood redraws the answer for it, with no new estimate", () => {
  const { panel, cost, sent } = mount();
  cost.render(shop, null, { result: ANSWER }, undefined, "20");
  assert.match(panel.querySelector(".cost-results").textContent, /if a 1 in 20 years flood comes/);
  cost.render(shop, null, { result: ANSWER }, undefined, "10");
  assert.match(panel.querySelector(".cost-results").textContent, /if a 1 in 10 years flood comes/);
  assert.equal(panel.querySelector(".cost-picker").querySelectorAll("button")[0].getAttribute("aria-pressed"), "true");
  assert.equal(sent.length, 0);
});

test("the answer comes before the form, and the photo of the stock after it", () => {
  const { panel } = mount();
  const grid = panel.querySelector(".cost-grid");
  assert.deepEqual(grid.children.map((child) => child.getAttribute("class")), ["surface cost-results", "surface cost-form", "surface stock-card"]);
});

const ANSWER = { per_flood: { 10: {}, 20: {}, 50: {} }, inputs: DEFAULT_FIGURES, basis: { direct: "a", indirect: "b" }, method: "", limits: "",
  expected_yearly_loss_rm: 100, loss_over_years: { years: 10, discount_rate: 0.04, present_value_rm: 800 }, measure: null };
for (const name of ["direct_damage_rm", "indirect_loss_rm", "total_rm", "water_above_floor_m"]) {
  for (const rp of ["10", "20", "50"]) ANSWER.per_flood[rp][name] = 1;
}

/** The answer's box, with where it sits on screen stubbed in, and a record of each scroll asked for. */
function placedOutput(panel, top) {
  const output = panel.querySelector(".cost-results");
  const scrolls = [];
  output.getBoundingClientRect = () => ({ top });
  output.scrollIntoView = (options) => scrolls.push(options);
  globalThis.innerHeight = 800;
  return scrolls;
}

test("after the owner presses Estimate, an answer above the screen is scrolled into view", () => {
  const { panel, cost } = mount();
  const scrolls = placedOutput(panel, -600);
  cost.render(shop, null, { busy: true }, undefined, "20");
  cost.render(shop, null, { result: ANSWER }, undefined, "20");
  assert.equal(scrolls.length, 1);
  assert.equal(scrolls[0].block, "start");
});

test("the first look the tab works out itself, or an answer already on screen, scrolls nothing", () => {
  const { panel, cost } = mount();
  const scrolls = placedOutput(panel, -600);
  cost.render(shop, null, { busy: true, assumed: true }, undefined, "20");
  cost.render(shop, null, { result: ANSWER, assumed: true }, undefined, "20");
  assert.equal(scrolls.length, 0, "a first look");
  const onScreen = placedOutput(panel, 120);
  cost.render(shop, null, { busy: true, result: ANSWER }, undefined, "20");
  cost.render(shop, null, { result: { ...ANSWER } }, undefined, "20");
  assert.equal(onScreen.length, 0, "already in view");
});

test("a failed press leaves the page where it is, with the error by the button", () => {
  const { panel, cost } = mount();
  const scrolls = placedOutput(panel, -600);
  cost.render(shop, null, { busy: true, result: ANSWER }, undefined, "20");
  cost.render(shop, null, { error: "Could not reach the server.", result: ANSWER }, undefined, "20");
  assert.equal(scrolls.length, 0);
  assert.equal(panel.querySelector(".form-error").textContent, "Could not reach the server.");
});

test("screen readers hear a short line when the owner's estimate is in, and nothing for a first look", () => {
  const { panel, cost } = mount();
  const status = panel.querySelector('[role="status"]');
  cost.render(shop, null, { busy: true, assumed: true }, undefined, "20");
  assert.equal(panel.querySelector(".cost-results").textContent, "Working it out…", "no invitation to press while it works");
  cost.render(shop, null, { result: ANSWER, assumed: true }, undefined, "20");
  assert.equal(status.textContent, "");
  cost.render(shop, null, { busy: true, result: ANSWER, assumed: true }, undefined, "20");
  cost.render(shop, null, { result: { ...ANSWER }, assumed: false }, undefined, "20");
  assert.match(status.textContent, /^Your estimate: RM\s?1 if a 1 in 20 years flood comes$/);
  assert.equal(panel.querySelector(".cost-results").getAttribute("aria-live"), null, "the whole answer is not read out");
});

// ---------- the estimate's states, as main.js keeps them ----------

const R1 = { inputs: { shop_size: "medium" } };
const R2 = { inputs: { shop_size: "small" } };

test("a first look: working, then done, and a failure is silent", () => {
  assert.deepEqual(estimateState.busy(undefined, true), { busy: true, result: undefined, assumed: true });
  assert.deepEqual(estimateState.done(R1, true), { result: R1, assumed: true });
  assert.deepEqual(estimateState.failed(undefined, "down", true), { assumed: true }, "no error the owner did not cause");
});

test("the owner's press after a first look becomes theirs, and the plan uses it only then", () => {
  const first = estimateState.done(R1, true);
  const working = estimateState.busy(first, false);
  assert.deepEqual(working, { busy: true, result: R1, assumed: true }, "the first look stays marked while it works");
  const pressed = estimateState.done(R2, false);
  assert.ok(isOwnAnswer(working, pressed));
  assert.deepEqual(planFigures({ estimates: { a: pressed }, photos: {} }, "a"), R2.inputs);
  const failed = estimateState.failed(first, "down", false);
  assert.deepEqual(failed, { error: "down", result: R1, assumed: true });
  assert.ok(!isOwnAnswer(working, failed));
  assert.deepEqual(planFigures({ estimates: { a: failed }, photos: {} }, "a"), {}, "still only a first look");
});

test("a first look is worked out once: on Flood cost, for a place with no estimate yet", () => {
  const state = (tab, estimates = {}) => ({ tab, placeKey: "a", estimates });
  assert.ok(needsFirstLook(state("cost"), shop));
  assert.ok(!needsFirstLook(state("cost", { a: { busy: true, assumed: true } }), shop), "not while one is on its way");
  assert.ok(!needsFirstLook(state("cost", { a: { assumed: true } }), shop), "not again after one failed");
  assert.ok(!needsFirstLook(state("business"), shop));
  assert.ok(!needsFirstLook(state("cost"), undefined));
});

test("another size of flood keeps the form's own message, and neither scrolls nor speaks", () => {
  const { panel, cost, form } = mount();
  const done = { result: ANSWER };   // the store keeps the same estimate when only the size changes
  cost.render(shop, null, done, undefined, "20");
  tap(panel, "raise", "50");   // a measure with no value of one's own
  form.dispatch("submit");
  const message = panel.querySelector(".form-error").textContent;
  assert.match(message, /pick a value in question 1/);
  const scrolls = placedOutput(panel, -600);
  cost.render(shop, null, done, undefined, "50");
  assert.equal(panel.querySelector(".form-error").textContent, message);
  assert.equal(scrolls.length, 0);
  assert.equal(panel.querySelector('[role="status"]').textContent, "");
});

test("the note under the picker names the area's own bigger flood, as on My business", () => {
  const { panel } = mount({ floodExample: (place) => (place.id === shop.id ? "2021-12" : null) });
  assert.match(panel.querySelector(".cost-picker").textContent, /Floods bigger than 1 in 50 years, such as December 2021, are not shown\./);
});
