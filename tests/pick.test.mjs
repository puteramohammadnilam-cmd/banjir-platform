// Run from 11_Platform_Draft:  node --test tests/pick.test.mjs
// Picking the place to show (pick.js), on the small fake DOM in tests/fake_dom.mjs: nobody is handed a stranger's shop
// on a first visit, a business someone picked is there again on their next, a link wins over that memory, both search
// boxes open a business by name, and My business, Flood cost and the compare card cope with nothing picked.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createBusiness } from "../app/static/js/card.js";
import { createCompareCard } from "../app/static/js/compare.js";
import { createCost } from "../app/static/js/cost.js";
import {
  DEFAULT_RP, emptyState, finderEntries, initialState, rememberPlace, rememberedPlace, sectionFinder, wireFinder,
} from "../app/static/js/pick.js";
import { ALIASES, INDEX, SECTIONS, SECTION_WORD } from "./fixtures/city_data.mjs";
import { installFakeDom } from "./fake_dom.mjs";
import { AREAS, HOME, point, shop } from "./point_fixtures.mjs";

const STORE_KEY = "banjir-check-place";
const other = { ...shop, id: "node-2", name: "B Shop" };
const START = { area: HOME, premises: [shop, other], status: { maps_ready: false } };
const NO_LINK = { tab: null, rp: null };

/** A localStorage that keeps what is set, as a browser's does. */
function fakeStorage(initial = {}) {
  const items = new Map(Object.entries(initial));
  return { getItem: (key) => items.get(key) ?? null, setItem: (key, value) => items.set(key, String(value)), items };
}

beforeEach(() => {
  installFakeDom();
  globalThis.localStorage = fakeStorage();
});

const remembered = (picks) => { globalThis.localStorage = fakeStorage({ [STORE_KEY]: JSON.stringify(picks) }); };

// ---------- the first state ----------

test("a first visit with no link picks nothing, and opens on the Area overview", () => {
  const state = initialState(NO_LINK, START, null);
  assert.equal(state.placeKey, null);
  assert.equal(state.tab, "overview");
  assert.equal(state.rp, DEFAULT_RP);
  assert.equal(DEFAULT_RP, "50", "the biggest flood size shown");
  assert.deepEqual(state.points, {});
  assert.deepEqual(state.squares, {});
});

test("the business last picked in this area is picked again", () => {
  remembered({ home: other.id, far: "node-9" });
  assert.equal(initialState(NO_LINK, START, null).placeKey, other.id);
});

test("a remembered business the area no longer lists, or one of another area, is not picked", () => {
  remembered({ home: "node-gone" });
  assert.equal(initialState(NO_LINK, START, null).placeKey, null);
  remembered({ far: shop.id });
  assert.equal(initialState(NO_LINK, START, null).placeKey, null);
});

test("a link wins over the memory, a point's included, and opens on My business", () => {
  remembered({ home: other.id });
  const byBusiness = initialState(NO_LINK, START, { place: shop, squares: null });
  assert.equal(byBusiness.placeKey, shop.id);
  assert.equal(byBusiness.tab, "business");
  const spot = point();
  const squares = { blocks: [], cells: [] };
  const byPoint = initialState(NO_LINK, START, { place: spot, squares });
  assert.equal(byPoint.placeKey, spot.id);
  assert.deepEqual(byPoint.points, { [spot.id]: spot });
  assert.deepEqual(byPoint.squares, { [spot.id]: squares });
});

test("storage that is missing, throws or holds rubbish reads as nothing remembered", () => {
  globalThis.localStorage = undefined;
  assert.equal(rememberedPlace("home", START.premises), null);
  globalThis.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(rememberedPlace("home", START.premises), null);
  assert.doesNotThrow(() => rememberPlace("home", shop.id));
  for (const rubbish of ["not json", "[1,2]", "null", "7"]) {
    globalThis.localStorage = fakeStorage({ [STORE_KEY]: rubbish });
    assert.equal(rememberedPlace("home", START.premises), null, rubbish);
  }
});

