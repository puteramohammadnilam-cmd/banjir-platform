// Run from 11_Platform_Draft:  node --test tests/overview.test.mjs
// The Area overview's list of businesses (overview.js createDirectory) and the words that name the area, on the small
// fake DOM in tests/fake_dom.mjs: a search that could mean several businesses shows them all and says how many, one that
// matches none says why and what to do next, and the search's heading names the area it covers.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { SQUARE_RAMP } from "../app/static/js/cells.js";
import { BANDS, h } from "../app/static/js/dom.js";
import { createCityDirectory, createDirectory, renderAreaLabels, renderLegend } from "../app/static/js/overview.js";
import { pageArea } from "../app/static/js/start.js";
import { CITY_AREA, INDEX, SECTIONS, SECTION_WORD } from "./fixtures/city_data.mjs";
import { installFakeDom } from "./fake_dom.mjs";
import { HOME, shop } from "./point_fixtures.mjs";

const dobi = (id, name) => ({ ...shop, id, name });
const PREMISES = [dobi("d-1", "DOBI DHOLPIN"), dobi("d-2", "Dobi DIY Selesa"), dobi("d-3", "Dobi Queen"), shop];

beforeEach(() => installFakeDom());

/** The list with its filter, status line, next steps and column heads; `ways(calls)` gives the optional ways on. */
function mount(ways = {}) {
  const parts = { list: h("ol"), filter: h("input"), status: h("p"), next: h("div"), head: h("div") };
  const opened = [];
  const calls = [];
  const directory = createDirectory(parts, PREMISES, { area: HOME, onOpen: (id) => opened.push(id), ...ways(calls) });
  return { ...parts, directory, opened, calls };
}

const shownNames = (list) => list.children.filter((item) => !item.hidden).map((item) => item.querySelector(".name").textContent);
const buttonTexts = (node) => node.querySelectorAll("button").map((button) => button.textContent);
const BOTH_WAYS = (calls) => ({ onCheckPoint: (button) => calls.push(["check", button]), onOtherArea: () => calls.push(["area"]) });

test("a search several businesses match shows them all, says how many, and each row opens its business", () => {
  const { list, filter, status, next, head, directory, opened } = mount(BOTH_WAYS);
  directory.showMatches("dobi");
  assert.equal(filter.value, "dobi", "the filter box holds the search");
  assert.deepEqual(shownNames(list), ["DOBI DHOLPIN", "Dobi DIY Selesa", "Dobi Queen"]);
  assert.equal(status.textContent, "3 businesses match “dobi”. Pick yours.");
  assert.equal(next.hidden, true, "no next steps while the list has rows");
  assert.equal(head.hidden, false);
  list.children.find((item) => !item.hidden && item.textContent.includes("Queen")).querySelector("button").click();
  assert.deepEqual(opened, ["d-3"]);
});

test("a search that matches nothing says the list misses shops, with a way to check the spot and to pick another area", () => {
  const { list, status, next, head, directory, calls } = mount(BOTH_WAYS);
  directory.showMatches("Kedai Runcit Pak Ali");
  assert.deepEqual(shownNames(list), []);
  assert.equal(status.textContent, `Not on our list for ${HOME.name}. Our list comes from a public map and misses some shops.`);
  assert.equal(head.hidden, true, "no column heads over an empty list");
  assert.equal(next.hidden, false);
  assert.deepEqual(buttonTexts(next), ["Check the spot on the map", "Pick another area"]);
  const [check, area] = next.querySelectorAll("button");
  check.dispatch("click", { currentTarget: check });   // the button, for focus to go back to on Cancel
  area.click();
  assert.deepEqual(calls, [["check", check], ["area"]]);
});

test("the next steps leave out what this build or this area cannot do", () => {
  const { next, directory } = mount(() => ({ onCheckPoint: null, onOtherArea: () => {} }));
  directory.showMatches("nothing");
  assert.deepEqual(buttonTexts(next), ["Pick another area"]);
  const bare = mount(() => ({}));
  bare.directory.showMatches("nothing");
  assert.equal(bare.next.hidden, true, "with no way on, no empty row of buttons");
});

