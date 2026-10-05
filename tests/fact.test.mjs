// Run from 11_Platform_Draft:  node --test tests/fact.test.mjs
// The at-a-glance facts (fact.js) and the verdicts the My business tab gives them: a tone and a chip for the road, the
// ground and the flood record, the distance as a person says it, the limits folded away, and the area's long data
// notes on the Area overview folded under short headings. Never the word "safe".
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createBusiness } from "../app/static/js/card.js";
import { elevationFact } from "../app/static/js/elevation.js";
import { distanceText, factCard, factGroup } from "../app/static/js/fact.js";
import { h } from "../app/static/js/dom.js";
import { useLang } from "../app/static/js/i18n.js";
import { renderAreaLabels } from "../app/static/js/overview.js";
import { installFakeDom } from "./fake_dom.mjs";
import { AREAS, HOME, shop } from "./point_fixtures.mjs";

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

test("a card leaves out the parts it is not given: no chip, no fold, no tone it does not know", () => {
  const card = factCard({ iconName: "pin", label: "Label", value: "Value", tone: "odd" });
  assert.equal(card.getAttribute("data-tone"), null);
  assert.equal(card.querySelector(".fact-chip"), null);
  assert.equal(card.querySelector(".fact-more"), null);
  const full = factCard({ iconName: "pin", label: "Label", value: "Value", tone: "high", chip: "Chip", more: [null, h("p", {}, "Why")] });
  assert.equal(full.getAttribute("data-tone"), "high");
  assert.equal(full.querySelector(".fact-more").textContent, "How to read thisWhy");
});

test("a group with no facts is left out, and one with facts has its heading", () => {
  assert.equal(factGroup("Empty", [null, false]), null);
  assert.equal(factGroup("Some", [h("p", {}, "a")]).querySelector("h2").textContent, "Some");
});

test("a distance under 1 km is in metres, from 1 km in kilometres with one decimal", () => {
  assert.equal(distanceText(850.4), "850 m away");
  assert.equal(distanceText(999.6), "1.0 km away", "rounded first, so never 1,000 m");
  assert.equal(distanceText(3019), "3.0 km away");
  assert.equal(distanceText(12_345), "12.3 km away");
  useLang("ms");
  assert.equal(distanceText(3019), "3.0 km dari sini");
  useLang("en");
});

/** The road fact's tone and chip when its water at rp "20" is `depth`. */
function roadVerdict(depth) {
  const panel = document.createElement("section");
  const card = createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {} });
  card.render({ premise: { ...shop, road: { ...shop.road, depth_m: { 10: null, 20: depth, 50: null } } }, rp: "20" });
  const road = panel.querySelectorAll(".fact").find((fact) => fact.querySelector(".fact-label").textContent === "Road access");
  return [road.getAttribute("data-tone"), road.querySelector(".fact-chip").textContent];
}

test("the road's chip goes by the water a car meets: dry, shallow, hard, then too deep from 30 cm", () => {
  assert.deepEqual(roadVerdict(null), ["low", "Dry in the model"]);
  assert.deepEqual(roadVerdict(0.1), ["some", "Shallow"]);
  assert.deepEqual(roadVerdict(0.15), ["some", "Hard for cars"]);
  assert.deepEqual(roadVerdict(0.29), ["some", "Hard for cars"]);
  assert.deepEqual(roadVerdict(0.3), ["high", "Too deep for cars"]);
});

test("the road keeps its name and distance on show and folds the limit away", () => {
  const panel = document.createElement("section");
  createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {} }).render({ premise: shop, rp: "20" });
  const road = panel.querySelectorAll(".fact").find((fact) => fact.querySelector(".fact-label").textContent === "Road access");
  assert.equal(road.querySelector(".fact-note").textContent, "Jalan A, 9 m away.");
  assert.equal(road.querySelector(".fact-more").querySelector("p").textContent, "A rough sign of being cut off, not a road closure.");
});

test("a fold the reader opened stays open when the side is rebuilt for another flood size", () => {
  const panel = document.createElement("section");
  const card = createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {} });
  const roadFold = () => panel.querySelectorAll(".fact").find((fact) => fact.querySelector(".fact-label").textContent === "Road access").querySelector(".fact-more");
  card.render({ premise: shop, rp: "20" });
  roadFold().setAttribute("open", "");
  card.render({ premise: shop, rp: "50" });
  assert.notEqual(roadFold().getAttribute("open"), null);
  assert.equal(panel.querySelectorAll(".fact-more").filter((fold) => fold.getAttribute("open") != null).length, 1, "only that one");
});

test("the flood record is the area's: any recent flood reads some, never high, with often from 3", () => {
  const verdict = (recentYears) => {
    const floods = recentYears.map((year) => ({ when: `May ${year}`, year: year + 0.4, what: "A flood.", source: "A paper" }));
    const panel = document.createElement("section");
    createBusiness(panel, { area: { ...HOME, history: { ...HOME.history, floods } }, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {} })
      .render({ premise: shop, rp: "20" });
    const fact = panel.querySelectorAll(".fact").find((one) => one.querySelector(".fact-label").textContent === "Floods recorded here");
    return fact && [fact.getAttribute("data-tone"), fact.querySelector(".fact-chip")?.textContent ?? null];
  };
  assert.deepEqual(verdict([2020]), ["some", "Now and then"]);
  assert.deepEqual(verdict([2020, 2021, 2022]), ["some", "Often"]);
});

test("lower ground reads higher: near the river high, 1 to 3 m some, more than 3 m low, no river no tone", () => {
  const verdict = (above) => {
    const fact = elevationFact({ elevation: { ground_m: 6, above_river_m: above } });
    return [fact.getAttribute("data-tone"), fact.querySelector(".fact-chip")?.textContent ?? null];
  };
  assert.deepEqual(verdict(0.2), ["high", "Low-lying"]);
  assert.deepEqual(verdict(2), ["some", "A little higher"]);
  assert.deepEqual(verdict(5), ["low", "Higher ground"]);
  assert.deepEqual(verdict(null), [null, null]);
});

test("no chip or fact on My business says safe, in either language", () => {
  for (const lang of ["en", "ms"]) {
    useLang(lang);
    const panel = document.createElement("section");
    createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {} })
      .render({ premise: { ...shop, road: { ...shop.road, depth_m: { 10: null, 20: null, 50: null } } }, rp: "20" });
    assert.ok(!/\b(safe|selamat)\b/i.test(panel.textContent), lang);
  }
  useLang("en");
});

test("the area's data notes are listed open in the Reference tab, and fold under the business list", () => {
  const elements = new Map();
  globalThis.document.getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, h(id === "finder-hero-label" ? "label" : "div"));
    return elements.get(id);
  };
  renderAreaLabels({ ...HOME, notes: { depths: "Depths note.", shelters: "Shelters note.", sections: "Sections note.", businesses: "Businesses note." } });
  const notes = elements.get("map-note");
  assert.equal(elements.get("map-notes-card").hidden, false);
  assert.deepEqual(notes.querySelectorAll("h3").map((heading) => heading.textContent), ["Where the flood depths come from",
    "Where the relief centres come from", "Where the section outlines come from", "Where the list of businesses comes from"]);
  assert.deepEqual(notes.querySelectorAll("p").map((line) => line.textContent), ["Depths note.", "Shelters note.", "Sections note.", "Businesses note."]);
  assert.equal(elements.get("directory-note").querySelector("summary").textContent, "Where the list of businesses comes from");
  renderAreaLabels({ ...HOME, notes: null });
  assert.equal(elements.get("map-notes-card").hidden, true);
  assert.equal(elements.get("map-note").children.length, 0);
});

