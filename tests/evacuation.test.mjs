// node --test tests/evacuation.test.mjs
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { centreLine, checkedTime, createEvacuation } from "../app/static/js/evacuation.js";
import { useLang } from "../app/static/js/i18n.js";
import { installFakeDom } from "./fake_dom.mjs";

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

const CENTRE = { name: "SK TAMAN MELATI", district: "Petaling", disaster: "Banjir", evacuees: 1200, families: 300, full_pct: 35 };
const FOUND = { checked: "2026-10-06T13:15+00:00", count: 1, evacuees: 1200, open_nationwide: 4, margin_km: 5, centres: [CENTRE], source: "https://infobencanajkmv2.jkm.gov.my/landing/" };

test("the check time is Malaysian clock time", () => {
  assert.equal(checkedTime("2026-10-06T13:15+00:00", "en-GB"), "21:15");
  assert.equal(checkedTime("not a time"), "");
});

test("a centre's line has its counts, how full it is, and its district as JKM names it", () => {
  assert.equal(centreLine(CENTRE), "People: 1,200 · Families: 300 · 35% full · Petaling");
  assert.equal(centreLine({ ...CENTRE, full_pct: null, district: "" }), "People: 1,200 · Families: 300");
  assert.equal(centreLine({ ...CENTRE, evacuees: 1, families: 1 }), "People: 1 · Families: 1 · 35% full · Petaling", "no '1 families'");
});

test("the card stays hidden until the server answers, and while the feed fails", () => {
  const section = document.createElement("section");
  const card = createEvacuation(section);
  for (const state of [{ busy: true }, { error: true }, { data: null }]) {
    card.set(state);
    assert.equal(section.hidden, true, JSON.stringify(state));
  }
});

test("open centres near here are listed with the summary, the nationwide count and JKM's link", () => {
  const section = document.createElement("section");
  createEvacuation(section).set({ data: FOUND });
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /Flood evacuation centres open now/);
  assert.match(section.textContent, /Open near here: 1 · People in them: 1,200/);
  assert.equal(section.querySelectorAll("li").length, 1);
  assert.match(section.textContent, /Open for floods across Malaysia: 4\./);
  assert.match(section.textContent, /checked at 21:15\. Centres within about 5 km/);
  assert.equal(section.querySelector("a").getAttribute("href"), FOUND.source);
});

test("with none open near here it says so plainly, in both languages, and never calls a place safe", () => {
  const section = document.createElement("section");
  const card = createEvacuation(section);
  card.set({ data: { ...FOUND, count: 0, evacuees: 0, centres: [] } });
  assert.match(section.textContent, /JKM lists none open near here right now\./);
  assert.equal(section.querySelectorAll("li").length, 0);
  useLang("ms");
  card.set({ data: { ...FOUND, count: 0, evacuees: 0, centres: [] } });
  assert.match(section.textContent, /JKM tidak menyenaraikan pusat dibuka berhampiran sekarang\./);
  assert.ok(!/\b(safe|selamat)\b/i.test(section.textContent));
});