test("remembering a pick keeps the other areas' picks", () => {
  remembered({ far: "node-9" });
  rememberPlace("home", shop.id);
  assert.deepEqual(JSON.parse(globalThis.localStorage.items.get(STORE_KEY)), { far: "node-9", home: shop.id });
  assert.equal(rememberedPlace("home", START.premises), shop.id);
});

// ---------- the finder ----------

function mountFinder(premises = START.premises) {
  const datalist = document.createElement("datalist");
  const pair = () => [document.createElement("form"), document.createElement("input")];
  const [header, hero] = [pair(), pair()];
  const opened = [];
  const shown = [];
  wireFinder({ datalist, forms: [header, hero] }, premises, (id) => opened.push(id), (text) => shown.push(text));
  return { datalist, header, hero, opened, shown };
}

/** A pick from the browser's suggestion list: an input event with no inputType (Chrome) or "insertReplacementText". */
const type = ([, input], text, inputType = undefined) => { input.value = text; input.dispatch("input", { inputType }); };
/** Typing, key by key: each key is an input event of its own, with inputType "insertText". */
const typeKeys = ([, input], text) => {
  for (let end = 1; end <= text.length; end += 1) { input.value = text.slice(0, end); input.dispatch("input", { inputType: "insertText" }); }
};
const submit = ([form, input], text) => { input.value = text; form.dispatch("submit"); };

test("one suggestion list, by name, serves both search boxes", () => {
  const { datalist } = mountFinder();
  assert.deepEqual(datalist.children.map((option) => option.getAttribute("value")), [...finderEntries(START.premises).keys()]);
  assert.deepEqual([...finderEntries(START.premises).values()], [shop.id, other.id]);
});

test("picking a suggestion in either box opens its business and clears the box", () => {
  const { header, hero, opened } = mountFinder();
  const [shopText, otherText] = finderEntries(START.premises).keys();
  type(hero, otherText);
  type(header, shopText);
  assert.deepEqual(opened, [other.id, shop.id]);
  assert.equal(hero[1].value, "");
  assert.equal(header[1].value, "");
});

test("Enter in either box opens the one business that matches, and a suggestion's text opens its own", () => {
  const { header, hero, opened, shown } = mountFinder();
  submit(hero, "  b sho ");
  submit(header, "a shop");
  submit(hero, [...finderEntries(START.premises).keys()][1]);
  assert.deepEqual(opened, [other.id, shop.id, other.id]);
  assert.deepEqual(shown, []);
  assert.equal(hero[1].value, "", "an opened business clears the box");
});

test("Enter on a name several businesses share opens none of them and hands the text over, to show them all", () => {
  const dobi = (id, name) => ({ ...shop, id, name });
  const premises = [dobi("d-1", "DOBI DHOLPIN"), dobi("d-2", "Dobi DIY Selesa"), dobi("d-3", "Dobi Queen")];
  const { header, hero, opened, shown } = mountFinder(premises);
  submit(hero, " dobi ");
  submit(header, "DOBI D");
  assert.deepEqual(opened, []);
  assert.deepEqual(shown, ["dobi", "DOBI D"], "the text as typed, trimmed");
  assert.equal(hero[1].value, " dobi ", "the box keeps what was typed");
  submit(hero, "dobi queen");
  assert.deepEqual(opened, ["d-3"]);
});

test("Enter on a whole name opens that business, though a longer name holds it too", () => {
  const { hero, opened, shown } = mountFinder([shop, { ...shop, id: "node-3", name: "A Shop Two" }]);
  submit(hero, "a shop");
  assert.deepEqual(opened, [shop.id]);
  submit(hero, "a sho");
  assert.deepEqual(shown, ["a sho"]);
});

test("Enter on a name that matches nothing hands it over, and an empty box opens nothing", () => {
  const { header, hero, opened, shown } = mountFinder();
  submit(hero, "nothing like it");
  submit(header, "   ");
  assert.deepEqual(opened, []);
  assert.deepEqual(shown, ["nothing like it"]);
});

// ---------- a city split into sections: its index, its sections and the old areas' names ----------

