// Run from 11_Platform_Draft:  node --test tests/pin_flow.test.mjs
// The flow behind "Check any point" (pin.js) under node:test: aim mode, the check and the location. The browser's parts
// are stand-ins (tests/pin_page.mjs): the DOM of pin_dom.mjs, a fake map, a fake server behind `fetch` and a fake
// geolocation. What is sent is what the privacy words of the dialog promise (one request, POST /api/point), and what is
// late is dropped. The pin, and the flood squares that come in the same answer, are in tests/pin_squares.test.mjs.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { COVERAGE, E100, PanelElement } from "./pin_dom.mjs";
import {
  BLOCKS, FIX_OPTIONS, KL, KUAH, KUCHING, NORTH_OF_KL, SQUARES, SRI_MUDA, STRAIT,
  aim, choose, covering, deferred, flush, placeAt, pressLocate, serve, setup,
} from "./pin_page.mjs";
import { ApiError } from "../app/static/js/api.js";
import { WORDS } from "../app/static/js/pin-words.js";
import { snapToGrid } from "../app/static/js/place.js";

beforeEach(() => {
  serve(covering);
});

// ---------- aim mode ----------

test("starting puts the cross up, shows the panel, listens for keys and moves focus to the map, once", async () => {
  const page = setup();
  assert.equal(page.panel.hidden, true);
  await aim(page);
  assert.equal(page.panel.hidden, false);
  assert.deepEqual(page.map.calls.filter(([name]) => name === "enterAim"), [["enterAim", "aim-help"]]);
  assert.equal(page.map.calls.at(-1)[0], "focusMap");
  assert.equal(page.document.listenerCount("keydown"), 1);
  assert.equal(page.status(), "");
  assert.equal(page.check.disabled, false);
  page.pin.start({});
  assert.equal(page.map.count("enterAim"), 1, "a second start only focuses the map");
  assert.equal(page.document.listenerCount("keydown"), 1);
});

test("starting at a Place, as 'Move the pin' does, puts the cross on it at street level", async () => {
  const page = setup();
  const place = placeAt(...KL);
  await aim(page, { at: place });
  assert.deepEqual(page.map.calls.find(([name]) => name === "aimAt"), ["aimAt", place.lat, place.lon, 17]);
});

test("the map is brought into view when the page is scrolled away from it", async () => {
  const page = setup();
  await aim(page);
  assert.equal(page.anchor.scrolledIntoView, 0, "it is in view: left alone");
  page.pin.close();
  page.anchor.rect = { top: 10, bottom: 410, height: 400 };
  await aim(page);
  assert.equal(page.anchor.scrolledIntoView, 1, "under the tab bar: scrolled");
  page.pin.close();
  page.anchor.rect = { top: 100, bottom: 500, height: 400 };
  page.panel.rect = { top: 520, bottom: 900, height: 380 };
  await aim(page);
  assert.equal(page.anchor.scrolledIntoView, 2, "the panel's last button is below the screen: scrolled");
  page.pin.close();
  page.panel.rect = { top: 280, bottom: 560, height: 280 };   // a sheet that sticks over the middle of the map
  await aim(page);
  assert.equal(page.anchor.scrolledIntoView, 3, "the cross would be under the sheet: scrolled");
});

test("a panel that floats over the map's corner scrolls the page only when the map is off the screen", async () => {
  const page = setup();
  globalThis.getComputedStyle = (node) => ({ position: node === page.panel ? "absolute" : "static" });
  try {
    page.anchor.rect = { top: 300, bottom: 760, height: 460 };
    page.panel.rect = { top: 310, bottom: 560, height: 250 };   // over the map's top right, level with the cross
    await aim(page);
    assert.equal(page.anchor.scrolledIntoView, 0, "the map is on the screen: left alone");
    page.pin.close();
    page.anchor.rect = { top: 500, bottom: 960, height: 460 };
    await aim(page);
    assert.equal(page.anchor.scrolledIntoView, 1, "its foot is below the screen: scrolled");
  } finally {
    delete globalThis.getComputedStyle;
  }
});

