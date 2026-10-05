// Run from 11_Platform_Draft:  node --test tests/cost_form.test.mjs
// The Flood cost form (cost.js) on the fake DOM: it starts ready to answer, so one press of Estimate gives a figure.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createCost, estimateState, isOwnAnswer, needsFirstLook } from "../app/static/js/cost.js";
import { planFigures } from "../app/static/js/plan.js";
import { installFakeDom } from "./fake_dom.mjs";
import { shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

/** The tab with a place on show. The fake DOM has no form controls collection, so one is given, reading the radios. */
function mount(options = {}) {
  const sent = [];
  const panel = document.createElement("section");
  const cost = createCost(panel, { onEstimate: (figures) => sent.push(figures), ...options });
  const form = panel.querySelector("form");
  const radios = form.querySelectorAll("input").filter((input) => input.getAttribute("name") === "mode");
  const mode = { get value() { return radios.find((radio) => radio.checked)?.getAttribute("value"); }, set value(next) { radios.forEach((radio) => { radio.checked = radio.getAttribute("value") === next; }); } };
  form.elements = { mode };
  form.reportValidity = () => true;
  cost.render(shop, null, undefined, undefined, "20");
  return { panel, cost, form, sent, mode, radios };
}

test("the form starts on a typical figure for a medium shop, with the shop size chosen and the value box away", () => {
  const { panel, mode } = mount();
  assert.equal(mode.value, "size");
  const size = panel.querySelector("select");
  assert.equal(size.value, "medium");
  assert.equal(size.parent.hidden, false);
  const value = panel.querySelector("#cost-value_at_risk_rm") ?? panel.querySelectorAll("input").find((input) => input.getAttribute("name") === "value_at_risk_rm");
  assert.equal(value.parent.parent.hidden, true);
  assert.notEqual(value.required, true, "an empty value box cannot block Estimate");
});

test("pressing Estimate with nothing typed sends a medium shop's typical figure", () => {
  const { form, sent } = mount();
  form.dispatch("submit");
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { value_at_risk_rm: 0, shop_size: "medium", floor_height_cm: 0, daily_takings_rm: 0, closed_days: 0, raise_cm: 0, measure_cost_rm: 0 });
});

test("a value filled in from the stock photo switches to the owner's own value", () => {
  const { panel, form, sent, mode, radios } = mount();
  const useStock = radios.find((radio) => radio.getAttribute("value") === "value");
  useStock.checked = true;
  useStock.dispatch("change");
  assert.equal(mode.value, "value");
  const value = panel.querySelectorAll("input").find((input) => input.getAttribute("name") === "value_at_risk_rm");
  value.value = "25000";
  form.dispatch("submit");
  assert.equal(sent[0].value_at_risk_rm, 25000);
  assert.equal(sent[0].shop_size, "");
});

test("another place gets the same ready-to-answer form, not the last place's mode", () => {
  const { cost, mode, radios } = mount();
  radios.find((radio) => radio.getAttribute("value") === "value").dispatch("change");
  mode.value = "value";
  cost.render({ ...shop, id: "node-9", name: "Other" }, null, undefined, undefined, "20");
  assert.equal(mode.value, "size");
});

// ---------- the tab opens with an answer ----------

const DEFAULT_FIGURES = { value_at_risk_rm: 0, shop_size: "medium", floor_height_cm: 0, daily_takings_rm: 0, closed_days: 0, raise_cm: 0, measure_cost_rm: 0 };
const field = (panel, name) => panel.querySelectorAll("input").find((input) => input.getAttribute("name") === name);

test("figures() gives what Estimate would send, so the tab can work out a first look when it opens", () => {
  const { cost, sent } = mount();
  assert.deepEqual(cost.figures(), DEFAULT_FIGURES);
  assert.equal(sent.length, 0, "asking for the figures sends nothing");
});

test("figures() gives none while the form holds a problem", () => {
  const { panel, cost, form } = mount();
  field(panel, "raise_cm").value = "30";   // a measure needs its cost too
  assert.equal(cost.figures(), null);
  field(panel, "raise_cm").value = "";
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
  field(panel, "raise_cm").value = "30";   // a measure without its cost
  form.dispatch("submit");
  const message = panel.querySelector(".form-error").textContent;
  assert.match(message, /give both how far to raise the stock and what it costs/);
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