const CITY_FINDER = sectionFinder(SECTIONS, ALIASES, SECTION_WORD, "Shah Alam");

function mountCityFinder({ premises = INDEX, ready = null } = {}) {
  const datalist = document.createElement("datalist");
  const forms = [[document.createElement("form"), document.createElement("input")]];
  const opened = [];
  const shown = [];
  const finder = wireFinder({ datalist, forms }, premises, (target) => opened.push(target), (text) => shown.push(text),
    { extra: CITY_FINDER.entries, synonyms: CITY_FINDER.synonyms, ready });
  return { datalist, form: forms[0], opened, shown, finder };
}

test("the sections and the old areas' names are suggestions too, after the businesses", () => {
  const { datalist } = mountCityFinder();
  const values = datalist.children.map((option) => option.getAttribute("value"));
  assert.equal(values.length, INDEX.length + SECTIONS.length + 2);
  assert.deepEqual(values.slice(INDEX.length), ["Seksyen 24 · Shah Alam", "Seksyen 25 · Shah Alam", "Seksyen U1 · Shah Alam",
    "Taman Sri Muda · Seksyen 25", "Taman Seri Muda · Seksyen 25"]);
});

// A section's name is the start of others' ("Seksyen 2" of "Seksyen 25", "Seksyen U1" of "Seksyen U10"): what is typed
// must never open a page on its own (WCAG 3.2.2). Only a pick from the list, or Enter, does.
const PREFIXED = [{ id: "seksyen-2", name: "Seksyen 2" }, { id: "seksyen-25", name: "Seksyen 25" }];

function mountPrefixed() {
  const named = sectionFinder(PREFIXED, [], SECTION_WORD, "Shah Alam");
  const datalist = document.createElement("datalist");
  const form = [document.createElement("form"), document.createElement("input")];
  const opened = [];
  wireFinder({ datalist, forms: [form] }, [], (target) => opened.push(target), () => {}, { extra: named.entries, synonyms: named.synonyms });
  return { form, opened };
}

test("typing a section's name, or a suggestion's whole text, opens nothing until Enter or a pick", () => {
  const { form, opened } = mountPrefixed();
  typeKeys(form, "Seksyen 2");
  typeKeys(form, "Seksyen 25");
  typeKeys(form, "Seksyen 2 · Shah Alam");
  type(form, "Seksyen 2 · Shah Alam", "insertFromPaste");
  assert.deepEqual(opened, [], "nothing opens while typing or pasting");
  submit(form, "Seksyen 25");
  assert.deepEqual(opened, [{ section: "seksyen-25" }]);
  submit(form, "Seksyen 2");
  assert.deepEqual(opened, [{ section: "seksyen-25" }, { section: "seksyen-2" }]);
});

test("a pick from the suggestion list opens at once, as Chrome and as Firefox and Safari report it", () => {
  const { form, opened } = mountPrefixed();
  type(form, "Seksyen 2 · Shah Alam");
  type(form, "Seksyen 25 · Shah Alam", "insertReplacementText");
  assert.deepEqual(opened, [{ section: "seksyen-2" }, { section: "seksyen-25" }]);
  assert.equal(form[1].value, "", "an opened section clears the box");
});

test("an old area's name opens its section, typed in full or picked from the list", () => {
  const { form, opened } = mountCityFinder();
  submit(form, "Taman Sri Muda");
  type(form, "Taman Seri Muda · Seksyen 25");
  submit(form, "taman sri muda");
  assert.deepEqual(opened, [{ section: "seksyen-25" }, { section: "seksyen-25" }, { section: "seksyen-25" }]);
});

test("a section opens by its name, its id, or the word for it in either language", () => {
  const { form, opened } = mountCityFinder();
  for (const typed of ["Seksyen 25", "SEKSYEN 25", "section 25", "Section U1", "seksyen-u1"]) submit(form, typed);
  assert.deepEqual(opened, [{ section: "seksyen-25" }, { section: "seksyen-25" }, { section: "seksyen-25" }, { section: "seksyen-u1" }, { section: "seksyen-u1" }]);
});

