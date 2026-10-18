// Run from 11_Platform_Draft:  node --test tests/early_tab.test.mjs
// js/early-tab.js runs before the page is drawn and sets the tab a link asks for, so the header is laid out for it from
// the first paint. It is a plain script (a module would run too late), so it keeps its own copy of the tab list.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

import { TABS } from "../app/static/js/place.js";

const SOURCE = readFileSync(new URL("../app/static/js/early-tab.js", import.meta.url), "utf8");
const PAGE = readFileSync(new URL("../app/static/index.html", import.meta.url), "utf8");

/** Runs the script for a page address and gives back the body's data-tab. */
function tabFor(search) {
  const body = { dataset: { tab: "overview" } };
  vm.runInNewContext(SOURCE, { location: { search }, document: { body }, URLSearchParams });
  return body.dataset.tab;
}

test("a link's tab is set before the page is drawn, and anything else leaves the overview", () => {
  for (const tab of TABS) assert.equal(tabFor(`?tab=${tab}&place=x`), tab);
  for (const search of ["", "?tab=ask", "?tab=nonsense", "?tab="]) assert.equal(tabFor(search), "overview", search);
});

test("the script's tab list is place.js's, and the page loads it first thing in the body", () => {
  const list = JSON.parse(/\[[^\]]*\]/.exec(SOURCE)[0]);
  assert.deepEqual(list, TABS);
  assert.match(PAGE, /<body data-tab="overview">\s*<script src="js\/early-tab\.js"><\/script>/);
});
