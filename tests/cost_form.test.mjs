// Run from 11_Platform_Draft:  node --test tests/cost_form.test.mjs
// The Flood cost form (cost.js) on the fake DOM: it starts ready to answer, so one press of Estimate gives a figure.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createCost } from "../app/static/js/cost.js";
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
  cost.render(shop, null, undefined, undefined, "100");
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
  cost.render({ ...shop, id: "node-9", name: "Other" }, null, undefined, undefined, "100");
  assert.equal(mode.value, "size");
});
