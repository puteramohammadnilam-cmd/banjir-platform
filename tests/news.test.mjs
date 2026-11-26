// node --test tests/news.test.mjs
// What is new (news.js): the "NEW" label and the "What's new" note while the news is fresh, closed for good by "Got it".
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { NEW_UNTIL, createNews, isFresh, newBadge } from "../app/static/js/news.js";
import { installFakeDom } from "./fake_dom.mjs";

const DURING = new Date("2026-11-27T02:00:00Z");
const AFTER = new Date(`${NEW_UNTIL}T17:00:00Z`);   // 1 am the day after, in Malaysia

function store() {
  const kept = new Map();
  return { getItem: (k) => kept.get(k) ?? null, setItem: (k, v) => kept.set(k, v) };
}

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

test("the NEW label shows until the news is old, in the page's language", () => {
  assert.equal(isFresh(DURING), true);
  assert.equal(newBadge(DURING).textContent, "NEW");
  assert.equal(isFresh(AFTER), false);
  assert.equal(newBadge(AFTER), null);
  useLang("ms");
  assert.equal(newBadge(DURING).textContent, "BARU");
});

test("the note lists each new part with a way to it, and Got it closes it for good", () => {
  const storage = store();
  const calls = [];
  const section = document.createElement("aside");
  createNews(section, { onShowOutlook: () => calls.push("outlook"), onOpenEngineer: () => calls.push("engineer"), storage, now: DURING });
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /NEW.*What's new.*Next 5 days:.*Engineer mode:/);
  const buttons = [...section.querySelectorAll("button")];
  buttons.find((b) => b.textContent === "Show me").click();
  buttons.find((b) => b.textContent === "Open").click();
  assert.deepEqual(calls, ["outlook", "engineer"]);
  buttons.find((b) => b.textContent === "Got it").click();
  assert.equal(section.hidden, true);
  const again = document.createElement("aside");
  createNews(again, { storage, now: DURING });
  assert.equal(again.hidden, true, "remembered in this browser");
});

test("the note stays away once the news is old", () => {
  const section = document.createElement("aside");
  createNews(section, { storage: store(), now: AFTER });
  assert.equal(section.hidden, true);
});
