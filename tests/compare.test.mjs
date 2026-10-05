// Run from 11_Platform_Draft:  node --test tests/compare.test.mjs
// Comparing places side by side (compare.js), for someone choosing between shop lots: the place on show is added with
// one button, up to three are kept, and each row opens its place again.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { MAX_COMPARED, addCompared, createCompareCard, verdict } from "../app/static/js/compare.js";
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
  const calls = { added: [], removed: [], opened: [], found: 0 };
  const card = createCompareCard({ onAdd: (id) => calls.added.push(id), onRemove: (id) => calls.removed.push(id), onOpen: (place) => calls.opened.push(place.id),
    onFind: () => { calls.found += 1; } });
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

test("with two places the table puts them across the top, and the depths, road water and relief centre down the side", () => {
  const { card } = mount();
  card.render({ current: shop, compared: [shop, other] });
  const rows = card.node.querySelectorAll("tr").map((row) => row.textContent);
  assert.match(rows[0], /A Shop.*Kedai Dua/);
  assert.match(rows[1], /1 in 10 years flood.*0\.20 m.*no water/);
  assert.match(rows[3], /1 in 50 years flood.*1\.00 m.*0\.80 m/);
  assert.match(rows[4], /Nearest road, 1 in 50.*0\.90 m/);
  assert.match(rows[5], /Relief centre.*none listed.*SK Satu, 450 m/);
});

test("a point is named by its square, and each name opens its place", () => {
  const { card, calls } = mount();
  card.render({ current: shop, compared: [shop, point()] });
  const heads = card.node.querySelector("thead").querySelectorAll("th");
  assert.match(heads[2].textContent, /90 m square at 3\.02998, 101\.53667/);   // after the hidden "Place" and A Shop
  heads[2].querySelector("button").click();
  assert.deepEqual(calls.opened, ["pt:3.02998,101.53667"]);
});

test("the steps say what to do next, and Find another place goes to the search", () => {
  const { card, calls, button } = mount();
  card.render({ current: shop, compared: [] });
  assert.match(card.node.textContent, /Step 1 of 2: add this place\./);
  assert.equal(button("Find another place"), undefined, "nothing added yet: add this one first");
  card.render({ current: shop, compared: [shop] });
  assert.match(card.node.textContent, /Step 2 of 2: A Shop is added\. Now find a second place, open it, and add it in this box at the bottom of My business\./);
  button("Find another place").click();
  assert.equal(calls.found, 1);
  assert.equal(button("Remove A Shop"), undefined, "the main button already removes the place on show");
  card.render({ current: other, compared: [shop] });
  assert.match(card.node.textContent, /Step 2 of 2: A Shop is added\. Add this place to see the two side by side\./);
  assert.ok(button("Add this place to compare"));
  button("Remove A Shop").click();
  assert.deepEqual(calls.removed, ["node-1"]);
});

test("a point added alone is named by its square", () => {
  const { card } = mount();
  card.render({ current: shop, compared: [point()] });
  assert.match(card.node.textContent, /90 m square at 3\.02998, 101\.53667 is added/);
});

test("two or more places get one line on where the least and the most water are, and the least is marked per row", () => {
  const { card } = mount();
  card.render({ current: shop, compared: [shop, other] });
  assert.match(card.node.querySelector(".compare-verdict").textContent,
    /In a 1 in 50 years flood, the model puts the least water at Kedai Dua \(0\.80 m\) and the most at A Shop \(1\.00 m\)\./);
  const rows = card.node.querySelectorAll("tr");
  assert.match(rows[0].textContent, /A ShopOn show/);
  assert.match(rows[1].textContent, /0\.20 mno waterLeast water/);
  assert.match(rows[3].textContent, /1\.00 m0\.80 mLeast water/);
  assert.equal(card.node.querySelector("thead").querySelectorAll("th")[1].getAttribute("class"), "is-current");
});

test("the verdict says when the places are dry, or the same", () => {
  const dry = { ...other, depth_m: { 10: null, 20: 0, 50: null } };
  assert.equal(verdict([dry, { ...dry, id: "x" }]), "In a 1 in 50 years flood, the model puts no water at any of these places.");
  assert.equal(verdict([other, { ...other, id: "x", name: "Kedai Tiga" }]),
    "In a 1 in 50 years flood, the model puts the same water at all of these places: 0.80 m.");
  assert.match(verdict([other, { ...other, id: "x", name: "Kedai Tiga" }, shop]), /least water at Kedai Dua, Kedai Tiga \(0\.80 m\)/);
});

test("each row has its own remove button, named for screen readers", () => {
  const { card, calls } = mount();
  card.render({ current: shop, compared: [shop, other] });
  const remove = card.node.querySelectorAll(".compare-remove");
  assert.equal(remove[1].getAttribute("aria-label"), "Remove Kedai Dua");
  remove[1].click();
  assert.deepEqual(calls.removed, ["node-2"]);
});

test("with three places the add button says the limit", () => {
  const { card, button } = mount();
  const third = { ...other, id: "node-3" };
  card.render({ current: { ...other, id: "node-4" }, compared: [shop, other, third] });
  assert.match(card.node.textContent, /Up to 3 places: adding this one drops the oldest/);
  assert.ok(button("Add this place to compare"));
});
