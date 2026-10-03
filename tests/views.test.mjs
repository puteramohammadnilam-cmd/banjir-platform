// Run from 11_Platform_Draft:  node --test tests/views.test.mjs
// The DOM side of a point in the My business tab (card.js) and the Ask AI tab (chat.js), on the small fake DOM in
// tests/fake_dom.mjs. The words themselves are tested in tests/point.test.mjs; here: which parts show for a point, which
// stay away, and what the buttons call. A business is held to what it always showed.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createBusiness } from "../app/static/js/card.js";
import { createChat } from "../app/static/js/chat.js";
import { h } from "../app/static/js/dom.js";
import { useLang } from "../app/static/js/i18n.js";
import { NO_WATER_NOTE } from "../app/static/js/point.js";
import { installFakeDom } from "./fake_dom.mjs";
import { AREAS, HOME, LISTING, point, shop } from "./point_fixtures.mjs";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));   // let an awaited exchange finish
const DRY = { 10: null, 100: null, 500: null };

// ---------- My business ----------

/** The tab built the way main.js builds it. */
function mountCard(options = {}) {
  installFakeDom();
  const panel = document.createElement("section");
  const card = createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {}, ...options });
  return { panel, card };
}
const show = (card, place, change = {}) => card.render({ premise: place, rp: "100", photo: undefined, listing: undefined, ...change });
const factLabels = (panel) => panel.querySelectorAll(".fact-label").map((label) => label.textContent);
const head = (panel) => panel.querySelector("header");
const buttonNamed = (panel, text) => panel.querySelectorAll("button").find((button) => button.textContent === text);
const headButtons = (panel) => head(panel).querySelectorAll("button").map((button) => button.textContent);

test("a business shows its road, its Google Maps listing, its floor and the page's flood record", () => {
  const { panel, card } = mountCard();
  show(card, shop, { listing: LISTING });
  assert.deepEqual(factLabels(panel), ["Road access", "Google Maps", "Floor height", "Floods recorded here"]);
  assert.equal(head(panel).querySelector("h1").textContent, "A Shop");
  assert.deepEqual(headButtons(panel), ["See on map"]);
  assert.ok(!panel.textContent.includes(NO_WATER_NOTE));
});

test("a business of an area with no flood record shows no record fact", () => {
  const { panel, card } = mountCard({ area: { ...HOME, history: null } });
  show(card, shop);
  assert.deepEqual(factLabels(panel), ["Road access", "Floor height"]);
});

test("a point shows no road or Google Maps fact, even when handed a road and a listing, but keeps the floor photo and the record", () => {
  const { panel, card } = mountCard();
  show(card, point({ road: shop.road }), { listing: LISTING });
  assert.deepEqual(factLabels(panel), ["Floor height", "Floods recorded here"]);
});

test("a point's head carries its kicker, title, square, tags and the way to see it on the map", () => {
  const { panel, card } = mountCard();
  show(card, point());
  const words = head(panel);
  assert.equal(words.querySelector(".kicker").textContent, "A point you picked");
  assert.equal(words.querySelector("h1").textContent, "Point in Home Town, Some State");
  assert.equal(words.querySelector(".muted").textContent, "The 90 m flood square at 3.02998, 101.53667");
  assert.deepEqual(words.querySelectorAll(".tag").map((tag) => tag.textContent), ["90 m model square", "Not a mapped business"]);
  assert.deepEqual(headButtons(panel), ["See on map"], "no Move the pin until the page can move the pin");
});

test("'Move the pin' shows only where the page can move the pin, and is called with nothing", () => {
  const moves = [];
  const { panel, card } = mountCard({ onMovePin: (...args) => moves.push(args) });
  show(card, point());
  assert.deepEqual(headButtons(panel), ["Move the pin", "See on map"]);
  buttonNamed(panel, "Move the pin").click();
  assert.deepEqual(moves, [[]]);
  const business = mountCard({ onMovePin: () => assert.fail("a business has no pin to move") });
  show(business.card, shop);
  assert.equal(buttonNamed(business.panel, "Move the pin"), undefined);
});

test("a point's missing coordinates leave out the line about its square, and nothing else", () => {
  const { panel, card } = mountCard();
  show(card, point({ lat: undefined }));
  assert.equal(head(panel).querySelector(".muted"), null);
  assert.equal(head(panel).querySelector("h1").textContent, "Point in Home Town, Some State");
});

