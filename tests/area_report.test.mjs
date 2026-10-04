// Run from 11_Platform_Draft:  node --test tests/area_report.test.mjs
// The printable area summary for associations and councils (area-report.js): the area's own figures, worked out from
// its data in the page, its streets with the most wet businesses, its flood record and its notes.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { areaSummary, buildAreaReport, topSections } from "../app/static/js/area-report.js";
import { pageArea } from "../app/static/js/start.js";
import { installFakeDom } from "./fake_dom.mjs";
import { CITY_AREA, INDEX, SECTIONS, SECTION_WORD } from "./fixtures/city_data.mjs";

const road = (name) => ({ name, kind: "residential", distance_m: 5, depth_m: { 10: null, 20: null, 50: null } });
const biz = (id, roadName, d10, d20, d50) => ({ id, name: id, road: road(roadName), depth_m: { 10: d10, 20: d20, 50: d50 } });
const PREMISES = [
  biz("a", "Jalan Satu", null, 0.5, 1.0), biz("b", "Jalan Satu", 0.2, 1.5, 2.0), biz("c", "Jalan Dua", null, 3.5, 4.0),
  biz("d", "a road with no name", null, 0.4, 0.6), biz("e", "Jalan Dua", null, null, null),
];
const AREA = {
  id: "home", name: "Home Town", display_name: "Home Town, Some State", council: "Majlis Home (MH)",
  notes: { businesses: "Mapped on OpenStreetMap.", depths: "Depth check: the model runs deep." },
  history: { first_year: 2012, recent_from: 2019, last_year: 2026, floods: [
    { when: "24 Dec 2012", year: 2012.98, what: "Roads flooded.", source: "Bernama, 24 Dec 2012" },
    { when: "1999", year: 1999.5, account: true, what: "A trader recalls water.", source: "Bernama, one person's account" },
  ] },
};

beforeEach(() => installFakeDom());

test("the summary counts wet businesses and their typical depth for each flood size", () => {
  const summary = areaSummary(PREMISES);
  assert.equal(summary.total, 5);
  assert.deepEqual(summary.floods.map((f) => [f.rp, f.wet, f.percent, f.median, f.chance]), [
    ["10", 1, 20, 0.2, 65], ["20", 4, 80, 1.0, 40], ["50", 4, 80, 1.5, 18],
  ]);
});

test("the streets with the most wet businesses at the default size, 1 in 50, are named, unnamed roads left out", () => {
  assert.deepEqual(areaSummary(PREMISES).streets, [{ name: "Jalan Satu", wet: 2 }, { name: "Jalan Dua", wet: 1 }]);
});

test("the sheet holds the figures, the streets, the record with sources, the notes and the model's limits", () => {
  const sheet = buildAreaReport({ area: AREA, premises: PREMISES, date: "3 Oct 2026" });
  const text = sheet.textContent;
  assert.match(text, /Flood summary: Home Town, Some State/);
  assert.match(text, /5 businesses mapped on OpenStreetMap/);
  assert.match(sheet.querySelectorAll("tr")[2].textContent, /1 in 20 years.*40%.*4 of 5.*80%.*1\.0 m/);
  assert.match(text, /with water in the model, 1 in 50 years.*Jalan Satu: 2/);
  assert.match(text, /24 Dec 2012: Roads flooded\. \(Bernama, 24 Dec 2012\)/);
  assert.match(text, /One person's recollection/);
  assert.match(text, /Depth check: the model runs deep\./);
  assert.match(text, /not an official flood map/);
  assert.match(text, /Majlis Home \(MH\)/);
  assert.match(text, /3 Oct 2026/);
});

test("an area with no flood record says so", () => {
  const text = buildAreaReport({ area: { ...AREA, history: null }, premises: PREMISES, date: "3 Oct 2026" }).textContent;
  assert.match(text, /No flood record collected for Home Town yet/);
});

import { useLang } from "../app/static/js/i18n.js";

test("in Bahasa Melayu the sheet's labels say dalam model", () => {
  useLang("ms");
  try {
    const text = buildAreaReport({ area: AREA, premises: PREMISES, date: "3 Okt 2026" }).textContent;
    assert.match(text, /Perniagaan yang dimasuki air, dalam model/);
    assert.match(text, /1 dalam 50 tahun/);
  } finally {
    useLang("en");
  }
});

// ---------- a city split into sections ----------

const cityReport = () => buildAreaReport({ area: CITY_AREA, premises: INDEX, sections: SECTIONS, word: SECTION_WORD, date: "5 Oct 2026" });

test("the city's sections with the most businesses with water, at 1 in 50, biggest first, none with none", () => {
  assert.deepEqual(topSections(SECTIONS).map(({ id, wet, total }) => [id, wet, total]), [["seksyen-25", 2, 3], ["seksyen-24", 1, 1]]);
  const many = Array.from({ length: 14 }, (_, i) => ({ ...SECTIONS[0], id: `s-${i}`, counts: { ...SECTIONS[0].counts, wet_businesses: { 10: 0, 20: 0, 50: i + 1 } } }));
  assert.equal(topSections(many).length, 10, "ten at most");
  assert.equal(topSections(many)[0].id, "s-13");
});

test("the city's sheet is the whole city's, from its index, and adds the table of sections", () => {
  const sheet = cityReport();
  assert.equal(sheet.querySelector("h3").textContent, "Flood summary: Shah Alam, Selangor");
  assert.match(sheet.textContent, /5 businesses mapped/);
  const headings = sheet.querySelectorAll("h4").map((heading) => heading.textContent);
  assert.ok(headings.includes("The sections with the most businesses with water in the model, 1 in 50 years"), headings.join(" | "));
  const [, sections] = sheet.querySelectorAll("table");
  assert.deepEqual(sections.querySelectorAll("th").map((cell) => cell.textContent), ["Section", "Businesses with water", "Squares with water", "Seksyen 25", "Seksyen 24"]);
  assert.deepEqual(sections.querySelectorAll("td").map((cell) => cell.textContent), ["2 of 3", "58%", "1 of 1", "11%"]);
  assert.match(sheet.textContent, /Jalan Sungai: 2/, "the streets come from the index too");
});

test("a section's sheet is the section's, with no table of sections; a plain area's is as it was", () => {
  const page = pageArea(CITY_AREA, SECTIONS[1]);
  const sheet = buildAreaReport({ area: page, premises: INDEX.slice(1, 4), sections: null, word: SECTION_WORD, date: "5 Oct 2026" });
  assert.equal(sheet.querySelector("h3").textContent, "Flood summary: Seksyen 25, Shah Alam");
  assert.equal(sheet.querySelectorAll("table").length, 1);
  assert.equal(buildAreaReport({ area: AREA, premises: PREMISES, date: "5 Oct 2026" }).querySelectorAll("table").length, 1);
});

test("in Bahasa Melayu the table of sections uses the area's own word", () => {
  useLang("ms");
  try {
    const sheet = cityReport();
    assert.ok(sheet.querySelectorAll("h4").some((heading) => heading.textContent.startsWith("Senarai seksyen dengan paling banyak")));
    assert.equal(sheet.querySelectorAll("table")[1].querySelector("th").textContent, "Seksyen");
  } finally {
    useLang("en");
  }
});
