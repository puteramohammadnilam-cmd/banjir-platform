// node --test tests/river-gauge.test.mjs
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { checklist } from "../app/static/js/floodmode.js";
import { useLang } from "../app/static/js/i18n.js";
import { gaugeFact, gaugeLine } from "../app/static/js/river-gauge.js";
import { dayText, outlookText, tideLine } from "../app/static/js/tide.js";
import { installFakeDom } from "./fake_dom.mjs";
import { shop } from "./point_fixtures.mjs";

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

const GAUGE = { id: "G1", name: "Sg. Test di Kg. Test", river: "Sg. Test", distance_m: 914, link: "https://publicinfobanjir.water.gov.my/wl-graph/?stationid=G1" };
const TIDE = { station: "Gauge Town", date: "2026-10-07", highs: ["03:20", "15:50"], next_big: { from: "2026-10-09", to: "2026-10-13" } };
const text = (node) => (Array.isArray(node) ? node.map(text).join(" ") : node?.textContent ?? "");

test("the gauge fact names the gauge, how far and on which river, and links to JPS's own page", () => {
  const card = gaugeFact({ gauge: GAUGE });
  assert.match(card.textContent, /River gauge/);
  assert.match(card.textContent, /Sg\. Test di Kg\. Test/);
  assert.match(card.textContent, /The nearest JPS river level gauge, 914 m away, on Sg\. Test\./);
  assert.equal(card.querySelector("a").getAttribute("href"), GAUGE.link);
  assert.equal(gaugeFact({ gauge: null }), null);
  assert.match(gaugeFact({ gauge: { ...GAUGE, river: null } }).textContent, /gauge, 914 m away\./);
});

test("the checklist says which river to watch and today's high tides", () => {
  assert.match(gaugeLine({ gauge: GAUGE }).textContent, /Watch the river at Sg\. Test di Kg\. Test \(914 m away\):/);
  assert.match(tideLine(TIDE).textContent, /High tide today at Gauge Town: 03:20 and 15:50\./);
  assert.ok(!tideLine(null) && !tideLine({ ...TIDE, highs: [] }));
  const steps = text(checklist({ premise: { ...shop, gauge: GAUGE }, rp: "50", floorCm: 0, stock: undefined, dry: undefined, tide: TIDE }));
  assert.match(steps, /Watch the river at Sg\. Test/);
  assert.match(steps, /High tide today at Gauge Town/);
});

test("the big tide outlook reads as dates, in both languages", () => {
  assert.equal(dayText("2026-10-09", "en-GB"), "9 Oct");
  assert.equal(outlookText(TIDE), "Next big tides: 9 Oct to 13 Oct.");
  assert.equal(outlookText({ ...TIDE, next_big: { from: "2026-10-07", to: "2026-10-09" } }), "Big tides until 9 Oct.");
  assert.equal(outlookText({ ...TIDE, next_big: { from: "2026-10-09", to: "2026-10-09" } }), "Next big tide: 9 Oct.");
  assert.equal(outlookText({ ...TIDE, next_big: null }), null);
  useLang("ms");
  assert.match(outlookText(TIDE), /^Air pasang besar seterusnya: 9 Okt hingga 13 Okt\.$/);
  assert.match(gaugeLine({ gauge: GAUGE }).textContent, /Pantau sungai di Sg\. Test/);
  assert.ok(!/\b(safe|selamat)\b/i.test(gaugeFact({ gauge: GAUGE }).textContent + outlookText(TIDE)));
});