test("a point in another listed area names it, offers to open it, and leaves that area's record to its own page", () => {
  const opened = [];
  const { panel, card } = mountCard({ onOpenArea: (id) => opened.push(id) });
  show(card, point({ area_id: "far" }));
  assert.equal(head(panel).querySelector("h1").textContent, "Point in Far Town centre, Other State");
  assert.equal(head(panel).querySelector(".fact-note").textContent, "This point is in Far Town. Open Far Town");
  buttonNamed(panel, "Open Far Town").click();
  assert.deepEqual(opened, ["far"]);
  assert.deepEqual(factLabels(panel), ["Floor height"]);
});

test("without a way to open the other area only the sentence shows", () => {
  const { panel, card } = mountCard();
  show(card, point({ area_id: "far" }));
  assert.equal(head(panel).querySelector(".fact-note").textContent.trim(), "This point is in Far Town.");
  assert.equal(buttonNamed(panel, "Open Far Town"), undefined);
});

test("a point in no listed area is a point you picked: no offer, no record", () => {
  const { panel, card } = mountCard();
  show(card, point({ area_id: null }));
  assert.equal(head(panel).querySelector("h1").textContent, "Point you picked");
  assert.equal(head(panel).querySelector(".fact-note"), null);
  assert.deepEqual(factLabels(panel), ["Floor height"]);
});

test("a point shows the relief centre its area has, and a business keeps its own", () => {
  const shelter = { name: "A Hall", distance_m: 1806 };
  const inArea = mountCard();
  show(inArea.card, point({ shelter }));
  assert.deepEqual(factLabels(inArea.panel), ["Flood relief centre", "Floor height", "Floods recorded here"]);
  assert.ok(inArea.panel.textContent.includes("A Hall"));
  const business = mountCard();
  show(business.card, { ...shop, shelter });
  assert.equal(factLabels(business.panel)[1], "Flood relief centre");
});

test("a dry point says what the model does not show; a dry business, or a wet point, does not", () => {
  const dryPoint = mountCard();
  show(dryPoint.card, point({ depth_m: DRY }));
  assert.ok(dryPoint.panel.textContent.includes("No water") && dryPoint.panel.textContent.includes(NO_WATER_NOTE));
  const dryShop = mountCard();
  show(dryShop.card, { ...shop, depth_m: DRY });
  assert.ok(dryShop.panel.textContent.includes("No water") && !dryShop.panel.textContent.includes(NO_WATER_NOTE));
  const wetPoint = mountCard();
  show(wetPoint.card, point());
  assert.ok(!wetPoint.panel.textContent.includes(NO_WATER_NOTE));
});

test("the head is made again for a new place, so nothing of the old one is left", () => {
  const { panel, card } = mountCard({ onMovePin() {} });
  show(card, point());
  show(card, shop);
  assert.equal(head(panel).querySelector("h1").textContent, "A Shop");
  assert.deepEqual(headButtons(panel), ["See on map"]);
  show(card, point({ area_id: "far" }));
  assert.deepEqual(headButtons(panel), ["Move the pin", "See on map"]);
});

// ---------- Ask AI ----------

/** The Ask tab's parts as index.html has them, and a chat on them. `selected.ref` is the place a question is about. */
function mountChat(change = {}) {
  installFakeDom();
  const messages = h("ol");
  const chips = h("div");
  const input = h("input", { placeholder: "Tanya apa-apa pasal banjir di kedai ini" });
  const form = h("form", {}, input, h("button", { type: "submit" }, "Ask"));
  const news = h("button", { type: "button" });
  const section = h("section", {}, h("p", {}, "Gemini searches Google."), news);
  const selected = { ref: "node-1" };
  const chat = createChat({ messages, chips, form, input, news, getPlaceRef: () => selected.ref, areaId: "home", areaName: "Home Town", areas: AREAS, ...change });
  return { chat, chips, input, news, section, selected };
}
const chipTexts = (chips) => chips.children.map((chip) => chip.textContent);
const noteIn = (section) => section.children.at(-1);

/** Stand in for the server: answer every call well, and keep what was asked as [path, body]. */
function stubServer() {
  const asked = [];
  globalThis.fetch = async (path, init) => {
    asked.push([path, JSON.parse(init.body)]);
    return { json: async () => ({ success: true, data: { answer: "An answer.", sources: [], search_html: "" } }) };
  };
  return asked;
}

test("a business chat starts with its five chips and the news button for the page's area, with no note", () => {
  const { chips, news, section } = mountChat();
  assert.equal(chips.children.length, 5);
  assert.equal(news.textContent, "Latest flood news for Home Town");
  assert.equal(news.hidden, false);
  assert.equal(section.children.length, 2, "the note is made only when a place needs it");
});

