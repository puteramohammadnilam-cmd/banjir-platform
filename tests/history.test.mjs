// Run from 11_Platform_Draft:  node --test tests/history.test.mjs
// The past-floods block (history.js) on the fake DOM: an area with a plain record (Kuantan and the others) keeps the
// look it has today; a record cut to a city or one of its sections (app/history.py for_scope) adds source links, type
// and confidence tags, section names in the city list, a gaps line, and says "no record found", never "no flood".
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { floodCounts, renderHistory } from "../app/static/js/history.js";
import { useLang } from "../app/static/js/i18n.js";
import { installFakeDom } from "./fake_dom.mjs";

// the old Taman Sri Muda area is now part of the city: its area.json is kept frozen beside its build
const AREA_FILES = { "sri-muda": "../tests/fixtures/sri_muda_built/area.json" };
const areaJson = (id) => JSON.parse(readFileSync(new URL(AREA_FILES[id] ?? `../app/data/areas/${id}/area.json`, import.meta.url), "utf8"));
const NAMES = { "sec-1": { en: "Part 1", ms: "Bahagian 1" }, "sec-2": { en: "Part 2", ms: "Bahagian 2" },
  "sec-3": { en: "Part 3", ms: "Bahagian 3" } };

function flood(id, date, year, sections, change = {}) {
  return { id, date, when: date, year, place: "A street", what: "A flood.", depth: null, sections, confidence: "high",
    account: false, undated: false, source: "Paper", url: "https://example.org/a", source_type: "news",
    sources: [{ title: "Paper", url: "https://example.org/a", type: "news" }], ...change };
}

const CITY = {
  first_year: 1992, recent_from: 2019, last_year: 2026, scope: null, checked: "2026-10-04",
  section_names: { "sec-1": NAMES["sec-1"], "sec-2": NAMES["sec-2"] }, gaps: [[1992, 1994], [1996, 2020], [2022, 2022], [2024, 2026]],
  floods: [
    flood("a", "1995-12-24", 1995.98, ["sec-1"], { depth: "a little over 1 m", confidence: "medium" }),
    flood("b", "2021-05-18", 2021.38, ["sec-1"], { sources: [
      { title: "Good link", url: "https://example.org/good", type: "official" },
      { title: "Plain link", url: "http://example.org/plain", type: "news" },
      { title: "Script link", url: "javascript:alert(1)", type: "news" }] }),
    flood("c", "2021-05-18", 2021.38, ["sec-2"], { confidence: "medium", source_type: "dataset",
      sources: [{ title: "A public layer", url: "https://example.org/layer", type: "dataset" }] }),
    flood("d", "2021", 2021.5, ["sec-2"], { undated: true, confidence: "low" }),
    flood("e", "2023-01-02", 2023.0, []),
  ],
};
const AREA = { id: "town", name: "Town", display_name: "Town, State" };

function render(history, area = AREA) {
  installFakeDom();
  const element = document.createElement("section");
  renderHistory(element, { ...area, history });
  return element;
}
const texts = (element, selector) => element.querySelectorAll(selector).map((node) => node.textContent);

function inLang(code, run) {
  useLang(code);
  try {
    return run();
  } finally {
    useLang("en");
  }
}

// ---------- areas with a plain record keep today's look

for (const id of ["kuantan", "kota-bharu", "kuala-terengganu", "sri-muda"]) {
  test(`${id}: the record looks as it did, with no links, tags or gaps line`, () => {
    const area = areaJson(id);
    const element = render(area.history, area);
    assert.deepEqual(element.children.map((child) => child.tagName), ["h2", "p", "svg", "p", "details"]);
    const counts = floodCounts(area.history);
    assert.equal(element.querySelector(".history-lead").textContent,
      `${counts.dated} dated floods at ${area.name} since ${counts.since} in the sources we checked, ${counts.recent} of them since ${counts.recentFrom}. Not a complete record.`);
    assert.deepEqual(texts(element, "li"), area.history.floods.map((f) => `${f.when} ${f.what} ${f.source}`));
    assert.equal(element.querySelectorAll("a").length, 0);
    assert.equal(element.querySelectorAll(".tag").length, 0);
    assert.equal(element.querySelector(".history-gaps"), null);
  });
}

