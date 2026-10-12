// Run from 11_Platform_Draft:  node --test tests/views.test.mjs
// The DOM side of a point in the My business tab (card.js) and the Ask AI chat (chat.js), on the small fake DOM in
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
const DRY = { 10: null, 20: null, 50: null };

// ---------- My business ----------
// (a point in a city's section: see the end of this file)

/** The tab built the way main.js builds it. */
function mountCard(options = {}) {
  installFakeDom();
  const panel = document.createElement("section");
  const card = createBusiness(panel, { area: HOME, areas: AREAS, onPhoto() {}, onPick() {}, goto() {}, showOnMap() {}, ...options });
  return { panel, card };
}
const show = (card, place, change = {}) => card.render({ premise: place, rp: "20", photo: undefined, listing: undefined, ...change });
const factLabels = (panel) => panel.querySelectorAll(".fact-label").map((label) => label.textContent);
const head = (panel) => panel.querySelector("header");
const buttonNamed = (panel, text) => panel.querySelectorAll("button").find((button) => button.textContent === text);
const headButtons = (panel) => head(panel).querySelectorAll("button").map((button) => button.textContent);

test("a business with a 3D picture links to its section's at the size on show, and one without has no link", () => {
  const { panel, card } = mountCard();
  const in3d = () => head(panel).querySelectorAll("a").filter((link) => link.textContent === "See in 3D");
  const baked = { ...shop, section: "s-7", has_3d: true };
  show(card, baked);
  assert.equal(in3d().length, 1);
  assert.equal(in3d()[0].getAttribute("href"), "3d.html?area=home&section=s-7&place=node-1&rp=20");
  assert.deepEqual(headButtons(panel), ["See on map"]);
  const link = in3d()[0];
  show(card, baked, { rp: "50" });   // another size: the same head, its link moved on
  assert.equal(in3d()[0], link);
  assert.equal(link.getAttribute("href"), "3d.html?area=home&section=s-7&place=node-1&rp=50");
  show(card, shop);
  assert.equal(in3d().length, 0);
});

test("a business with no 3D view says which areas have one, and only then", () => {
  const ready = [AREAS[0], { ...AREAS[1], has_3d: true }];
  const note = (panel) => head(panel).querySelectorAll("p").map((p) => p.textContent).find((text) => text.startsWith("3D view"));
  let { panel, card } = mountCard({ areas: ready });
  show(card, shop);
  assert.equal(note(panel), "3D view: only for shops in Far Town, for now.");
  ({ panel, card } = mountCard({ areas: ready }));
  show(card, { ...shop, has_3d: true });
  assert.equal(note(panel), undefined, "a shop with the view needs no note");
  ({ panel, card } = mountCard());
  show(card, shop);
  assert.equal(note(panel), undefined, "no area has the view yet: nothing to point to");
});

test("a business shows its road, its Google Maps listing, its floor and the page's flood record", () => {
  const { panel, card } = mountCard();
  show(card, shop, { listing: LISTING });
  assert.deepEqual(factLabels(panel), ["Height of the ground", "Floods recorded here", "Road access", "Floor height", "Google Maps"]);
  assert.deepEqual(panel.querySelectorAll(".fact-group-heading").map((heading) => heading.textContent),
    ["Water at this place", "Getting out", "Make it more exact"]);
  assert.equal(head(panel).querySelector("h1").textContent, "A Shop");
  assert.deepEqual(headButtons(panel), ["See on map"]);
  assert.ok(!panel.textContent.includes(NO_WATER_NOTE));
});

test("a Google listing with another name says it may be another shop; one with the same name just names it", () => {
  const { panel, card } = mountCard();
  show(card, shop, { listing: { configured: true, place: { ...LISTING.place, name: "B Shop", same_name: false } } });
  assert.ok(panel.textContent.includes('The nearest listing has another name, "B Shop", so it may be another shop.'));
  show(card, shop, { listing: { configured: true, place: { ...LISTING.place, same_name: true } } });
  assert.ok(panel.textContent.includes('As "A Shop".') && !panel.textContent.includes("another shop"));
});