test("a business anywhere in the city opens by its name, and one the name could mean several of is shown", () => {
  const { form, opened, shown } = mountCityFinder();
  submit(form, "kedai u satu");
  submit(form, "dobi");
  assert.deepEqual(opened, ["node-u1"]);
  assert.deepEqual(shown, ["dobi"]);
});

test("more places can be handed in later, as the city index arrives on a section's page", () => {
  const { datalist, form, opened, finder } = mountCityFinder({ premises: INDEX.slice(1, 3) });
  submit(form, "kedai u satu");
  assert.deepEqual(opened, []);
  finder.setPlaces(INDEX);
  assert.equal(datalist.children.length, INDEX.length + SECTIONS.length + 2);
  submit(form, "kedai u satu");
  assert.deepEqual(opened, ["node-u1"]);
});

test("Enter waits for what `ready` is still loading, then matches against it", async () => {
  let finder = null;
  const ready = () => Promise.resolve().then(() => finder.setPlaces(INDEX));
  const mounted = mountCityFinder({ premises: [], ready });
  finder = mounted.finder;
  submit(mounted.form, "kedai u satu");
  assert.deepEqual(mounted.opened, [], "not before the index is in");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(mounted.opened, ["node-u1"]);
});

// ---------- nothing picked ----------

const buttonTexts = (node) => node.querySelectorAll("button").map((button) => button.textContent);

test("the empty state says what to do, with both ways to do it, and the second only when points can be checked", () => {
  const calls = [];
  const node = emptyState({ kicker: "My business", onFind: () => calls.push("find"), onCheckPoint: (button) => calls.push(button) });
  assert.equal(node.querySelector("h1").textContent, "Pick your shop first");
  assert.ok(node.textContent.includes("Search by name, or tap a dot on the map."));
  assert.deepEqual(buttonTexts(node), ["Find your shop", "Check a point"]);
  const [find, check] = node.querySelectorAll("button");
  find.click();
  check.dispatch("click", { currentTarget: check });
  assert.deepEqual(calls, ["find", check]);
  assert.deepEqual(buttonTexts(emptyState({ kicker: "x", onFind() {} })), ["Find your shop"]);
});

function mountBusiness(options = {}) {
  const panel = document.createElement("section");
  const card = createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {}, ...options });
  const show = (premise) => card.render({ premise, rp: "20", photo: undefined, listing: undefined });
  return { panel, show };
}

test("My business with nothing picked shows the empty state as its only heading, and the business once one is", () => {
  const { panel, show } = mountBusiness({ onCheckPoint() {} });
  show(undefined);
  assert.deepEqual(panel.querySelectorAll("h1").map((heading) => heading.textContent), ["Pick your shop first"]);
  assert.equal(panel.querySelector(".biz-grid").hidden, true);
  show(shop);
  assert.deepEqual(panel.querySelectorAll("h1").map((heading) => heading.textContent), ["A Shop"]);
  assert.equal(panel.querySelector(".biz-grid").hidden, false);
  assert.equal(panel.querySelector(".pick-empty"), null);
});

test("Flood cost with nothing picked shows the empty state first, and its form is off", () => {
  const panel = document.createElement("section");
  const cost = createCost(panel, { onEstimate() {}, onFind() {}, onCheckPoint: null });
  assert.doesNotThrow(() => cost.render(undefined, null, undefined, undefined, "20"));
  assert.equal(panel.querySelector("h1").textContent, "Pick your shop first");
  assert.deepEqual(buttonTexts(panel.querySelector(".pick-empty")), ["Find your shop"]);
  assert.ok(panel.querySelector("form").parent.hidden);
});

test("the compare card draws nothing with no place on show", () => {
  const card = createCompareCard({ onAdd() {}, onRemove() {}, onOpen() {} });
  assert.doesNotThrow(() => card.render({ current: undefined, compared: [] }));
  assert.equal(card.node.children.length, 0);
  card.render({ current: shop, compared: [] });
  assert.ok(card.node.children.length > 0);
});
