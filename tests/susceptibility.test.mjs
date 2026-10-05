// Run from 11_Platform_Draft:  node --test tests/susceptibility.test.mjs
// Flash flood potential and our score (susceptibility.js): the class words and ramps, a section's figures, the My
// business fact (a susceptibility, never a depth), the map's checkbox and "Colour by" radios, and "How these are worked
// out". Every part steps aside when the server sends no index fields (the other areas, an older server).
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createBusiness } from "../app/static/js/card.js";
import { useLang } from "../app/static/js/i18n.js";
import {
  FLASH_CLASSES, FLASH_RAMP, SCORE_RAMP, flashFact, flashWord, highShare, mapControls, methodBody, scoreClass, scoreOf,
  showsScore, swatchStyle, textOf,
} from "../app/static/js/susceptibility.js";
import { INDEXED_AREA, INDEXED_SECTIONS, INDEX_METHOD, SECTIONS, SECTION_WORD } from "./fixtures/city_data.mjs";
import { installFakeDom } from "./fake_dom.mjs";
import { AREAS, HOME, point, shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

/** Run `body` in Bahasa Melayu, and put English back after, whatever happens. */
function inMalay(body) {
  useLang("ms");
  try {
    return body();
  } finally {
    useLang("en");
  }
}

// ---------- words, figures and ramps ----------

test("four classes, low to extreme, each with its word and a step of the warm ramp", () => {
  assert.deepEqual(FLASH_CLASSES, ["low", "medium", "high", "extreme"]);
  assert.deepEqual(FLASH_CLASSES.map(flashWord), ["Low", "Medium", "High", "Extreme"]);
  assert.deepEqual(FLASH_RAMP.map(({ key }) => key), FLASH_CLASSES);
  assert.equal(flashWord("unknown"), null, "a class the page does not know has no word");
  assert.equal(SCORE_RAMP.length, 5);
  inMalay(() => assert.deepEqual(FLASH_CLASSES.map(flashWord), ["Rendah", "Sederhana", "Tinggi", "Ekstrem"]));
});

test("a section's high-or-extreme share and score; null when the server sent none", () => {
  assert.equal(highShare(INDEXED_SECTIONS[0]), 0.2);
  assert.equal(highShare(INDEXED_SECTIONS[2]), 0.7);
  assert.equal(highShare(SECTIONS[0]), null, "no indexes: not worked out, not 0");
  assert.equal(highShare({ indexes: { flash: null, score: null } }), null);
  assert.equal(scoreOf(INDEXED_SECTIONS[1]), 4.6);
  assert.equal(scoreOf(INDEXED_SECTIONS[2]), null, "a score of null stays null");
  assert.equal(scoreOf(SECTIONS[0]), null);
});

test("a score's class comes from its breaks at 1.5, 2.5, 3.5 and 4.5, edges going up; none is 0", () => {
  const cases = [[null, 0], [1, 1], [1.49, 1], [1.5, 2], [2.5, 3], [3.49, 3], [3.5, 4], [4.5, 5], [5, 5]];
  for (const [value, expected] of cases) assert.equal(scoreClass(value), expected, String(value));
});

test("the score shows only when the data says so: no method, or show_score not true, hides it", () => {
  assert.equal(showsScore(INDEX_METHOD), true);
  assert.equal(showsScore(undefined), false);
  assert.equal(showsScore(null), false);
  assert.equal(showsScore({ ...INDEX_METHOD, show_score: false }), false);
  assert.equal(showsScore({ deviations: [] }), false, "a method that does not say keeps the score hidden until the user decides");
});

test("a note from the data is a plain string or {en, ms}; a swatch is its colour at its opacity", () => {
  assert.equal(textOf("Plain."), "Plain.");
  assert.equal(textOf({ en: "Section 24", ms: "Seksyen 24" }), "Section 24");
  inMalay(() => assert.equal(textOf({ en: "Section 24", ms: "Seksyen 24" }), "Seksyen 24"));
  assert.equal(textOf(null), "");
  assert.equal(swatchStyle({ color: "#d05a1b", opacity: 0.6 }), "--sw: rgb(208 90 27 / 0.6)");
});

// ---------- the My business fact ----------

/** A fact's parts as fact.js lays them out: label, chip, value, and the lines folded under "How to read this". */
const factParts = (node) => ({
  label: node.querySelector(".fact-label").textContent,
  chip: node.querySelector(".fact-chip")?.textContent ?? null,
  value: node.querySelector(".fact-value").textContent,
  tone: node.getAttribute("data-tone"),
  more: node.querySelector(".fact-more")?.querySelectorAll("p").map((line) => line.textContent) ?? [],
});

test("the fact says the class as its chip and the figure out of 10, with what it measures and that it is not a depth folded away", () => {
  const node = flashFact({ ...shop, flash_flood: { score: 7.24, class: "high" } });
  const { label, chip, value, tone, more } = factParts(node);
  assert.equal(`${label}: ${chip}, ${value}`, "Flash flood potential: High, 7.2 of 10");
  assert.equal(tone, "high");
  assert.match(more[0], /heavy rain/);
  assert.match(more.at(-1), /susceptibility, not a water depth/);
  assert.equal(node.querySelector(".ramp-swatch").getAttribute("style"), swatchStyle(FLASH_RAMP[2]));
});

test("each class has its tone: low reads low, medium some, high and extreme high", () => {
  const toneOf = (key) => flashFact({ ...shop, flash_flood: { score: 5, class: key } }).getAttribute("data-tone");
  assert.deepEqual(["low", "medium", "high", "extreme"].map(toneOf), ["low", "some", "high", "high"]);
});

test("with the area's own example, a section its record names, the fact says floods like those are what it measures", () => {
  const node = flashFact({ ...shop, flash_flood: { score: 2, class: "low" } }, INDEXED_AREA);
  assert.match(factParts(node).more[1], /^Flash floods are on record in Section 24, where the river model shows little or no water/);
  assert.equal(factParts(node).value, "2.0 of 10");
  inMalay(() => assert.match(flashFact({ ...shop, flash_flood: { score: 2, class: "low" } }, INDEXED_AREA).textContent, /di Seksyen 24/));
  const unnamed = flashFact({ ...shop, flash_flood: { score: 2, class: "low" } }, { ...INDEXED_AREA, flash_flood_example: "seksyen-u1" });
  assert.equal(factParts(unnamed).more.length, 2, "a section the record does not name: no example, never its id");
});

test("null means not worked out for this spot; a field the server never sent hides the fact", () => {
  const node = flashFact({ ...shop, flash_flood: null }, INDEXED_AREA);
  assert.equal(factParts(node).value, "Not worked out for this spot yet");
  assert.equal(factParts(node).chip, null);
  assert.ok(!node.textContent.includes("flash floods on record"), "no example beside a figure that is not there");
  assert.equal(flashFact(shop), null);
  assert.equal(flashFact({ ...shop, flash_flood: { score: 5, class: "odd" } }), null, "a class the page cannot name is not guessed at");
});

test("in Bahasa Melayu the fact reads naturally", () => {
  inMalay(() => {
    const { label, chip, value, more } = factParts(flashFact({ ...shop, flash_flood: { score: 7.2, class: "high" } }));
    assert.equal(`${label}: ${chip}, ${value}`, "Potensi banjir kilat: Tinggi, 7.2 daripada 10");
    assert.match(more.at(-1), /bukan kedalaman air/);
    assert.equal(factParts(flashFact({ ...shop, flash_flood: null })).value, "Belum dikira untuk tempat ini");
  });
});

test("My business shows the fact beside the others, with the example only for the page's own area", () => {
  const panel = document.createElement("section");
  const area = { ...HOME, flash_flood_example: "s-1", history: { ...HOME.history, section_names: { "s-1": { en: "Low Street", ms: "Jalan Rendah" } } } };
  const card = createBusiness(panel, { area, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {} });
  card.render({ premise: { ...shop, flash_flood: { score: 7.2, class: "high" } }, rp: "50" });
  assert.match(panel.textContent, /Flash flood potential.*High.*7\.2 of 10.*on record in Low Street/);
  card.render({ premise: point({ area_id: "far", flash_flood: { score: 3, class: "medium" } }), rp: "50" });
  assert.match(panel.textContent, /Medium3\.0 of 10/);
  assert.ok(!panel.textContent.includes("Low Street"), "another area's point does not get this area's example");
  card.render({ premise: shop, rp: "20" });
  assert.ok(!panel.textContent.includes("Flash flood potential"), "an older server: no fact at all");
});

// ---------- the map's controls ----------

test("the checkbox is a real, unchecked checkbox with a label, and says when it is turned on or off", () => {
  const calls = [];
  const [toggle] = mapControls({ hasLayer: true, metrics: [], onLayer: (on) => calls.push(on) });
  const input = toggle.querySelector("input");
  assert.equal(toggle.tagName, "label");
  assert.equal(input.getAttribute("type"), "checkbox");
  assert.equal(input.getAttribute("checked"), null, "off by default");
  assert.match(toggle.textContent, /Show flash flood potential/);
  input.checked = true;
  input.dispatch("change");
  input.checked = false;
  input.dispatch("change");
  assert.deepEqual(calls, [true, false]);
});

test("the radios are a named group, the river model first and chosen, each choice handed on", () => {
  const picked = [];
  const nodes = mapControls({ hasLayer: false, metrics: ["depth", "flash", "score"], word: SECTION_WORD, onMetric: (key) => picked.push(key) });
  assert.equal(nodes.length, 1, "no layer: no checkbox");
  const [group] = nodes;
  assert.equal(group.tagName, "fieldset");
  assert.equal(group.querySelector("legend").textContent, "Colour each section by");
  const radios = group.querySelectorAll("input");
  assert.deepEqual(radios.map((radio) => [radio.getAttribute("type"), radio.getAttribute("value")]),
    [["radio", "depth"], ["radio", "flash"], ["radio", "score"]]);
  assert.equal(new Set(radios.map((radio) => radio.getAttribute("name"))).size, 1, "one group");
  assert.equal(radios[0].getAttribute("checked"), "");
  assert.deepEqual(group.querySelectorAll("label").map((label) => label.textContent),
    ["Wet squares (river model)", "Flash flood potential", "Our score (1–5)"]);
  radios[1].dispatch("change");
  assert.deepEqual(picked, ["flash"]);
});

test("one metric is no choice: no radios; nothing at all when there is neither", () => {
  assert.deepEqual(mapControls({ hasLayer: false, metrics: ["depth"] }), []);
  assert.deepEqual(mapControls({ hasLayer: false, metrics: [] }), []);
});

// ---------- how these are worked out ----------

test("the method names the formula, the deviations and the sources, with a link where one is given", () => {
  const body = methodBody(INDEX_METHOD, { showScore: true, word: SECTION_WORD, credit: "ESA WorldCover 2021" });
  assert.match(body.map((node) => node.textContent).join(" "), /Rainfall and economic loss.*Leeonis, A\. N\./);
  assert.match(body.map((node) => node.textContent).join(" "), /Compared with past flood records/);
  const text = body.map((node) => node.textContent).join(" ");
  assert.match(text, /Smith \(2003\).*Yassin et al\. \(2023\)/);
  assert.match(text, /\(1\.5 × slope \+ land cover \+ soil \+ 0\.5 × plant cover\) ÷ 4/);
  assert.match(text, /Leeonis et al\. \(2024\)/);
  assert.match(text, /Vegetation cover from a satellite greenness composite\./);
  assert.match(text, /Smith, G\. \(2003\)/);
  assert.match(text, /ESA WorldCover 2021/);
  const links = body.flatMap((node) => node.querySelectorAll("a"));
  assert.deepEqual(links.map((a) => [a.getAttribute("href"), a.getAttribute("rel")]), [["https://example.org/pm", "noopener noreferrer"]]);
});

test("the score's own credit line shows with the score, as fine print", () => {
  const body = methodBody(INDEX_METHOD, { showScore: true, word: SECTION_WORD });
  const credit = body.find((node) => node.textContent === INDEX_METHOD.score.credit);
  assert.ok(credit, "the score credit is shown");
  assert.equal(credit.getAttribute("class"), "fineprint");
  const withoutCredit = { ...INDEX_METHOD, score: { ...INDEX_METHOD.score, credit: undefined } };
  assert.doesNotMatch(methodBody(withoutCredit, { showScore: true }).map((node) => node.textContent).join(" "), /WorldPop/);
});

test("with the score hidden the method leaves it out; with no method only the index's own words show", () => {
  const text = methodBody(INDEX_METHOD, { showScore: false, word: SECTION_WORD }).map((node) => node.textContent).join(" ");
  assert.doesNotMatch(text, /Leeonis|Rainfall|Compared with|WorldPop/);
  const bare = methodBody(null, { showScore: false }).map((node) => node.textContent).join(" ");
  assert.match(bare, /Smith \(2003\)/);
  assert.doesNotMatch(bare, /differ/);
});

test("the comparison with recorded floods is put in words from its rank correlation", async () => {
  const { matchKey, comparedNote } = await import("../app/static/js/susceptibility.js");
  assert.equal(matchKey(0.017), "compare.none");
  assert.equal(matchKey(-0.183), "compare.none");
  assert.equal(matchKey(0.3), "compare.weak");
  assert.equal(matchKey(0.398), "compare.moderate");
  assert.equal(matchKey(0.64), "compare.strong");
  assert.equal(matchKey(-0.2), "compare.opposite");
  assert.equal(matchKey(-0.45), "compare.opposite");
  assert.equal(matchKey(-0.199), "compare.none");
  const validation = { n: 56, spearman: { flash_vs_history: 0.017, score_vs_history: 0.398 } };
  assert.equal(comparedNote(validation, "flash", { en: "Section", ms: "Seksyen" }),
    "Compared with the floods on record, section by section (56 in all): no clear match (rank correlation 0.02).");
  assert.match(comparedNote(validation, "score", null), /a moderate match \(rank correlation 0\.40\)/);
  assert.equal(comparedNote({ n: 56 }, "flash"), null, "no figure, no note");
  const against = { n: 56, spearman: { flash_vs_history: -0.25 } };
  assert.equal(comparedNote(against, "flash", { en: "Section", ms: "Seksyen" }),
    "Compared with the floods on record, section by section (56 in all): the ranking goes the other way, with more floods on record where it ranks lower (rank correlation -0.25).");
  inMalay(() => assert.match(comparedNote(against, "flash", { en: "Section", ms: "Seksyen" }), /berlawanan arah.*\(korelasi pangkat -0\.25\)/));
});