test("the verdict follows the cross: each place that cannot be checked says why and turns the button off", async () => {
  const page = setup();
  await aim(page);
  const verdicts = [[KUCHING, "Sabah and Sarawak are not in this build yet."], [KUAH, "Langkawi is not covered yet."],
    [STRAIT, "This spot is outside the flood model files in this build."]];
  for (const [spot, words] of verdicts) {
    page.map.moveTo(...spot);
    assert.equal(page.status(), words);
    assert.equal(page.check.disabled, true, words);
  }
  page.map.moveTo(...KL);
  assert.equal(page.status(), "");
  assert.equal(page.check.disabled, false);
});

test("a move of the map clears what was said about the old spot", async () => {
  const page = setup();
  await aim(page);
  serve(() => ({ failure: WORDS.readFailed }));
  page.check.click();
  await flush();
  assert.equal(page.alert(), WORDS.readFailed);
  page.map.moveTo(...KL);
  assert.equal(page.alert(), "");
});

// ---------- the check ----------

test("a check sends only the snapped square's centre, then hands over the Place and ends aim mode", async () => {
  const page = setup();
  const asked = serve(covering);
  await aim(page);
  page.map.moveTo(...SRI_MUDA);
  page.check.click();
  assert.equal(page.status(), "Reading the flood model…", "the wait is said at once");
  assert.equal(page.check.getAttribute("aria-disabled"), "true");
  await flush();
  const square = snapToGrid(...SRI_MUDA, [E100]);
  assert.deepEqual(asked, [{ path: "/api/point", body: { lat: square.lat, lon: square.lon, source: "pin" } }]);
  assert.notEqual(asked[0].body.lat, SRI_MUDA[0], "never the point the cross was on");
  assert.deepEqual(page.checked.map((place) => place.id), [square.id]);
  assert.deepEqual(page.squared, [SQUARES], "the squares around the point came in the same answer");
  assert.equal(page.panel.hidden, true);
  assert.equal(page.map.count("exitAim"), 1);
  assert.equal(page.document.listenerCount("keydown"), 0);
});

test("an answer with a point but no squares, or squares that are not lists, still hands over the point, with none", async () => {
  const page = setup();
  for (const extra of [{ blocks: undefined, cells: undefined }, { blocks: "x", cells: 3 }, { blocks: BLOCKS, cells: undefined }]) {
    serve((path, body) => ({ ...covering(path, body), ...extra }));
    await aim(page);
    page.check.click();
    await flush();
  }
  assert.equal(page.checked.length, 3);
  assert.deepEqual(page.squared, [null, null, null]);
});

test("nothing is sent for a spot no loaded grid holds", async () => {
  const page = setup();
  const asked = serve(covering);
  await aim(page);
  page.map.moveTo(...KUCHING);
  page.check.click();                 // disabled: nothing happens
  page.document.fire("keydown", { key: "Enter", target: page.anchor });   // the keyboard's way to check: nothing either
  await flush();
  assert.deepEqual(asked, []);
  assert.deepEqual(page.checked, []);
});

test("a spot the server will not check says why, and stays off until the cross moves; asking again is not needed", async () => {
  const page = setup();
  const asked = serve(() => ({ coverage: "outside", region: null, place: null }));
  await aim(page);
  page.map.moveTo(...KL);
  page.check.click();
  await flush();
  assert.equal(page.status(), "This spot is outside Malaysia. Banjir Check covers Malaysia only.");
  assert.equal(page.alert(), "");
  assert.equal(page.check.disabled, true, "the same square would get the same answer");
  assert.equal(asked.length, 1);
  assert.deepEqual(page.checked, []);
  page.map.moveTo(...NORTH_OF_KL);
  assert.equal(page.status(), "");
  assert.equal(page.check.disabled, false);
  page.map.moveTo(...KL);
  assert.equal(page.check.disabled, true, "the refusal is remembered");
  assert.equal(page.status(), "This spot is outside Malaysia. Banjir Check covers Malaysia only.");
});

