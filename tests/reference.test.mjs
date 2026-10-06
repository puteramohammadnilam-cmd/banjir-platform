// Run from 11_Platform_Draft:  node --test tests/reference.test.mjs
// The Reference tab's "On this page" list (reference.js): a button jumps to its heading and gives it focus, with no
// #fragment; a section the area has no data for hides its button.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { syncReferenceNav, wireReferenceNav } from "../app/static/js/reference.js";
import { installFakeDom } from "./fake_dom.mjs";

beforeEach(() => installFakeDom());

test("a section that is hidden hides its link, and one on show shows it", () => {
  const items = [{ item: { hidden: false }, target: "a" }, { item: { hidden: false }, target: "b" }, { item: { hidden: true }, target: "c" }];
  const sections = { a: { hidden: false }, b: { hidden: true }, c: { hidden: false } };
  syncReferenceNav(items, (id) => sections[id]);
  assert.deepEqual(items.map(({ item }) => item.hidden), [false, true, false]);
});

test("a link scrolls its heading into view and gives it focus", () => {
  const calls = [];
  const heading = { scrollIntoView: (options) => calls.push(["scroll", options.block]), focus: (options) => calls.push(["focus", options.preventScroll]) };
  globalThis.document.getElementById = (id) => (id === "ref-sources" ? heading : null);
  let onClick;
  wireReferenceNav({ addEventListener: (type, handler) => { onClick = handler; } });
  onClick({ target: { closest: () => ({ getAttribute: () => "ref-sources" }) } });
  assert.deepEqual(calls, [["scroll", "start"], ["focus", true]]);
  onClick({ target: { closest: () => null } });   // a click between the links does nothing
  assert.equal(calls.length, 2);
});