test("a search one business matches says so in the singular", () => {
  const { status, directory } = mount(() => ({}));
  directory.showMatches(shop.name);
  assert.equal(status.textContent, `1 business matches “${shop.name}”.`);
});

test("typing in the filter filters quietly, with the plain message when nothing matches and no search's count", () => {
  const { list, filter, status, next, directory } = mount(BOTH_WAYS);
  directory.showMatches("dobi");
  filter.value = "queen";
  filter.dispatch("input");
  assert.deepEqual(shownNames(list), ["Dobi Queen"]);
  assert.equal(status.textContent, "", "the search's count goes once the filter is typed in");
  filter.value = "zzz";
  filter.dispatch("input");
  assert.equal(status.textContent, "No business matches that filter.");
  assert.equal(next.hidden, false, "the ways on are there for a typed filter too");
  filter.value = "";
  filter.dispatch("input");
  assert.equal(shownNames(list).length, PREMISES.length);
  assert.equal(status.textContent, "");
  assert.equal(next.hidden, true);
});

test("the search's heading names the area it covers, by its short name", () => {
  const elements = new Map();
  globalThis.document.getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, h(id === "finder-hero-label" ? "label" : "p"));
    return elements.get(id);
  };
  renderAreaLabels(HOME);
  assert.equal(elements.get("finder-hero-label").textContent, `Find your shop in ${HOME.name}`);
});

// ---------- the map's key ----------

test("the key has two groups: the dots' five classes with no water and the relief centre, and the squares' ramp", () => {
  const legend = h("ul");
  renderLegend(legend, true);
  const [dots, squares] = legend.querySelectorAll(".legend-group");
  assert.deepEqual(legend.children.map((group) => group.querySelector(".legend-heading").textContent),
    ["Dots: water at each business", "Squares: the model's 90 m squares, darker = deeper"]);
  assert.deepEqual(dots.querySelectorAll(".swatch").map((swatch) => swatch.getAttribute("class")),
    [...BANDS.map((_, i) => `swatch band-${i + 1}`), "swatch swatch-dry"]);
  assert.ok(dots.querySelector(".shelter-pin"), "the relief centre is a dot's kind of mark");
  assert.deepEqual(squares.querySelector(".square-strip").children.map((step) => step.getAttribute("class")),
    SQUARE_RAMP.map((_, i) => `sq-${i + 1}`), "one step for each step of the ramp, shallowest first");
  assert.deepEqual(squares.querySelectorAll(".muted").map((end) => end.textContent), ["under 0.9 m", "3 m or more"]);
  assert.equal(squares.querySelector(".square-strip").getAttribute("aria-hidden"), "true", "the heading and the two ends say it all");
});

test("the key leaves out the relief centre when the area has none", () => {
  const legend = h("ul");
  renderLegend(legend, false);
  assert.equal(legend.querySelector(".shelter-pin"), null);
  assert.equal(legend.querySelectorAll(".swatch").length, BANDS.length + 1);
});

test("a section's page names the section, with its city, in the search's heading and the list's", () => {
  const elements = new Map();
  globalThis.document.getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, h("p"));
    return elements.get(id);
  };
  renderAreaLabels(pageArea(CITY_AREA, SECTIONS[1]));
  assert.equal(elements.get("finder-hero-label").textContent, "Find your shop in Seksyen 25");
  assert.equal(elements.get("directory-heading").textContent, "Businesses in Seksyen 25");
  assert.equal(elements.get("map").getAttribute("aria-label"), "Map of Seksyen 25, Shah Alam, with modelled flood depth at each business");
});

// ---------- a section's page, once its city's index is in ----------

const SECTION_PREMISES = INDEX.filter((row) => row.section === "seksyen-25");