test("a server that cannot be reached says so in an alert, aim mode stays, and the next try can work", async () => {
  const page = setup();
  await aim(page);
  serve(() => { throw new Error("offline"); });
  page.check.click();
  await flush();
  assert.equal(page.alert(), "Could not reach the server. Check your connection and try again.");
  assert.equal(page.status(), "");
  assert.equal(page.panel.hidden, false);
  assert.equal(page.check.disabled, false);
  assert.equal(page.check.getAttribute("aria-disabled"), null);
  serve(covering);
  page.check.click();
  await flush();
  assert.equal(page.checked.length, 1);
});

test("an error the server words itself is said in its words, such as too many checks", async () => {
  const page = setup();
  await aim(page);
  serve(() => ({ failure: "Too many requests. Please wait a few minutes." }));
  page.check.click();
  await flush();
  assert.equal(page.alert(), "Too many requests. Please wait a few minutes.");
  assert.equal(page.check.disabled, false, "the next try can work");
  assert.deepEqual(page.checked, []);
});

test("an answer that is not a point is a failure to read the model", async () => {
  const page = setup();
  await aim(page);
  for (const answer of [null,
    { coverage: "covered", region: "peninsula", place: { id: "node-1", is_point: false } },
    { coverage: "covered", region: "peninsula", place: { ...placeAt(...KL), cell: null } },
    { coverage: "covered", region: "peninsula", place: { ...placeAt(...KL), depth_m: null } }]) {
    serve(() => answer);
    page.check.click();
    await flush();
    assert.equal(page.alert(), WORDS.readFailed, JSON.stringify(answer)?.slice(0, 60));
  }
  assert.deepEqual(page.checked, []);
});

test("a second click while the server is asked sends nothing more", async () => {
  const page = setup();
  const gate = deferred();
  const asked = serve(() => gate.promise);
  await aim(page);
  page.check.click();
  page.check.click();
  page.document.fire("keydown", { key: "Enter", target: page.anchor });
  gate.resolve(covering("/api/point", { lat: 3.025, lon: 101.5325 }));
  await flush();
  assert.equal(asked.length, 1);
  assert.equal(page.checked.length, 1);
});

test("an answer that comes after Cancel is dropped, and so is one that comes after leaving the tab", async () => {
  const page = setup();
  const gate = deferred();
  serve(() => gate.promise);
  await aim(page);
  page.check.click();
  page.button("Cancel").click();
  gate.resolve(covering("/api/point", { lat: 3.025, lon: 101.5325 }));
  await flush();
  assert.deepEqual(page.checked, []);
  assert.equal(page.panel.hidden, true);

  const later = deferred();
  serve(() => later.promise);
  await aim(page);
  page.check.click();
  page.pin.render({ tab: "business", place: { id: "node-1", is_point: false } });
  later.resolve(covering("/api/point", { lat: 3.025, lon: 101.5325 }));
  await flush();
  assert.deepEqual(page.checked, []);
});

test("a check that has to ask for the coverage first does, and says it could not when it cannot", async () => {
  let works = false;
  const page = setup({ getCoverage: async () => { if (!works) throw new Error("offline"); return COVERAGE; } });
  page.pin.start({});
  await flush();
  assert.equal(page.alert(), WORDS.readFailed, "said as soon as aim mode begins");
  page.check.click();
  await flush();
  assert.equal(page.alert(), WORDS.readFailed);
  assert.deepEqual(page.checked, []);
  works = true;
  page.check.click();
  await flush();
  assert.equal(page.checked.length, 1);
});

test("the first words of aim mode wait until the panel has been drawn, so a live region says them", async () => {
  const page = setup({ centre: { lat: KUCHING[0], lon: KUCHING[1] } });
  page.pin.start({});
  assert.equal(page.status(), "", "not in the same breath as showing the panel");
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(page.status(), "", "nor as soon as the coverage is there");
  await flush();
  assert.equal(page.status(), "Sabah and Sarawak are not in this build yet.");
  assert.equal(page.check.disabled, true);
});

test("when the coverage cannot be had at the start, the server's own words are said, as they are for a check", async () => {
  const page = setup({ getCoverage: async () => { throw new ApiError("Too many requests. Please wait a few minutes."); } });
  page.pin.start({});
  await flush();
  assert.equal(page.alert(), "Too many requests. Please wait a few minutes.");
});

