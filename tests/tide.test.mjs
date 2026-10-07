// node --test tests/tide.test.mjs
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { createTide, timesText } from "../app/static/js/tide.js";
import { installFakeDom } from "./fake_dom.mjs";

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

const TIDE = { station: "Gauge Town", date: "2026-10-07", highs: ["03:18", "15:48"], lows: ["09:54", "22:06"], range_m: 3.0,
  big: false, next_high: { time: "15:48", tomorrow: false }, typical_error_m: 0.18, source: "Public tide-gauge record" };

test("high tide times read as a list", () => {
  assert.equal(timesText(["03:18", "15:48"]), "03:18 and 15:48");
  assert.equal(timesText(["03:18"]), "03:18");
  assert.equal(timesText(["01:00", "13:00", "23:50"]), "01:00, 13:00 and 23:50");
  assert.equal(timesText([]), "");
});

test("the card stays hidden until the server answers, and for an area with no tide table", () => {
  const section = document.createElement("section");
  const card = createTide(section);
  for (const state of [{ busy: true }, { error: true }, { data: null }]) {
    card.set(state);
    assert.equal(section.hidden, true, JSON.stringify(state));
  }
});

test("an ordinary day gives the station, today's highs, the next high and why it matters", () => {
  const section = document.createElement("section");
  createTide(section).set({ data: TIDE });
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /Tide at Gauge Town/);
  assert.match(section.textContent, /High tide today: 03:18 and 15:48\./);
  assert.match(section.textContent, /Next high tide: 15:48 today\./);
  assert.match(section.textContent, /An ordinary tide today: about 3 m between low and high\./);
  assert.match(section.textContent, /drains away more slowly/);
  assert.match(section.textContent, /within about 0.18 m/);
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
  assert.match(section.textContent, /Air pasang hari ini: 03:18 dan 15:48\./);
  assert.match(section.textContent, /pasang perbani/);
  assert.match(section.textContent, /04:12 esok/);
  assert.ok(!/\b(safe|selamat)\b/i.test(section.textContent));
});
