// Run from 11_Platform_Draft:  node --test tests/compare.test.mjs
// Comparing places side by side (compare.js), for someone choosing between shop lots: the place on show is added with
// one button, up to three are kept, and each row opens its place again.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { MAX_COMPARED, addCompared, createCompareCard } from "../app/static/js/compare.js";
import { installFakeDom } from "./fake_dom.mjs";
import { point, shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

test("adding keeps at most three places, newest last, and never the same place twice", () => {
  assert.equal(MAX_COMPARED, 3);
  assert.deepEqual(addCompared([], "a"), ["a"]);
  assert.deepEqual(addCompared(["a", "b"], "a"), ["a", "b"]);
  assert.deepEqual(addCompared(["a", "b", "c"], "d"), ["b", "c", "d"]);
});

function mount() {
  const calls = { added: [], removed: [], opened: [] };
  const card = createCompareCard({ onAdd: (id) => calls.added.push(id), onRemove: (id) => calls.removed.push(id), onOpen: (place) => calls.opened.push(place.id) });
  const button = (words) => card.node.querySelectorAll("button").find((b) => b.textContent === words);
  return { card, calls, button };
}

const other = { ...shop, id: "node-2", name: "Kedai Dua", depth_m: { 10: null, 20: 0.3, 50: 0.8 }, shelter: { name: "SK Satu", distance_m: 450 } };

test("the place on show can be added; once added the button says so and removes it", () => {
  const { card, calls, button } = mount();
  card.render({ current: shop, compared: [] });
  button("Add this place to compare").click();
  assert.deepEqual(calls.added, ["node-1"]);
  card.render({ current: shop, compared: [shop] });
  button("Remove from compare").click();
  assert.deepEqual(calls.removed, ["node-1"]);
});

test("with two places the table shows their depths, road water and relief centre side by side", () => {
  const { card } = mount();
  card.render({ current: shop, compared: [shop, other] });
  const rows = card.node.querySelectorAll("tr").slice(1).map((row) => row.textContent);
  assert.equal(rows.length, 2);
  assert.match(rows[0], /A Shop.*0\.20 m.*0\.50 m.*1\.00 m.*0\.90 m.*none listed/);
  assert.match(rows[1], /Kedai Dua.*no water.*0\.30 m.*0\.80 m.*SK Satu, 450 m/);
});

test("a point is named by its square, and each row opens its place", () => {
  const { card, calls } = mount();
  card.render({ current: shop, compared: [shop, point()] });
  assert.match(card.node.querySelectorAll("tr")[2].textContent, /90 m square at 3\.02998, 101\.53667/);
  card.node.querySelectorAll("tr")[2].querySelector("button").click();
  assert.deepEqual(calls.opened, ["pt:3.02998,101.53667"]);
});

test("with one place added it says which, and what to do next, whether it is on show or not", () => {
  const { card, calls, button } = mount();
  card.render({ current: shop, compared: [shop] });
  assert.match(card.node.textContent, /Added: A Shop\. Open another place and add it to see them side by side\./);
  assert.ok(button("Remove from compare"));
  assert.equal(button("Remove"), undefined, "the main button already removes the place on show");
  card.render({ current: other, compared: [shop] });
  assert.match(card.node.textContent, /Added: A Shop\. Add this place to see them side by side\./);
  assert.ok(button("Add this place to compare"));
  button("Remove").click();
  assert.deepEqual(calls.removed, ["node-1"]);
  card.render({ current: other, compared: [] });
  assert.doesNotMatch(card.node.textContent, /Added:/);
});

test("a point added alone is named by its square", () => {
  const { card } = mount();
  card.render({ current: shop, compared: [point()] });
  assert.match(card.node.textContent, /Added: 90 m square at 3\.02998, 101\.53667\./);
});

test("with three places the add button says the limit", () => {
  const { card, button } = mount();
  const third = { ...other, id: "node-3" };
  card.render({ current: { ...other, id: "node-4" }, compared: [shop, other, third] });
  assert.match(card.node.textContent, /Up to 3 places: adding this one drops the oldest/);
  assert.ok(button("Add this place to compare"));
});