test("when the coverage cannot be had, the alert for it waits for the panel too", async () => {
  const page = setup({ getCoverage: async () => { throw new Error("offline"); } });
  page.pin.start({});
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(page.alert(), "");
  await flush();
  assert.equal(page.alert(), WORDS.readFailed);
});

test("words that come late for aim mode that is over are not written", async () => {
  const page = setup({ centre: { lat: KUCHING[0], lon: KUCHING[1] } });
  page.pin.start({});
  page.pin.close();
  await flush();
  assert.equal(page.status(), "");
});

test("a button that goes off while it has focus hands focus to the map, which a page left on the body could not", async () => {
  const page = setup();
  serve(() => ({ coverage: "outside", region: null, place: null }));
  await aim(page);
  const before = page.map.count("focusMap");
  page.check.focus();
  page.check.click();
  await flush();
  assert.equal(page.check.disabled, true);
  assert.equal(page.map.count("focusMap"), before + 1, "the map took focus when the button went off");
  page.map.moveTo(...NORTH_OF_KL);   // it comes back on: nothing to move
  assert.equal(page.map.count("focusMap"), before + 1);
});

test("a button that goes off while focus is somewhere else leaves focus alone", async () => {
  const page = setup();
  await aim(page);
  const before = page.map.count("focusMap");
  page.map.moveTo(...KUCHING);
  assert.equal(page.check.disabled, true);
  assert.equal(page.map.count("focusMap"), before);
});

test("a check asks about where the cross was when it was pressed, though the coverage arrives later", async () => {
  const gate = deferred();
  const page = setup({ getCoverage: () => gate.promise });
  const asked = serve(covering);
  page.pin.start({});
  page.check.click();
  page.map.moveTo(...KL);                        // the person goes on moving the map while the coverage is awaited
  gate.resolve(COVERAGE);
  await flush();
  const square = snapToGrid(3.025, 101.5325, [E100]);
  assert.deepEqual(asked.map((request) => request.body.lat), [square.lat]);
  assert.deepEqual(page.checked.map((place) => place.id), [square.id]);
});

// ---------- ending aim mode ----------

test("Cancel gives focus back to what opened aim mode, and Escape does the same", async () => {
  const page = setup();
  const opener = new PanelElement("button");
  await aim(page, { opener });
  page.button("Cancel").click();
  assert.equal(page.document.activeElement, opener);
  assert.equal(page.panel.hidden, true);
  assert.equal(page.map.count("exitAim"), 1);
  await aim(page, { opener });
  page.document.activeElement = page.anchor;
  page.document.fire("keydown", { key: "Escape", target: page.anchor });
  assert.equal(page.document.activeElement, opener);
  assert.equal(page.panel.hidden, true);
});

test("with nothing to give focus back to, or something that is not on show, focus goes to the map", async () => {
  const page = setup();
  await aim(page, { opener: null });
  const before = page.map.count("focusMap");
  page.button("Cancel").click();
  assert.equal(page.map.count("focusMap"), before + 1);

  const hiddenParent = new PanelElement("div");
  hiddenParent.hidden = true;
  const buried = new PanelElement("button");
  hiddenParent.append(buried);
  await aim(page, { opener: buried });
  const again = page.map.count("focusMap");
  page.button("Cancel").click();
  assert.equal(page.map.count("focusMap"), again + 1);
});

test("Escape is left alone when a field has it, or the dialog, or something else already took it", async () => {
  const page = setup();
  await aim(page);
  page.document.fire("keydown", { key: "Escape", target: new PanelElement("input") });
  page.document.fire("keydown", { key: "Escape", target: page.anchor, defaultPrevented: true });
  page.dialog.open = true;
  page.document.fire("keydown", { key: "Escape", target: page.anchor });
  page.dialog.open = false;
  assert.equal(page.panel.hidden, false, "aim mode is still on");
  page.document.fire("keydown", { key: "Escape", target: page.anchor });
  assert.equal(page.panel.hidden, true);
});