function mountSection() {
  const parts = { list: h("ol"), filter: h("input"), status: h("p"), next: h("div"), head: h("div") };
  const opened = [];
  const directory = createDirectory(parts, SECTION_PREMISES, {
    area: pageArea(CITY_AREA, SECTIONS[1]), onOpen: (id) => opened.push(id), onCheckPoint: () => {},
  });
  return { ...parts, directory, opened };
}

test("on a section's page a search matching only other sections shows those, with their sections, once the city's index is in", () => {
  const { list, status, directory, opened } = mountSection();
  directory.showMatches("kedai");
  assert.deepEqual(shownNames(list), [], "before the index: this section's list only");
  directory.widen(INDEX, SECTIONS, "Shah Alam");
  directory.showMatches("kedai");
  assert.deepEqual(shownNames(list), ["Kedai Dua Empat", "Kedai U Satu"]);
  assert.match(list.children.find((item) => item.textContent.includes("U Satu")).querySelector(".meta").textContent, /· Seksyen U1$/);
  assert.equal(status.textContent, "2 businesses match “kedai”. Pick yours.");
  list.children.find((item) => item.textContent.includes("U Satu")).querySelector("button").click();
  assert.deepEqual(opened, ["node-u1"], "the page opens it on its own section's page (main.js)");
});

test("a widened search lists this section's matches first, once each, and the city's none-found names the city", () => {
  const { list, status, filter, directory } = mountSection();
  directory.widen(INDEX, SECTIONS, "Shah Alam");
  directory.showMatches("a");
  const names = shownNames(list);
  assert.deepEqual(names.slice(0, 2), ["A Shop", "Dobi Kering"], "this section's own first");
  assert.equal(new Set(names).size, names.length, "a business of this section is not listed twice");
  directory.showMatches("Kedai Runcit Pak Ali");
  assert.equal(status.textContent, "Not on our list for Shah Alam. Our list comes from a public map and misses some shops.");
  filter.value = "";
  filter.dispatch("input");
  assert.deepEqual(shownNames(list), ["A Shop", "Dobi Kering", "Dobi Queen"], "an empty filter: this section's list again");
});

// ---------- the whole city ----------

function mountCity(index = INDEX) {
  const parts = { list: h("ol"), filter: h("input"), status: h("p"), next: h("div"), head: h("div") };
  const opened = [];
  const directory = createCityDirectory(parts, index, {
    area: CITY_AREA, sections: SECTIONS, onOpen: (id) => opened.push(id), onCheckPoint: () => {}, onOtherArea: () => {},
  });
  return { ...parts, directory, opened };
}
const typeIn = (filter, text) => { filter.value = text; filter.dispatch("input"); };

test("the whole city's list shows nothing until a name is typed, and says how many it can search", () => {
  const { list, status, head, next } = mountCity();
  assert.equal(list.children.length, 0, "no rows are built for a city's thousands of businesses up front");
  assert.equal(status.textContent, `Type a name to search the ${INDEX.length} businesses in Shah Alam.`);
  assert.equal(head.hidden, true);
  assert.equal(next.hidden, true);
});

test("a filter shows the city's matching businesses, each with its section, and a row opens its business", () => {
  const { list, filter, status, opened } = mountCity();
  typeIn(filter, "dobi");
  assert.deepEqual(shownNames(list), ["Dobi Kering", "Dobi Queen"]);
  assert.match(list.children[0].querySelector(".meta").textContent, /· Seksyen 25$/);
  assert.match(list.children[0].querySelector("button").getAttribute("aria-label"), /In Seksyen 25\.$/);
  assert.equal(status.textContent, "");
  list.children[1].querySelector("button").click();
  assert.deepEqual(opened, ["node-2"]);
  typeIn(filter, "seksyen u1");
  assert.deepEqual(shownNames(list), ["Kedai U Satu"], "a section's name finds its businesses");
  typeIn(filter, "");
  assert.equal(list.children.length, 0, "an emptied filter empties the list again");
});

