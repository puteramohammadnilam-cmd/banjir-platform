// Run from 11_Platform_Draft:  node --test tests/front_door.test.mjs
// js/front-door.js sends a bare address to the new map (map.html) unless this browser chose the old interface; a link
// that names a view, a tab or a place still opens the old page. ui-choice.js remembers the choice under the same key.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";
import vm from "node:vm";

import { useLang } from "../app/static/js/i18n.js";
import { summaryCard } from "../app/static/js/map-gl-card.js";
import { UI_KEY, rememberUi } from "../app/static/js/ui-choice.js";
import { installFakeDom } from "./fake_dom.mjs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const SOURCE = read("../app/static/js/front-door.js");
const PAGE = read("../app/static/index.html");
const MAP = read("../app/static/map.html");

/** Where the script sends an address to: "./map.html", or null when the page stays. */
function goesTo(search, hash, stored = null, { blocked = false } = {}) {
  let to = null;
  const localStorage = { getItem: (key) => { if (blocked) throw new Error("blocked"); return key === UI_KEY ? stored : null; } };
  vm.runInNewContext(SOURCE, { location: { search, hash, replace: (url) => { to = url; } }, localStorage });
  return to;
}

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

test("a bare address opens the new map, unless this browser chose the old interface", () => {
  assert.equal(goesTo("", ""), "./map.html");
  assert.equal(goesTo("", "", "new"), "./map.html");
  assert.equal(goesTo("", "", "old"), null);
  assert.equal(goesTo("", "", null, { blocked: true }), "./map.html");
});

test("a link that names a view, a tab or a point still opens the old page", () => {
  for (const [search, hash] of [["?tab=business", ""], ["?section=sec-1&rp=20", ""], ["", "#place=pt:3.00042,101.50042"]]) {
    assert.equal(goesTo(search, hash), null, search + hash);
  }
});

test("the switch remembers under the key the front door reads, and the script runs first in the head", () => {
  assert.ok(SOURCE.includes(`"${UI_KEY}"`));
  const stored = {};
  globalThis.localStorage = { setItem: (key, value) => { stored[key] = value; } };
  rememberUi("old");
  assert.deepEqual(stored, { [UI_KEY]: "old" });
  delete globalThis.localStorage;
  assert.match(PAGE, /<meta name="viewport"[^>]*>\s*<script src="js\/front-door\.js"><\/script>/);
  assert.ok(PAGE.indexOf("front-door.js") < PAGE.indexOf("<link rel=\"stylesheet\""));
});

test("the new map is the front door: no noindex, and its way to the old interface", () => {
  assert.doesNotMatch(MAP, /noindex/);
  assert.match(MAP, /id="mg-old" href="\.\/\?rp=50"/);   // a query, so the front door never sends it back
  const nodes = summaryCard({ wet: 1, all: 2, rp: "50", onPick() {}, onOld() {} });
  const old = nodes.find((node) => node.getAttribute?.("class")?.includes("mg-old-link"));
  assert.equal(old.textContent, "Old interface");
  assert.equal(summaryCard({ wet: 1, all: 2, rp: "50", onPick() {} }).some((node) => node.getAttribute?.("class")?.includes("mg-old-link")), false);
});
