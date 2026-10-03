// Run from 11_Platform_Draft:  node --test tests/pin_panel.test.mjs
// The DOM of "Check any point" (pin-panel.js) under node:test, on the small fake DOM of fake_dom.mjs and what pin_dom.mjs
// adds to it (classList, removeAttribute, a <dialog> that opens and closes). The panel's place on the page, its look and
// the map around it are checked in the browser (checklist 6A).
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { installPinDom } from "./pin_dom.mjs";
import { HELP_ID, createAimPanel, createGpsDialog, createSquaresStatus } from "../app/static/js/pin-panel.js";
import { WORDS, describe } from "../app/static/js/pin-words.js";

beforeEach(() => {
  installPinDom();
});

const IDLE = { phase: "aiming", note: null, blocked: null, fix: null };
const buttons = (panel) => panel.node.querySelectorAll("button");
const live = (panel, role) => panel.node.querySelector(`[role="${role}"]`);
const noop = () => {};

function makePanel(overrides = {}) {
  return createAimPanel({ onCheck: noop, onLocate: noop, onCancel: noop, canLocate: true, ...overrides });
}

// ---------- the aim panel ----------

test("the panel is built hidden, with the plan's heading and words, and the three actions in order", () => {
  const panel = makePanel();
  assert.equal(panel.node.hidden, true);
  assert.equal(panel.node.querySelector("h3").textContent, "Check a point");
  const help = panel.node.querySelector(`[id="${HELP_ID}"]`);
  assert.equal(help.textContent, "Move the map until the cross sits on your premises. With a keyboard, select the map and use the arrow keys.");
  assert.deepEqual(buttons(panel).map((button) => button.textContent), ["Check this spot", "Use my location", "Cancel"]);
  assert.equal(panel.node.getAttribute("aria-labelledby"), panel.node.querySelector("h3").getAttribute("id"));
  panel.show();
  assert.equal(panel.node.hidden, false);
  panel.hide();
  assert.equal(panel.node.hidden, true);
});

test("the two live regions are in the panel from the start, so what goes into them is announced", () => {
  const panel = makePanel();
  assert.ok(live(panel, "status"), "a polite region for results and waits");
  assert.ok(live(panel, "alert"), "an alert region for errors");
  assert.equal(live(panel, "status").textContent, "");
  assert.equal(live(panel, "alert").textContent, "");
});

test("with no location in the browser there is no button for it", () => {
  const panel = makePanel({ canLocate: false });
  assert.deepEqual(buttons(panel).map((button) => button.textContent), ["Check this spot", "Cancel"]);
  panel.paint(describe(IDLE));
  assert.equal(buttons(panel).length, 2);
});

test("the buttons call what they were given, and the location button hands over itself for focus to return to", () => {
  const calls = [];
  const panel = makePanel({ onCheck: () => calls.push("check"), onCancel: () => calls.push("cancel"), onLocate: (button) => calls.push(button) });
  const [check, locate, cancel] = buttons(panel);
  check.click();
  cancel.click();
  locate.dispatch("click", { currentTarget: locate });   // as the browser sets the event's currentTarget
  assert.deepEqual(calls.slice(0, 2), ["check", "cancel"]);
  assert.equal(calls[2], locate);
});

test("an idle panel says nothing and both actions are ready", () => {
  const panel = makePanel();
  panel.paint(describe(IDLE));
  const [check, locate] = buttons(panel);
  assert.deepEqual([check.disabled, check.getAttribute("aria-disabled"), locate.disabled, locate.getAttribute("aria-disabled")], [false, null, false, null]);
  assert.equal(live(panel, "status").textContent, "");
  assert.equal(live(panel, "alert").textContent, "");
});

test("over a spot that cannot be checked the button is truly off and the reason is read out politely", () => {
  const panel = makePanel();
  panel.paint(describe({ ...IDLE, blocked: "Sabah and Sarawak are not in this build yet." }));
  const [check] = buttons(panel);
  assert.equal(check.disabled, true);
  assert.equal(live(panel, "status").textContent, "Sabah and Sarawak are not in this build yet.");
  assert.equal(live(panel, "alert").textContent, "");
});