test("an area with no record collected still says so in its old words", () => {
  const element = render(null);
  assert.equal(element.querySelector(".history-none").textContent, "No flood record collected for Town, State yet.");
});

// ---------- a city or section record

test("counts are of distinct flood days, and a year with no day given is not counted as a dated flood", () => {
  assert.deepEqual(floodCounts(CITY), { dated: 3, recent: 2, since: 1992, recentFrom: 2019 });
});

test("source links are https only, open in a new tab and send no referrer; others stay plain text", () => {
  const element = render(CITY);
  const links = element.querySelectorAll("a");
  assert.deepEqual(links.map((a) => a.getAttribute("href")),
    ["https://example.org/a", "https://example.org/good", "https://example.org/layer", "https://example.org/a", "https://example.org/a"]);
  for (const a of links) {
    assert.equal(a.getAttribute("rel"), "noopener noreferrer");
    assert.equal(a.getAttribute("target"), "_blank");
  }
  const second = element.querySelectorAll("li")[1].textContent;
  assert.match(second, /Plain link/);
  assert.match(second, /Script link/);
});

test("each flood shows its place, depth, source types, confidence and, in the city list, its sections", () => {
  const items = render(CITY).querySelectorAll("li");
  assert.deepEqual(texts(items[0], ".tag"), ["News", "Medium confidence", "Part 1"]);
  assert.deepEqual(texts(items[1], ".tag"), ["Official", "News", "High confidence", "Part 1"]);
  assert.deepEqual(texts(items[2], ".tag"), ["Dataset", "Medium confidence", "Part 2"]);
  assert.deepEqual(texts(items[4], ".tag"), ["News", "High confidence"]);
  assert.match(items[0].textContent, /^1995-12-24 A flood\. A street/);
  assert.match(items[0].textContent, /Depth reported: a little over 1 m/);
});

test("section names follow the page's language", () => {
  const tags = inLang("ms", () => texts(render(CITY).querySelectorAll("li")[0], ".tag"));
  assert.deepEqual(tags, ["Berita", "Keyakinan sederhana", "Bahagian 1"]);
});

test("in one section's record the lead names the section and the list leaves section tags out", () => {
  const section = { ...CITY, scope: "sec-1", floods: CITY.floods.slice(0, 2) };
  const element = render(section);
  assert.match(element.querySelector(".history-lead").textContent, /^2 dated floods at Part 1 since 1992/);
  assert.deepEqual(texts(element.querySelectorAll("li")[0], ".tag"), ["News", "Medium confidence"]);
});

test("the gaps line lists the runs of three years or more with no record", () => {
  assert.equal(render(CITY).querySelector(".history-gaps").textContent,
    "Years with no flood record in the sources we checked include 1992–1994, 1996–2020, 2024–2026.");
});

test("a hollow dot is explained for a year whose reports give no day", () => {
  const element = render(CITY);
  assert.match(texts(element, ".fineprint").join(" "), /A hollow dot is a year with reports that give no day\./);
  assert.equal(element.querySelectorAll(".flood-dot.is-account").length, 0, "2021 also has dated floods, so its dot is full");
});

test("a section with no record says none was found, never that it does not flood, in both languages", () => {
  const empty = { ...CITY, scope: "sec-3", section_names: { "sec-3": NAMES["sec-3"] }, gaps: [[1992, 2026]], floods: [] };
  const element = render(empty);
  assert.equal(element.querySelector(".history-none").textContent,
    "No flood record found for Part 3 in the sources we checked (1992–2026). That does not mean it has never flooded.");
  assert.equal(element.querySelector("svg"), null);
  const malay = inLang("ms", () => render(empty).querySelector(".history-none").textContent);
  assert.equal(malay,
    "Tiada rekod banjir ditemui untuk Bahagian 3 dalam sumber yang kami semak (1992–2026). Ini tidak bermakna kawasan ini tidak pernah dilanda banjir.");
});

test("a city with no record uses the area's name", () => {
  const empty = { ...CITY, section_names: {}, gaps: [[1992, 2026]], floods: [] };
  assert.match(render(empty).querySelector(".history-none").textContent, /^No flood record found for Town, State in/);
});