test("the bigger-flood example is the page's area's own: a point in another area gets the plain note", () => {
  const { panel, card } = mountCard({ area: { ...HOME, bigger_flood_example: "2021-12" } });
  const note = () => panel.querySelector(".scenario-note").textContent;
  show(card, shop);
  assert.match(note(), /such as December 2021/);
  show(card, point({ area_id: "home" }));
  assert.match(note(), /such as December 2021/);
  show(card, point({ area_id: "far" }));
  assert.equal(note(), "Floods bigger than 1 in 50 years are not shown.");
});

test("a business of an area with no flood record shows no record fact", () => {
  const { panel, card } = mountCard({ area: { ...HOME, history: null } });
  show(card, shop);
  assert.deepEqual(factLabels(panel), ["Height of the ground", "Road access", "Floor height"]);
});

test("a point shows no road or Google Maps fact, even when handed a road and a listing, but keeps the floor photo and the record", () => {
  const { panel, card } = mountCard();
  show(card, point({ road: shop.road }), { listing: LISTING });
  assert.deepEqual(factLabels(panel), ["Height of the ground", "Floods recorded here", "River forecast", "Floor height"]);
  assert.ok(!panel.textContent.includes("Getting out"), "a group with nothing in it has no heading");
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
  assert.deepEqual(factLabels(panel), ["Height of the ground", "River forecast", "Floor height"]);
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
  assert.deepEqual(factLabels(panel), ["Height of the ground", "River forecast", "Floor height"]);
});