test("while the server is asked the button stays focusable but is marked busy, and the wait is said", () => {
  const panel = makePanel();
  panel.paint(describe({ ...IDLE, phase: "checking" }));
  const [check, locate] = buttons(panel);
  assert.equal(check.disabled, false, "disabled would drop keyboard focus");
  assert.equal(check.getAttribute("aria-disabled"), "true");
  assert.equal(locate.getAttribute("aria-disabled"), "true");
  assert.ok(check.getAttribute("class").split(" ").includes("is-busy"));
  assert.equal(live(panel, "status").textContent, "Reading the flood model…");
  panel.paint(describe(IDLE));
  assert.equal(check.getAttribute("aria-disabled"), null);
  assert.ok(!check.getAttribute("class").split(" ").includes("is-busy"));
  assert.equal(live(panel, "status").textContent, "");
});

test("an error goes in the alert region as a boxed message, and leaves the polite region empty", () => {
  const panel = makePanel();
  panel.paint(describe({ ...IDLE, note: { text: WORDS.readFailed, tone: "alert" } }));
  assert.equal(live(panel, "alert").textContent, "Could not read the flood model just now. Try again.");
  assert.ok(live(panel, "alert").querySelector(".alert"), "the message sits in the alert box");
  assert.equal(live(panel, "status").textContent, "");
  panel.paint(describe({ ...IDLE, note: { text: WORDS.wideFix, tone: "status" } }));
  assert.equal(live(panel, "alert").textContent, "", "the error is gone when something else is said");
  assert.equal(live(panel, "status").textContent, "Move the cross to your premises before you check.");
});

test("painting the same thing again does not touch the region, so it is not read out twice", () => {
  const panel = makePanel();
  const status = live(panel, "status");
  panel.paint(describe({ ...IDLE, blocked: "Langkawi is not covered yet." }));
  const written = status.children[0];
  panel.paint(describe({ ...IDLE, blocked: "Langkawi is not covered yet." }));
  assert.equal(status.children[0], written, "the same text node: nothing was rewritten");
  const alert = live(panel, "alert");
  panel.paint(describe({ ...IDLE, note: { text: "Oops", tone: "alert" } }));
  const box = alert.children[0];
  panel.paint(describe({ ...IDLE, note: { text: "Oops", tone: "alert" } }));
  assert.equal(alert.children[0], box);
});

test("the panel says whether the focus is inside it", () => {
  const panel = makePanel();
  assert.equal(panel.contains(buttons(panel)[0]), true);
  assert.equal(panel.contains({}), false);
});

// ---------- the location dialog ----------

const makeDialog = () => createGpsDialog();
const opener = () => ({ focused: 0, focus() { this.focused += 1; } });
const choose = (dialog, label) => dialog.node.querySelectorAll("button").find((button) => button.textContent === label).click();

test("the dialog has the plan's title, privacy words and two buttons, and names its title and text for assistive technology", () => {
  const dialog = makeDialog();
  assert.equal(dialog.node.tagName, "dialog");
  assert.equal(dialog.node.querySelector("h2").textContent, "Use your location once?");
  assert.equal(dialog.node.querySelector("p").textContent, WORDS.dialogBody);
  assert.deepEqual(dialog.node.querySelectorAll("button").map((button) => button.textContent), ["Share my location", "Not now"]);
  assert.equal(dialog.node.getAttribute("aria-labelledby"), dialog.node.querySelector("h2").getAttribute("id"));
  assert.equal(dialog.node.getAttribute("aria-describedby"), dialog.node.querySelector("p").getAttribute("id"));
});

test("the dialog takes focus itself, not a button, so a key held down on the button that opened it cannot answer it", () => {
  const dialog = makeDialog();
  assert.equal(dialog.node.getAttribute("tabindex"), "-1", "it can take focus");
  dialog.open(opener());
  assert.equal(globalThis.document.activeElement, dialog.node);
  assert.notEqual(globalThis.document.activeElement.tagName, "button");
});

