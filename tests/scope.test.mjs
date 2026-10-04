// Run from 11_Platform_Draft:  node --test tests/scope.test.mjs
// The scope bar on the Area overview (scope.js), on the small fake DOM in tests/fake_dom.mjs. Another area is another
// page, so choosing one in the select must not load it: a keyboard user going through the options would be taken away
// at the first arrow key (WCAG 3.2.2, on input). The "Open" button loads it, and a visible hint says so.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createScopeBar } from "../app/static/js/scope.js";
import { installFakeDom } from "./fake_dom.mjs";

const AREAS = [{ id: "sri-muda", display_name: "Taman Sri Muda" }, { id: "kota-tinggi", display_name: "Kota Tinggi" }];
let pageShow = null;

beforeEach(() => {
  installFakeDom();
  globalThis.window = { addEventListener: (type, listener) => { if (type === "pageshow") pageShow = listener; } };
});

function mount({ onCheckPoint = null } = {}) {
  const slot = document.createElement("div");
  const opened = [];
  createScopeBar(slot, { areas: AREAS, areaId: "sri-muda", onArea: (id) => opened.push(id), onCheckPoint });
  const select = slot.querySelector("select");
  const open = slot.querySelectorAll("button").find((button) => button.textContent === "Open");
  return { slot, select, open, opened };
}

const choose = (select, value) => {
  select.value = value;
  select.dispatch("change");
};

test("choosing another area in the select does not load it", () => {
  const { select, opened } = mount();
  choose(select, "kota-tinggi");
  assert.deepEqual(opened, []);
});

test("Open loads the area chosen, and is off while the chosen area is the one on show", () => {
  const { select, open, opened } = mount();
  assert.equal(open.disabled, true);
  choose(select, "kota-tinggi");
  assert.equal(open.disabled, false);
  open.click();
  assert.deepEqual(opened, ["kota-tinggi"]);
  choose(select, "sri-muda");
  assert.equal(open.disabled, true);
});

test("the hint is on show and describes both the select and Open", () => {
  const { slot, select, open } = mount();
  const hint = slot.querySelector('[id="area-hint"]');
  assert.ok(hint.textContent.includes("Open"));
  assert.ok(!(hint.getAttribute("class") ?? "").includes("visually-hidden"));
  assert.equal(select.getAttribute("aria-describedby"), "area-hint");
  assert.equal(open.getAttribute("aria-describedby"), "area-hint");
});

test("coming back from the back-forward cache shows the page's own area again, with Open off", () => {
  const { select, open } = mount();
  choose(select, "kota-tinggi");
  pageShow({ persisted: true });
  assert.equal(select.value, "sri-muda");
  assert.equal(open.disabled, true);
});

test("the bar holds the area choice alone: the way in to any point is the search's neighbour, not here", () => {
  const { slot } = mount({ onCheckPoint: () => assert.fail("the scope bar has no check-point button") });
  assert.deepEqual(slot.querySelectorAll("button").map((button) => button.textContent), ["Open"]);
});

// ---------- a city split into sections ----------

const SECTIONS = [{ id: "seksyen-24", name: "Seksyen 24" }, { id: "seksyen-25", name: "Seksyen 25" }];
const WORD = { en: "Section", ms: "Seksyen" };

function mountCity({ sectionId = null, wholeCity = true } = {}) {
  const slot = document.createElement("div");
  const sections = [];
  createScopeBar(slot, {
    areas: AREAS, areaId: "sri-muda", onArea() {}, sections: SECTIONS, sectionId, word: WORD, wholeCity,
    onSection: (id) => sections.push(id), cityHref: "?", cityName: "The City",
  });
  const select = slot.querySelector('[id="section-select"]');
  const open = slot.querySelectorAll("button").filter((button) => button.textContent === "Open")[1];
  return { slot, select, open, sections };
}

test("a city adds a section select, in the area's own word, with the whole city first", () => {
  const { slot, select } = mountCity();
  assert.equal(slot.querySelector('[for="section-select"]').textContent, "Section");
  assert.deepEqual(select.children.map((option) => [option.getAttribute("value"), option.textContent]),
    [["", "Whole city"], ["seksyen-24", "Seksyen 24"], ["seksyen-25", "Seksyen 25"]]);
  assert.equal(select.value, "", "the whole city is on show");
  assert.equal(slot.querySelector('[id="area-hint"]').textContent, "Pick an area or a section, then Open.");
  assert.equal(select.getAttribute("aria-describedby"), "area-hint");
});

test("choosing a section only chooses it; Open opens it, and the whole city with null", () => {
  const { select, open, sections } = mountCity({ sectionId: "seksyen-25" });
  assert.equal(open.disabled, true, "the section on show");
  choose(select, "seksyen-24");
  assert.deepEqual(sections, []);
  assert.equal(open.disabled, false);
  open.click();
  choose(select, "");
  open.click();
  assert.deepEqual(sections, ["seksyen-24", null]);
});

test("a section's page has a plain link back to the whole city; the whole city's page has none", () => {
  const onSection = mountCity({ sectionId: "seksyen-25" });
  const back = onSection.slot.querySelector("a");
  assert.equal(back.getAttribute("href"), "?");
  assert.equal(back.textContent, "All of The City");
  assert.equal(mountCity().slot.querySelector("a"), null);
});

test("a city with a default section has no whole-city view to offer", () => {
  const { select } = mountCity({ sectionId: "seksyen-25", wholeCity: false });
  assert.deepEqual(select.children.map((option) => option.getAttribute("value")), ["seksyen-24", "seksyen-25"]);
});

test("back from the cache, the section select shows the page's own section again", () => {
  const { select, open } = mountCity({ sectionId: "seksyen-25" });
  choose(select, "seksyen-24");
  pageShow({ persisted: true });
  assert.equal(select.value, "seksyen-25");
  assert.equal(open.disabled, true);
});

test("a plain area's bar is as it was: one select, one Open, the plain hint", () => {
  const { slot } = mount();
  assert.equal(slot.querySelectorAll("select").length, 1);
  assert.equal(slot.querySelector('[id="area-hint"]').textContent, "Pick an area, then Open.");
  assert.equal(slot.querySelector("a"), null);
});
