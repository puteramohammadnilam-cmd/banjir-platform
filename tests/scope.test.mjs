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

test("the way in to any point is there only when points can be checked", () => {
  const without = mount();
  assert.equal(without.slot.querySelectorAll("button").length, 1);
  const openers = [];
  const withPoints = mount({ onCheckPoint: (button) => openers.push(button) });
  const check = withPoints.slot.querySelectorAll("button").find((button) => button.textContent.includes("Check any point"));
  check.dispatch("click", { currentTarget: check });
  assert.deepEqual(openers, [check]);
});