test("sharing resolves true, shuts the dialog and gives focus back to the opener, without waiting for any close event", async () => {
  const dialog = makeDialog();
  const button = opener();
  const answer = dialog.open(button);
  assert.equal(dialog.isOpen, true);
  choose(dialog, "Share my location");
  assert.equal(dialog.isOpen, false, "shut at once");
  assert.equal(await answer, true);
  assert.equal(button.focused, 1);
});

test("Not now resolves false, shuts the dialog and gives focus back to the opener", async () => {
  const dialog = makeDialog();
  const button = opener();
  const answer = dialog.open(button);
  choose(dialog, "Not now");
  assert.equal(await answer, false);
  assert.equal(dialog.isOpen, false);
  assert.equal(button.focused, 1);
});

test("Escape, which the dialog handles itself and signals with `cancel`, resolves false", async () => {
  const dialog = makeDialog();
  const button = opener();
  const answer = dialog.open(button);
  dialog.node.dispatch("cancel");
  assert.equal(await answer, false);
});

test("each opening is its own: a choice settles only the dialog that is open, once", async () => {
  const dialog = makeDialog();
  const first = dialog.open(opener());
  choose(dialog, "Not now");
  assert.equal(await first, false);
  const second = dialog.open(opener());
  assert.equal(dialog.isOpen, true);
  choose(dialog, "Share my location");
  assert.equal(await second, true);
  choose(dialog, "Share my location");   // a stray click on a shut dialog changes nothing
  assert.equal(dialog.isOpen, false);
});

// ---------- the line about the flood squares ----------

test("the squares line has a polite region and an alert region from the start, both empty", () => {
  const status = createSquaresStatus();
  assert.ok(status.node.querySelector('[role="status"]'));
  assert.ok(status.node.querySelector('[role="alert"]'));
  assert.equal(status.node.textContent, "");
});

test("a note is said politely, and clear takes it away", () => {
  const status = createSquaresStatus();
  status.say(WORDS.squaresNone);
  assert.equal(status.node.querySelector('[role="status"]').textContent, "No flood squares near this point in the model");
  status.say("Another note");
  assert.equal(status.node.querySelector('[role="status"]').textContent, "Another note");
  status.clear();
  assert.equal(status.node.textContent, "");
});

test("a failure is an alert with a Retry button that calls what it was given, and the next note removes it", () => {
  const status = createSquaresStatus();
  let retried = 0;
  status.fail("Flood squares could not load.", () => { retried += 1; });
  const alert = status.node.querySelector('[role="alert"]');
  assert.ok(alert.textContent.startsWith("Flood squares could not load."));
  assert.equal(status.node.querySelector('[role="status"]').textContent, "");
  const retry = alert.querySelector("button");
  assert.equal(retry.textContent, "Retry");
  retry.click();
  assert.equal(retried, 1);
  status.say(WORDS.squaresNone);
  assert.equal(alert.textContent, "", "the failure is gone when something else is said");
  assert.equal(status.node.querySelector('[role="status"]').textContent, WORDS.squaresNone);
});

test("a Retry that has focus keeps it somewhere nearby when the failure goes, and when it fails again", () => {
  const status = createSquaresStatus();
  const document = globalThis.document;
  status.fail("Flood squares could not load.", () => {});
  status.node.querySelector("button").focus();
  status.say(WORDS.squaresNone);
  assert.equal(document.activeElement, status.node, "the line itself takes focus: not the top of the page");
  assert.equal(status.node.getAttribute("tabindex"), "-1");

  status.fail("Flood squares could not load.", () => {});
  const first = status.node.querySelector("button");
  first.focus();
  status.fail("Flood squares could not load.", () => {});
  const again = status.node.querySelector("button");
  assert.notEqual(again, first, "the button was made again");
  assert.equal(document.activeElement, again, "and the new one has focus, as the old one did");

  status.clear();
  assert.equal(document.activeElement, status.node);
});

test("focus that was somewhere else is not moved when the squares line changes", () => {
  const status = createSquaresStatus();
  const document = globalThis.document;
  const elsewhere = { focus() { document.activeElement = this; } };
  elsewhere.focus();
  status.fail("Flood squares could not load.", () => {});
  status.say(WORDS.squaresNone);
  status.clear();
  assert.equal(document.activeElement, elsewhere);
});
