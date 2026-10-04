// Run from 11_Platform_Draft:  node --test tests/section_table.test.mjs
// The table of a city's sections (section-table.js): the choropleth's figures for the keyboard and screen readers. A
// real <table>, sorted by header buttons that set aria-sort and say the new order out loud, each name a real link to
// its section, the figures following the flood size on show. On the small fake DOM of tests/fake_dom.mjs.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { createSectionTable, sectionRows, sortRows } from "../app/static/js/section-table.js";
import { installFakeDom } from "./fake_dom.mjs";
import { SECTIONS, SECTION_WORD } from "./fixtures/city_data.mjs";

beforeEach(() => installFakeDom());

function mount(rp = "50") {
  const slot = document.createElement("div");
  const lifted = [];
  const table = createSectionTable(slot, {
    sections: SECTIONS, word: SECTION_WORD, hrefOf: (id) => `?section=${id}`, onHighlight: (id) => lifted.push(id),
  });
  table.show(rp);
  return { slot, table, lifted };
}

const names = (slot) => slot.querySelectorAll("tbody")[0].children.map((tr) => tr.querySelector("a").textContent);
const headers = (slot) => slot.querySelectorAll("th").filter((th) => th.getAttribute("scope") === "col");
const sortButton = (slot, i) => headers(slot)[i].querySelector("button");
const live = (slot) => slot.querySelector('[aria-live="polite"]');

// ---------- the rows ----------

test("a row per section: its share of squares with water and its businesses with water at the flood size", () => {
  const rows = sectionRows(SECTIONS, "50");
  assert.deepEqual(rows.map(({ id, share, wet, total }) => [id, share, wet, total]),
    [["seksyen-24", 66 / 600, 1, 1], ["seksyen-25", 870 / 1500, 2, 3], ["seksyen-u1", 0, 0, 1]]);
  assert.deepEqual(rows.map(({ order }) => order), [0, 1, 2], "the data's own order, 1-36 then U1-U20");
});

test("sorting makes a new list: by name it is the data's order, by a figure the biggest first, ties in the data's order", () => {
  const rows = sectionRows(SECTIONS, "50");
  const before = rows.map(({ id }) => id);
  assert.deepEqual(sortRows(rows, "share", "descending").map(({ id }) => id), ["seksyen-25", "seksyen-24", "seksyen-u1"]);
  assert.deepEqual(sortRows(rows, "share", "ascending").map(({ id }) => id), ["seksyen-u1", "seksyen-24", "seksyen-25"]);
  assert.deepEqual(sortRows(rows, "name", "descending").map(({ id }) => id), ["seksyen-u1", "seksyen-25", "seksyen-24"]);
  assert.deepEqual(sortRows(sectionRows(SECTIONS, "10"), "wet", "descending").map(({ id }) => id), ["seksyen-25", "seksyen-24", "seksyen-u1"],
    "24 and U1 tie on 0 and keep their order");
  assert.deepEqual(rows.map(({ id }) => id), before, "the list handed in is not changed");
});

// ---------- the table ----------

test("a real table: a caption, column headers, a row header per section that is a link to it", () => {
  const { slot } = mount();
  const table = slot.querySelector("table");
  assert.ok(table);
  assert.match(table.querySelector("caption").textContent, /section/);
  assert.deepEqual(headers(slot).map((th) => th.textContent.trim()), ["Section", "Squares with water", "Businesses with water"]);
  const links = slot.querySelectorAll("a");
  assert.deepEqual(links.map((a) => a.getAttribute("href")), ["?section=seksyen-25", "?section=seksyen-24", "?section=seksyen-u1"]);
  assert.ok(slot.querySelectorAll("tbody")[0].children.every((tr) => tr.children[0].tagName === "th" && tr.children[0].getAttribute("scope") === "row"));
});

test("it opens sorted by share of squares, biggest first, and says so on that header alone", () => {
  const { slot } = mount();
  assert.deepEqual(names(slot), ["Seksyen 25", "Seksyen 24", "Seksyen U1"]);
  assert.deepEqual(headers(slot).map((th) => th.getAttribute("aria-sort")), [null, "descending", null]);
  const cells = slot.querySelectorAll("tbody")[0].children[0].children.map((cell) => cell.textContent);
  assert.deepEqual(cells, ["Seksyen 25", "58%", "2 of 3"]);
});

test("a header button sorts by its column, a second press turns the order round, and the new order is said", () => {
  const { slot } = mount();
  sortButton(slot, 0).click();
  assert.deepEqual(names(slot), ["Seksyen 24", "Seksyen 25", "Seksyen U1"]);
  assert.deepEqual(headers(slot).map((th) => th.getAttribute("aria-sort")), ["ascending", null, null]);
  assert.equal(live(slot).textContent, "Sorted by Section, ascending.");
  sortButton(slot, 0).click();
  assert.deepEqual(names(slot), ["Seksyen U1", "Seksyen 25", "Seksyen 24"]);
  assert.equal(live(slot).textContent, "Sorted by Section, descending.");
  sortButton(slot, 2).click();
  assert.deepEqual(headers(slot).map((th) => th.getAttribute("aria-sort")), [null, null, "descending"]);
  assert.equal(names(slot)[0], "Seksyen 25");
});

test("the header buttons stay put when the rows are redrawn, so focus does not fall to the page", () => {
  const { slot, table } = mount();
  const button = sortButton(slot, 1);
  button.click();
  table.show("10");
  assert.equal(sortButton(slot, 1), button);
});

test("a new flood size redraws the figures and keeps the order the reader chose", () => {
  const { slot, table } = mount();
  sortButton(slot, 0).click();
  table.show("10");
  assert.deepEqual(names(slot), ["Seksyen 24", "Seksyen 25", "Seksyen U1"]);
  assert.equal(slot.querySelectorAll("tbody")[0].children[1].children[1].textContent, "20%");
  assert.equal(live(slot).textContent, "Sorted by Section, ascending.", "the size change itself is not announced as a sort");
});

test("a row's bar shows its share, and a row lifts its section on the map while hovered or focused", () => {
  const { slot, lifted } = mount();
  const row = slot.querySelectorAll("tbody")[0].children[0];
  assert.equal(row.querySelector(".share-bar").getAttribute("style"), "--share: 0.58");
  assert.equal(row.querySelector(".share-bar").getAttribute("aria-hidden"), "true");
  row.dispatch("mouseenter");
  row.dispatch("mouseleave");
  row.dispatch("focusin");
  assert.deepEqual(lifted, ["seksyen-25", null, "seksyen-25"]);
});

test("a section with no businesses mapped says so, not 0 of 0", () => {
  const slot = document.createElement("div");
  const empty = [{ ...SECTIONS[2], counts: { ...SECTIONS[2].counts, businesses: 0 } }];
  createSectionTable(slot, { sections: empty, word: SECTION_WORD, hrefOf: (id) => `?section=${id}` }).show("50");
  assert.equal(slot.querySelectorAll("tbody")[0].children[0].children[2].textContent, "none mapped");
});

test("in Bahasa Melayu the headers use the area's own word and the order reads naturally", () => {
  useLang("ms");
  try {
    const { slot } = mount();
    assert.deepEqual(headers(slot).map((th) => th.textContent.trim()), ["Seksyen", "Petak dinaiki air", "Perniagaan dimasuki air"]);
    sortButton(slot, 1).click();
    assert.equal(live(slot).textContent, "Disusun mengikut Petak dinaiki air, menaik.");
  } finally {
    useLang("en");
  }
});