test("a point in a listed area gets point chips, and its news is that area's", async () => {
  const asked = stubServer();
  const { chat, chips, news } = mountChat();
  chat.render(point({ area_id: "far" }));
  assert.ok(chipTexts(chips).includes("Which businesses in this area stay dry in a 100 year flood?"));
  assert.ok(!chipTexts(chips).includes("Is this shop still open?"));
  assert.equal(news.textContent, "Latest flood news for Far Town");
  news.click();
  await settle();
  assert.deepEqual(asked, [["/api/news", { area_id: "far" }]]);
});

test("a business's news asks for the page's area", async () => {
  const asked = stubServer();
  const { chat, news } = mountChat();
  chat.render(shop);
  news.click();
  await settle();
  assert.deepEqual(asked, [["/api/news", { area_id: "home" }]]);
});

test("a point in no listed area has a note in place of the news button, and the button asks nothing", async () => {
  const asked = stubServer();
  const { chat, chips, news, section } = mountChat();
  chat.render(point({ area_id: null }));
  assert.equal(chips.children.length, 4);
  assert.equal(news.hidden, true);
  assert.equal(noteIn(section).textContent, "Flood news is available for the listed areas.");
  assert.equal(noteIn(section).hidden, false);
  news.click();
  await settle();
  assert.deepEqual(asked, []);
});

test("going back to a business gives back its chips and its news button, and hides the note", () => {
  const { chat, chips, news, section } = mountChat();
  const business = chipTexts(chips);
  chat.render(point({ area_id: null }));
  chat.render(point({ area_id: "far" }));
  assert.equal(noteIn(section).hidden, true);
  chat.render(shop);
  assert.deepEqual(chipTexts(chips), business);
  assert.equal(news.hidden, false);
  assert.equal(news.textContent, "Latest flood news for Home Town");
});

test("the chips are rebuilt only when the kind of place changes, so a focused chip is not lost", () => {
  const { chat, chips } = mountChat();
  let rebuilt = 0;
  const original = chips.replaceChildren.bind(chips);
  chips.replaceChildren = (...nodes) => { rebuilt += 1; original(...nodes); };
  chat.render(shop);
  chat.render({ ...shop, id: "node-2" });
  assert.equal(rebuilt, 0, "another business");
  chat.render(point());
  chat.render(point({ id: "pt:3.03998,101.54750" }));
  assert.equal(rebuilt, 1, "another point in the same kind of place");
  chat.render(point({ area_id: null }));
  assert.equal(rebuilt, 2);
});

test("a question goes with the id of the place selected when it is asked, and the page's area", async () => {
  const asked = stubServer();
  const { chips, selected } = mountChat();
  selected.ref = "pt:3.02998,101.53667";
  chips.children[0].click();
  await settle();
  assert.deepEqual(asked, [["/api/ask", { question: chipTexts(chips)[0], place: "pt:3.02998,101.53667", area_id: "home", history: [] }]]);
});

test("the question box speaks of a location for a point, and gets its own words back for a business", () => {
  const { chat, input } = mountChat();
  const business = input.placeholder;
  assert.equal(business, "Ask anything about flooding at this shop");
  chat.render(point());
  assert.equal(input.placeholder, "Ask anything about flooding at this spot");
  chat.render(shop);
  assert.equal(input.placeholder, business);
});

test("in Bahasa Melayu the question box, the greeting and the chips are all in Bahasa Melayu", () => {
  useLang("ms");
  try {
    const { chat, chips, input } = mountChat();
    assert.equal(input.placeholder, "Tanya apa-apa tentang banjir di kedai ini");
    assert.ok(chipTexts(chips).includes("Kedai ni kena air tak kalau banjir besar?"));
    assert.ok(chipTexts(chips).every((chip) => !/\b(the|this|would|which)\b/i.test(chip)), chipTexts(chips).join(" | "));
    chat.render(point());
    assert.equal(input.placeholder, "Tanya apa-apa tentang banjir di lokasi ini");
  } finally {
    useLang("en");
  }
});

// ---------- a depth the model may overstate ----------

test("a very deep model depth carries a warning next to the number; a modest one does not", () => {
  const { panel, card } = mountCard();
  show(card, { ...shop, depth_m: { 10: 4.1, 100: 5.6, 500: 6.2 } });
  assert.match(panel.querySelector(".risk").textContent, /The model can run very deep beside rivers/);
  show(card, { ...shop, id: "node-2", depth_m: { 10: 0.4, 100: 1.2, 500: 1.9 } });
  assert.doesNotMatch(panel.querySelector(".risk").textContent, /run very deep/);
  show(card, point({ depth_m: { 10: 3.2, 100: 3.5, 500: 4 } }));
  assert.match(panel.querySelector(".risk").textContent, /The model can run very deep beside rivers/);
});