test("a search with more than 100 matches shows the first 100 and says to type more", () => {
  const many = Array.from({ length: 140 }, (_, i) => ({ ...INDEX[1], id: `node-${1000 + i}`, name: `Kedai ${String(i).padStart(3, "0")}` }));
  const { list, directory, status } = mountCity(many);
  directory.showMatches("kedai");
  assert.equal(list.children.length, 100);
  assert.equal(status.textContent, "Showing the first 100 of 140 matches. Type more of the name to narrow them.");
  assert.equal(shownNames(list)[0], "Kedai 000");
});

test("a search that matches nothing in the city says so, with the ways on", () => {
  const { directory, status, next } = mountCity();
  directory.showMatches("Kedai Runcit Pak Ali");
  assert.equal(status.textContent, "Not on our list for Shah Alam. Our list comes from a public map and misses some shops.");
  assert.equal(next.hidden, false);
});

test("the city's key: the sections' shading in the area's word, the squares' ramp, the relief centre", () => {
  const legend = h("ul");
  renderLegend(legend, true, { word: SECTION_WORD });
  assert.deepEqual(legend.children.map((group) => group.querySelector(".legend-heading").textContent),
    ["Shading: share of each section's 90 m squares with water", "Squares: the model's 90 m squares, darker = deeper"]);
  assert.equal(legend.querySelectorAll(".choro-swatch").length, 6);
  assert.ok(legend.querySelector(".shelter-pin"));
  assert.equal(legend.querySelectorAll(".swatch").length, 0, "no business dots on the whole city's map");
});

test("the city's map is labelled for its shading and described by the table that holds its figures", () => {
  const elements = new Map();
  globalThis.document.getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, h("p"));
    return elements.get(id);
  };
  renderAreaLabels(CITY_AREA, { word: SECTION_WORD });
  const map = elements.get("map");
  assert.match(map.getAttribute("aria-label"), /^Map of Shah Alam, Selangor: each section shaded/);
  assert.equal(map.getAttribute("aria-describedby"), "sections-caption");
  assert.equal(elements.get("map-lead").textContent,
    "Each section is shaded by the share of its 90 m squares with water in the model. Tap one to open it.");
  assert.equal(elements.get("sections-heading").textContent, "Compare the sections");
});

// ---------- a section with no businesses, and one the river model leaves dry ----------

test("a section with no businesses mapped says so, with the way to check a spot, not that a filter matched nothing", () => {
  const parts = { list: h("ol"), filter: h("input"), status: h("p"), next: h("div"), head: h("div") };
  const area = pageArea(CITY_AREA, SECTIONS[2]);
  createDirectory(parts, [], { area, onOpen() {}, onCheckPoint: () => {} });
  assert.equal(parts.status.textContent, "No businesses are mapped in Seksyen U1 yet. Our list comes from a public map.");
  assert.equal(parts.head.hidden, true);
  assert.equal(parts.next.hidden, false);
});

test("where floods are on record but the river model shows no water, the map says it shows river floods only", async () => {
  const { riverOnlyNote } = await import("../app/static/js/overview.js");
  const dry = { ...SECTIONS[2], counts: { ...SECTIONS[2].counts, businesses: 4 } };
  const page = pageArea({ ...CITY_AREA }, dry);
  assert.equal(riverOnlyNote(page, dry), "Floods are on record for Seksyen U1, but the model shows little or no river water at its businesses: it maps river floods only, not flash floods or blocked drains.");
  assert.equal(riverOnlyNote(pageArea(CITY_AREA, SECTIONS[1]), SECTIONS[1]), null, "wet in the model: nothing to explain");
  assert.equal(riverOnlyNote({ ...page, history: { ...CITY_AREA.history, floods: [] } }, dry), null, "no record: nothing disagrees");
  assert.equal(riverOnlyNote(CITY_AREA, null), null, "the whole city has its own map");
});
