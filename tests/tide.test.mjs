// node --test tests/tide.test.mjs
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { createTide, malaysiaToday, timesText } from "../app/static/js/tide.js";
import { installFakeDom } from "./fake_dom.mjs";

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

// The card shows only today's tides, so the answer is dated today.
const TIDE = { station: "Gauge Town", date: malaysiaToday(), highs: ["03:20", "15:50"], lows: ["09:55", "22:05"], range_m: 3.0,
  big: false, next_high: { time: "15:50", tomorrow: false }, typical_error_m: 0.18, source: "Public tide-gauge record" };

test("high tide times read as a list", () => {
  assert.equal(timesText(["03:18", "15:48"]), "03:18 and 15:48");
  assert.equal(timesText(["03:18"]), "03:18");
  assert.equal(timesText(["01:00", "13:00", "23:50"]), "01:00, 13:00 and 23:50");
  assert.equal(timesText([]), "");
});

test("the card stays hidden until the server answers, and for an area with no tide table", () => {
  const section = document.createElement("section");
  const card = createTide(section);
  for (const state of [{ busy: true }, { data: null }]) {
    card.set(state);
    assert.equal(section.hidden, true, JSON.stringify(state));
  }
});

test("when the tide cannot be loaded, the card says so instead of going away", () => {
  const section = document.createElement("section");
  createTide(section).set({ error: true });
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /Tide today/);
  assert.match(section.textContent, /could not be loaded just now/);
});

test("an ordinary day gives the station, today's highs, the next high and why it matters", () => {
  const section = document.createElement("section");
  createTide(section).set({ data: TIDE });
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /Tide at Gauge Town/);
  assert.match(section.textContent, /High tide today: 03:20 and 15:50\./);
  assert.match(section.textContent, /Next high tide: 15:50 today\./);
  assert.match(section.textContent, /An ordinary tide today: about 3 m between low and high\./);
  assert.match(section.textContent, /can drain away more slowly, which can make flooding worse where the river is tidal/);
  assert.match(section.textContent, /Predicted for the Gauge Town gauge/);
  assert.match(section.textContent, /typically off by about 0.18 m, sometimes more/);
});

test("a big tide is said to be one, and tomorrow's next high is labelled tomorrow, in both languages", () => {
  const section = document.createElement("section");
  const card = createTide(section);
  const big = { ...TIDE, big: true, range_m: 4.6, next_high: { time: "04:12", tomorrow: true } };
  card.set({ data: big });
  assert.match(section.textContent, /A big tide today \(spring tide\): about 4.6 m/);
  assert.match(section.textContent, /Next high tide: 04:12 tomorrow\./);
  assert.ok(section.querySelector(".tide-big"));
  useLang("ms");
  card.set({ data: { ...big } });
  assert.match(section.textContent, /Pasang surut di Gauge Town/);
  assert.match(section.textContent, /Air pasang hari ini: 03:20 dan 15:50\./);
  assert.match(section.textContent, /pasang perbani/);
  assert.match(section.textContent, /04:12 esok/);
  assert.ok(!/\b(safe|selamat)\b/i.test(section.textContent));
});
