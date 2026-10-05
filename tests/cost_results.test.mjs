// Run from 11_Platform_Draft:  node --test tests/cost_results.test.mjs
// The Flood cost answer (cost.js results), on the small fake DOM: the key figure is the size of flood on show, the yearly
// loss reads as a floor, and the flat shop-size figure says depth does not count.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { results } from "../app/static/js/cost.js";
import { installFakeDom } from "./fake_dom.mjs";

beforeEach(() => installFakeDom());

const flood = (above, direct, indirect, share) => ({
  depth_m: above + 0.1, water_above_floor_m: above, damage_share: share, direct_damage_rm: direct, indirect_loss_rm: indirect,
  total_rm: direct + indirect,
});
const result = (per_flood) => ({
  per_flood, basis: { direct: "a", indirect: "b" }, expected_yearly_loss_rm: 3465, method: "", limits: "",
  loss_over_years: { years: 10, discount_rate: 0.04, present_value_rm: 28102 }, measure: null,
});
// a medium shop on the typical figure: the same damage in every flood that reaches the floor (the case in the report)
const FLAT = result({ 10: flood(0.95, 31647, 3000, null), 20: flood(1.48, 31647, 3000, null), 50: flood(1.71, 31647, 3000, null) });
const OWN = result({ 10: flood(0, 0, 0, 0), 20: flood(0.5, 19000, 5700, 0.38), 50: flood(1, 27000, 8100, 0.54) });
const text = (nodes) => nodes.map((node) => node.textContent).join(" | ");

test("the yearly loss says it is a floor and why", () => {
  const shown = text(results(FLAT));
  assert.match(shown, /at least RM\s?3,465/);
  assert.match(shown, /more frequent than 1 in 10 years are not in the model/);
  assert.match(shown, /bigger than 1 in 50 years are counted as if they cost the same as a 1 in 50 years flood/);
});

test("the key figure is the flood size on show: its cost, its water in the model and its chance", () => {
  const [figures] = results(FLAT, { rp: "20" });   // no basis line: these results name no inputs
  const key = figures.children[0];
  assert.equal(key.getAttribute("class"), "figure-box is-key");
  assert.match(key.textContent, /about RM\s?34,647/);
  assert.match(key.textContent, /if a 1 in 20 years flood comes/);
  assert.match(key.textContent, /Water in the model: 1\.58 m at the street, 1\.48 m above your floor\./);
  assert.match(key.textContent, /\b40% chance of a flood this big or bigger in the next 10 years\./);
  assert.match(text(results(FLAT, { rp: "50" })), /if a 1 in 50 years flood comes.* 18% chance of a flood this big or bigger/s);
  assert.match(text(results(FLAT)), /if a 1 in 50 years flood comes/, "the page's default size when none is given");
});

test("the discounted sum over 10 years moves into How this is worked out", () => {
  const how = results(FLAT).find((node) => node.tagName.toLowerCase() === "details");
  assert.match(how.textContent, /Over 10 years: about RM\s?28,102 in today's money/);
});

test("the flat figure gives one line, says depth does not count, and drops the repeated columns", () => {
  const nodes = results(FLAT);
  assert.match(text(nodes), /Any flood that reaches your floor: about RM\s?34,647/);
  assert.match(text(nodes), /Enter what your stock is worth/);
  assert.equal(nodes.find((node) => node.getAttribute("class") === "table-scroll").querySelectorAll("th").length, 3 + 3);   // 3 columns, 3 rows
});

test("the owner's own value keeps the full table and no flat line", () => {
  const nodes = results(OWN);
  assert.ok(!/Any flood that reaches your floor/.test(text(nodes)));
  assert.equal(nodes.find((node) => node.getAttribute("class") === "table-scroll").querySelectorAll("th").length, 5 + 3);
});

test("a flood that stays below the floor costs RM 0 and says so, never that the shop is safe", () => {
  const key = text([results(OWN, { rp: "10" })[0].children[0]]);
  assert.match(key, /^RM\s?0/);
  assert.match(key, /0\.10 m at the street, none above your floor/);
  const street = result({ 10: { ...flood(0, 0, 0, 0), depth_m: null }, 20: flood(0.5, 1, 1, 0.1), 50: flood(1, 2, 2, 0.2) });
  assert.match(text([results(street, { rp: "10" })[0].children[0]]), /In the model, no water reaches the street here in this flood\./);
  assert.ok(!/safe/i.test(key));
});

test("the table marks the flood size on show", () => {
  const table = results(OWN, { rp: "20" }).find((node) => node.getAttribute("class") === "table-scroll");
  const rows = table.querySelectorAll("tr").filter((row) => row.getAttribute("aria-current") === "true");
  assert.equal(rows.length, 1);
  assert.equal(rows[0].getAttribute("class"), "is-chosen");
  assert.match(rows[0].textContent, /^1 in 20 years/);
});

test("the first look says it is one, and which shop size's typical figure it used", () => {
  const shown = results({ ...FLAT, inputs: { shop_size: "medium" } }, { isAssumed: true });
  assert.equal(shown[0].getAttribute("class"), "cost-basis is-first-look");
  assert.equal(shown[0].textContent, "For a medium shop, using the typical figure. This is a first look: change the figures and press Estimate the cost to fit your own shop.");
});

test("an answer the owner pressed for names the shop size, and says nothing for their own value", () => {
  assert.equal(results({ ...FLAT, inputs: { shop_size: "complex" } })[0].textContent,
    "For a large complex, such as a mall or hypermarket, using the typical figure.");
  const own = results({ ...OWN, inputs: { shop_size: "", value_at_risk_rm: 25000 } });
  assert.ok(!own.some((node) => /cost-basis/.test(node.getAttribute("class") ?? "")));
});