test("Enter checks only when it is on the map itself", async () => {
  const page = setup();
  const asked = serve(covering);
  await aim(page);
  page.document.fire("keydown", { key: "Enter", target: page.check });
  page.document.fire("keydown", { key: "Enter", target: new PanelElement("input") });
  await flush();
  assert.equal(asked.length, 0);
  page.document.fire("keydown", { key: "Enter", target: page.anchor });
  await flush();
  assert.equal(asked.length, 1);
});

test("leaving the Area overview ends aim mode and leaves focus where the person put it; staying on it does not", async () => {
  const page = setup();
  await aim(page);
  const elsewhere = new PanelElement("button");
  page.document.activeElement = elsewhere;
  page.pin.render({ tab: "overview", place: { id: "node-1", is_point: false } });
  assert.equal(page.panel.hidden, false);
  page.pin.render({ tab: "business", place: { id: "node-1", is_point: false } });
  assert.equal(page.panel.hidden, true);
  assert.equal(page.document.activeElement, elsewhere);
  assert.equal(page.document.listenerCount("keydown"), 0);
  page.pin.close();   // closing what is closed is nothing
  assert.equal(page.map.count("exitAim"), 1);
});

// ---------- the location ----------

test("the location button is left out where the browser has no location", () => {
  const page = setup({ geolocation: null });
  assert.equal(page.locate, undefined);
  assert.deepEqual(page.panel.querySelectorAll("button").map((found) => found.textContent), ["Check this spot", "Cancel"]);
});

test("the dialog comes first: nothing is asked of the browser until the person shares", async () => {
  const calls = [];
  const page = setup({ geolocation: (ok, fail, options) => calls.push(options) });
  await aim(page);
  pressLocate(page);
  assert.equal(page.dialog.open, true);
  assert.deepEqual(calls, []);
  choose(page, "Not now");
  await flush();
  assert.deepEqual(calls, []);
  assert.equal(page.dialog.open, false);
  assert.equal(page.status(), "");
  assert.equal(page.panel.hidden, false, "aim mode goes on");
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  assert.deepEqual(calls, [FIX_OPTIONS]);
});

test("while the fix is found the wait is said and the buttons are busy; a good fix moves the cross there and no more is said", async () => {
  let deliver;
  const page = setup({ geolocation: (ok) => { deliver = ok; } });
  await aim(page);
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  assert.equal(page.status(), "Finding your location…");
  assert.equal(page.locate.getAttribute("aria-disabled"), "true");
  assert.equal(page.check.getAttribute("aria-disabled"), "true");
  deliver({ coords: { latitude: KL[0], longitude: KL[1], accuracy: 12 } });
  assert.deepEqual(page.map.calls.find(([name]) => name === "aimAt"), ["aimAt", KL[0], KL[1], 17]);
  assert.deepEqual(page.map.calls.findLast(([name]) => name === "showAccuracy"), ["showAccuracy", null]);
  assert.equal(page.status(), "");
  assert.equal(page.alert(), "");
  assert.equal(page.locate.getAttribute("aria-disabled"), null);
  assert.equal(page.document.activeElement, page.check, "focus goes to what comes next");
});

test("a fix that is wide shows its circle and the hint, and a later good one takes the circle off", async () => {
  let deliver;
  const page = setup({ geolocation: (ok) => { deliver = ok; } });
  await aim(page);
  const share = async () => { pressLocate(page); choose(page, "Share my location"); await flush(); };
  await share();
  deliver({ coords: { latitude: KL[0], longitude: KL[1], accuracy: 500 } });
  assert.deepEqual(page.map.calls.findLast(([name]) => name === "showAccuracy"), ["showAccuracy", { lat: KL[0], lon: KL[1], metres: 500 }]);
  assert.equal(page.status(), "Move the cross to your premises before you check.");
  await share();
  deliver({ coords: { latitude: KL[0], longitude: KL[1], accuracy: 20 } });
  assert.deepEqual(page.map.calls.findLast(([name]) => name === "showAccuracy"), ["showAccuracy", null]);
  assert.equal(page.status(), "");
});