test("a point shows the relief centre its area has, and a business keeps its own", () => {
  const shelter = { name: "A Hall", distance_m: 1806 };
  const inArea = mountCard();
  show(inArea.card, point({ shelter }));
  assert.deepEqual(factLabels(inArea.panel), ["Height of the ground", "Floods recorded here", "River forecast", "Flood relief centre", "Floor height"]);
  assert.ok(inArea.panel.textContent.includes("A Hall"));
  assert.ok(inArea.panel.textContent.includes("1.8 km away"), "the distance leads, as a person says it");
  const business = mountCard();
  show(business.card, { ...shop, shelter });
  assert.equal(factLabels(business.panel)[3], "Flood relief centre");
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

/** The chat parts as index.html has them, and a chat on them. `selected.ref` is the place a question is about. */
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
  chat.render(shop);   // the page renders the chat with its place straight away
  return { chat, chips, input, news, section, selected, messages, form };
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

test("an answer is shown from its first line: the list scrolls to its top, not to the bottom", async () => {
  stubServer();
  const { chips, messages } = mountChat();
  // the list 100 px down the screen, its messages 50 px apart; the question and the wait note leave it at the bottom
  // (0 in the fake), then the answer, the third message, sits 100 px below the list's top
  messages.getBoundingClientRect = () => ({ top: 100 });
  const proto = Object.getPrototypeOf(messages);
  proto.getBoundingClientRect = function () { return { top: 100 + 50 * this.parent.children.indexOf(this) }; };
  try {
    chips.children[0].click();
    await settle();
    assert.equal(messages.children.at(-1).textContent, "An answer.");
    assert.equal(messages.scrollTop, 100 - 8);   // its top edge, less the 8 px of room above it
  } finally {
    delete proto.getBoundingClientRect;
  }
});

test("a business chat starts with its five chips and the news button for the page's area, with no note", () => {
  const { chips, news, section } = mountChat();
  assert.equal(chips.children.length, 5);
  assert.equal(news.textContent, "Latest flood news for Home Town");
  assert.equal(news.hidden, false);
  assert.equal(section.children.length, 2, "the note is made only when a place needs it");
});

test("with nothing picked yet, the chat asks about the area and the tool, not a shop", () => {
  const { chat, chips, input, news } = mountChat();
  chat.render(undefined);
  assert.deepEqual(chipTexts(chips), ["Which businesses stay dry in a 1 in 50 years flood?", "Is heavy rain due today?",
    "How does this tool work out what a flood could cost?"]);
  assert.equal(input.placeholder, "Ask about floods here, or about this tool");
  assert.equal(news.textContent, "Latest flood news for Home Town");
});

test("the greeting names the shop, the point, or the area when nothing is picked", () => {
  const { chat, messages } = mountChat();
  const greeting = () => messages.children[0].textContent;
  assert.match(greeting(), /at A Shop, how this tool works/);
  chat.render(point());
  assert.match(greeting(), /at this point, how this tool works/);
  chat.render(undefined);
  assert.match(greeting(), /in Home Town, how this tool works, or getting your shop ready\. Pick a shop on the map/);
});

test("without the AI key every control is off and nothing invites a question", () => {
  const { chips, input, news, messages, form } = mountChat({ isReady: false });
  assert.equal(input.disabled, true);
  assert.equal(form.querySelector("button").disabled, true);
  assert.equal(news.disabled, true);
  assert.ok(chips.children.every((chip) => chip.disabled), "every chip is off");
  assert.equal(messages.children.length, 0, "no greeting asking for a question");
});

test("without the Maps key the rain and opening-hours questions are left out", () => {
  const { chat, chips } = mountChat({ hasMaps: false });
  assert.ok(!chipTexts(chips).some((chip) => /rain|still open/i.test(chip)), chipTexts(chips).join(" | "));
  chat.render(undefined);
  assert.deepEqual(chipTexts(chips), ["Which businesses stay dry in a 1 in 50 years flood?", "How does this tool work out what a flood could cost?"]);
});

test("a point in a listed area gets point chips, and its news is that area's", async () => {
  const asked = stubServer();
  const { chat, chips, news } = mountChat();
  chat.render(point({ area_id: "far" }));
  assert.ok(chipTexts(chips).includes("Which businesses in this area stay dry in a 1 in 50 years flood?"));
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
  assert.equal(business, "Ask about this shop, or about this tool");
  chat.render(point());
  assert.equal(input.placeholder, "Ask about this spot, or about this tool");
  chat.render(shop);
  assert.equal(input.placeholder, business);
});

test("in Bahasa Melayu the question box, the greeting and the chips are all in Bahasa Melayu", () => {
  useLang("ms");
  try {
    const { chat, chips, input } = mountChat();
    assert.equal(input.placeholder, "Tanya tentang kedai ini atau alat ini");
    assert.ok(chipTexts(chips).includes("Kedai ni kena air tak kalau banjir besar?"));
    assert.ok(chipTexts(chips).every((chip) => !/\b(the|this|would|which)\b/i.test(chip)), chipTexts(chips).join(" | "));
    chat.render(point());
    assert.equal(input.placeholder, "Tanya tentang lokasi ini atau alat ini");
  } finally {
    useLang("en");
  }
});

// ---------- a depth the model may overstate ----------

test("a very deep model depth carries a warning next to the number; a modest one does not", () => {
  const { panel, card } = mountCard();
  show(card, { ...shop, depth_m: { 10: 4.1, 20: 5.6, 50: 6.2 } });
  assert.match(panel.querySelector(".risk").textContent, /The model can run very deep beside rivers/);
  show(card, { ...shop, id: "node-2", depth_m: { 10: 0.4, 20: 1.2, 50: 1.9 } });
  assert.doesNotMatch(panel.querySelector(".risk").textContent, /run very deep/);
  show(card, point({ depth_m: { 10: 3.2, 20: 3.5, 50: 4 } }));
  assert.match(panel.querySelector(".risk").textContent, /The model can run very deep beside rivers/);
});

// ---------- AI and Google Maps off (the demo build) ----------

const shortcuts = (panel) => panel.querySelectorAll(".next-step").map((step) => step.textContent);

test("the shop-front photo button is off, with a line, when the AI is switched off, and on otherwise", () => {
  const off = mountCard({ isReady: false });
  show(off.card, shop);
  const label = off.panel.querySelector(".photo-button");
  assert.equal(label.getAttribute("aria-disabled"), "true");
  assert.equal(label.querySelector("input").disabled, true);
  assert.match(off.panel.textContent, /Needs the AI assistant, which is switched off in this test build\./);
  const on = mountCard();
  show(on.card, shop);
  assert.equal(on.panel.querySelector(".photo-button").querySelector("input").disabled, false);
  assert.doesNotMatch(on.panel.textContent, /switched off/);
});

test("the two shortcut cards say what the Flood cost tab now answers, and what Ask AI can read", () => {
  const full = mountCard();
  show(full.card, shop);
  assert.deepEqual(shortcuts(full.panel), [
    "What would a flood cost you?Loss per flood and per year, and the chance in the next 10 years",
    "Ask in Bahasa Melayu or EnglishGemini, with Google Weather and Google Maps"]);
  const noMaps = mountCard({ hasMaps: false });
  show(noMaps.card, shop);
  assert.match(shortcuts(noMaps.panel)[1], /Gemini, with this tool's flood data$/);
  const off = mountCard({ isReady: false, hasMaps: false });
  show(off.card, shop);
  assert.match(shortcuts(off.panel)[1], /The assistant is switched off in this test build$/);
  assert.ok(buttonNamed(off.panel, shortcuts(off.panel)[1]), "still a way to the chat");
});

test("the Ask AI shortcut opens the floating chat, with the shortcut itself as the opener, and goes to no tab", () => {
  const opened = [];
  const went = [];
  const { panel, card } = mountCard({ onAsk: (opener) => opened.push(opener), goto: (tab) => went.push(tab) });
  show(card, shop);
  const ask = panel.querySelectorAll(".next-step")[1];
  ask.dispatch("click", { currentTarget: ask });
  assert.deepEqual(opened, [ask]);
  assert.deepEqual(went, []);
  panel.querySelectorAll(".next-step")[0].dispatch("click");
  assert.deepEqual(went, ["cost"]);
});

// ---------- a point in a city split into sections ----------

test("a point's card in the whole city offers its section as a button, which calls onOpenSection and nothing else", () => {
  const opened = [];
  const city = { id: "shah-alam", name: "Shah Alam", display_name: "Shah Alam, Selangor", history: null };
  const { panel, card } = mountCard({ area: city, areas: [city], onOpenSection: (id) => opened.push(["section", id]), onOpenArea: (id) => opened.push(["area", id]) });
  show(card, point({ area_id: "shah-alam", section: { id: "seksyen-25", name: "Seksyen 25" } }));
  assert.equal(head(panel).querySelector("h1").textContent, "Point in Seksyen 25, Shah Alam");
  buttonNamed(panel, "Open Seksyen 25").click();
  assert.deepEqual(opened, [["section", "seksyen-25"]]);
});

test("on a section's page every question and the news name the section; a plain area's name none, as before", async () => {
  const asked = stubServer();
  const { chat, news, form, input } = mountChat({ areaId: "shah-alam", sectionId: "seksyen-25", areas: [{ id: "shah-alam", name: "Seksyen 25" }] });
  input.value = "Will it flood?";
  form.dispatch("submit");
  await settle();
  news.click();
  await settle();
  chat.render(point({ area_id: "shah-alam" }));
  assert.deepEqual(asked.map(([path, body]) => [path, body.area_id, body.section_id]),
    [["/api/ask", "shah-alam", "seksyen-25"], ["/api/news", "shah-alam", "seksyen-25"]]);
  const plain = stubServer();
  const other = mountChat();
  other.input.value = "Will it flood?";
  other.form.dispatch("submit");
  await settle();
  other.news.click();
  await settle();
  assert.ok(plain.every(([, body]) => !("section_id" in body)), JSON.stringify(plain));
});