test("checking right after a fix is a GPS point, and once the cross has moved to another square it is a pin", async () => {
  let deliver;
  const page = setup({ geolocation: (ok) => { deliver = ok; } });
  const asked = serve(covering);
  await aim(page);
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  deliver({ coords: { latitude: KL[0], longitude: KL[1], accuracy: 10 } });
  page.check.click();
  await flush();
  assert.equal(asked.at(-1).body.source, "gps");
  assert.equal(asked.at(-1).body.lat, snapToGrid(...KL, [E100]).lat, "the square's centre, not the fix");

  await aim(page);
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  deliver({ coords: { latitude: KL[0], longitude: KL[1], accuracy: 10 } });
  page.map.moveTo(...NORTH_OF_KL);
  page.check.click();
  await flush();
  assert.equal(asked.at(-1).body.source, "pin");
});

test("a fix in a place the map cannot show says it is outside Malaysia and moves nothing", async () => {
  let deliver;
  const page = setup({ geolocation: (ok) => { deliver = ok; } });
  await aim(page);
  page.map.offMap = true;
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  deliver({ coords: { latitude: 35.68, longitude: 139.69, accuracy: 10 } });
  assert.equal(page.status(), "This spot is outside Malaysia. Banjir Check covers Malaysia only.");
  assert.deepEqual(page.map.calls.findLast(([name]) => name === "showAccuracy"), ["showAccuracy", null]);
  assert.equal(page.check.disabled, true, "the check would be of the cross, not of the fix the words are about");
  page.map.moveTo(...KL);
  assert.equal(page.status(), "", "a move of the map ends it");
  assert.equal(page.check.disabled, false);
});

test("a fix over a place that is not covered moves the cross there and turns the check off with the reason", async () => {
  let deliver;
  const page = setup({ geolocation: (ok) => { deliver = ok; } });
  await aim(page);
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  deliver({ coords: { latitude: KUCHING[0], longitude: KUCHING[1], accuracy: 10 } });
  assert.equal(page.status(), "Sabah and Sarawak are not in this build yet.");
  assert.equal(page.check.disabled, true);
  assert.notEqual(page.document.activeElement, page.check, "focus is not put on a button that is off");
  assert.equal(page.map.calls.at(-1)[0], "focusMap", "it goes to the map");
});

test("a refused or failed location is an alert in its own words, and the buttons are ready again", async () => {
  let fail;
  const page = setup({ geolocation: (ok, error) => { fail = error; } });
  await aim(page);
  const share = async () => { pressLocate(page); choose(page, "Share my location"); await flush(); };
  await share();
  fail({ code: 1 });
  assert.equal(page.alert(), "Location is blocked for this page. Move the map to your premises instead.");
  assert.equal(page.locate.getAttribute("aria-disabled"), null);
  for (const code of [2, 3]) {
    await share();
    fail({ code });
    assert.equal(page.alert(), "Your location could not be found. Try again, or move the map to your premises.", `code ${code}`);
  }
  assert.equal(page.map.count("aimAt"), 0, "no fix, no move");
});

test("a browser that loses its location after the page began says the location could not be found", async () => {
  const page = setup({ geolocation: () => {} });
  await aim(page);
  delete globalThis.navigator.geolocation;
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  assert.equal(page.alert(), "Your location could not be found. Try again, or move the map to your premises.");
});

test("a fix that comes after Cancel is dropped", async () => {
  let deliver;
  const page = setup({ geolocation: (ok) => { deliver = ok; } });
  await aim(page);
  pressLocate(page);
  choose(page, "Share my location");
  await flush();
  page.button("Cancel").click();
  deliver({ coords: { latitude: KL[0], longitude: KL[1], accuracy: 10 } });
  assert.equal(page.map.count("aimAt"), 0);
  assert.equal(page.map.count("showAccuracy"), 0);
});

test("the location button does nothing while a check or a fix is being waited for", async () => {
  const calls = [];
  const page = setup({ geolocation: () => calls.push("asked") });
  const gate = deferred();
  serve(() => gate.promise);
  await aim(page);
  page.check.click();
  pressLocate(page);
  assert.equal(page.dialog.open, false);
  gate.resolve(covering("/api/point", { lat: 3.025, lon: 101.5325 }));
  await flush();
  assert.deepEqual(calls, []);
});
