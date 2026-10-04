// Run from 11_Platform_Draft:  node --test tests/chat_widget.test.mjs
// The floating chat's button and dialog (chat-widget.js), on the small fake DOM in tests/fake_dom.mjs with a stand-in for
// the native <dialog>: showModal and close, and the `close` event the browser sends after Escape or close().
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { h } from "../app/static/js/dom.js";
import { createChatWidget } from "../app/static/js/chat-widget.js";
import { installFakeDom } from "./fake_dom.mjs";

const SIZE = { left: 100, top: 0, right: 500, bottom: 800 };

/** A fake native dialog: showModal opens it, close() shuts it and says so with a `close` event, as the browser does, and
 *  Escape is the same close. `shows` counts showModal calls. */
function fakeDialog(...children) {
  const dialog = h("dialog", {}, ...children);
  Object.assign(dialog, { open: false, shows: 0, getBoundingClientRect: () => SIZE });
  dialog.showModal = () => { dialog.open = true; dialog.shows += 1; };
  dialog.close = () => { if (dialog.open) { dialog.open = false; dialog.dispatch("close"); } };
  dialog.focus = () => { document.activeElement = dialog; };
  return dialog;
}

/** A control that takes focus when asked and is still on the page. */
function control(tag, attrs = {}) {
  const element = h(tag, attrs);
  element.isConnected = true;
  element.focus = () => { document.activeElement = element; };
  return element;
}

function mount({ sheet = false, ...options } = {}) {
  installFakeDom();
  globalThis.matchMedia = () => ({ matches: sheet });
  const button = control("button", { hidden: true, "aria-expanded": "false" });
  const input = control("input");
  const mic = control("button", { class: "mic", "aria-pressed": "false" });
  const dialog = fakeDialog(input, mic);
  const log = [];
  mic.addEventListener("click", () => log.push("mic"));
  const widget = createChatWidget({ button, dialog, input, onClose: () => log.push("closed"), ...options });
  return { widget, button, dialog, input, mic, log };
}

test("the button is shown once the widget is built, and starts closed", () => {
  const { button } = mount();
  assert.equal(button.hidden, false);
  assert.equal(button.getAttribute("aria-expanded"), "false");
});

test("opening shows the dialog modally, says so on the button and puts focus in the question box", () => {
  const { widget, button, dialog, input } = mount();
  widget.open(button);
  assert.equal(dialog.open, true);
  assert.equal(widget.isOpen, true);
  assert.equal(button.getAttribute("aria-expanded"), "true");
  assert.equal(document.activeElement, input);
});

test("on a phone sheet focus goes to the dialog, so the keyboard does not cover the conversation", () => {
  const { widget, button, dialog } = mount({ sheet: true });
  widget.open(button);
  assert.equal(document.activeElement, dialog);
});

test("with the question box off (no AI in this build) focus goes to the dialog", () => {
  const { widget, button, dialog, input } = mount();
  input.disabled = true;
  widget.open(button);
  assert.equal(document.activeElement, dialog);
});

test("opening twice shows it once", () => {
  const { widget, button, dialog } = mount();
  widget.open(button);
  widget.open(button);
  assert.equal(dialog.shows, 1);
});

test("closing gives focus back to what opened it and clears aria-expanded", () => {
  const { widget, button, dialog } = mount();
  const shortcut = control("button");
  widget.open(shortcut);
  assert.equal(button.getAttribute("aria-expanded"), "true", "the floating button shows the state whoever opened it");
  widget.close();
  assert.equal(dialog.open, false);
  assert.equal(button.getAttribute("aria-expanded"), "false");
  assert.equal(document.activeElement, shortcut);
});

test("Escape, which closes the dialog by itself, ends the same way", () => {
  const { widget, button, dialog } = mount();
  widget.open(button);
  dialog.close();   // what Escape does
  assert.equal(button.getAttribute("aria-expanded"), "false");
  assert.equal(document.activeElement, button);
  assert.equal(widget.isOpen, false);
});

test("an opener that is gone by then (its card was drawn again) gives focus to the floating button", () => {
  const { widget, button } = mount();
  const shortcut = control("button");
  widget.open(shortcut);
  shortcut.isConnected = false;
  widget.close();
  assert.equal(document.activeElement, button);
});

test("opened with no opener (a link), focus goes back to the floating button", () => {
  const { widget, button } = mount();
  widget.open();
  widget.close();
  assert.equal(document.activeElement, button);
});

test("a click on the backdrop closes it; a click inside does not", () => {
  const { widget, button, dialog, input } = mount();
  widget.open(button);
  dialog.dispatch("click", { target: input, clientX: 200, clientY: 100 });
  assert.equal(dialog.open, true);
  dialog.dispatch("click", { target: dialog, clientX: 300, clientY: 100 });
  assert.equal(dialog.open, true, "a gap inside the panel is not the backdrop");
  dialog.dispatch("click", { target: dialog, clientX: 20, clientY: 100 });
  assert.equal(dialog.open, false);
});

test("closing stops a recording that is on and what is being read aloud", () => {
  const { widget, button, mic, log } = mount();
  widget.open(button);
  mic.setAttribute("aria-pressed", "true");
  widget.close();
  assert.deepEqual(log, ["mic", "closed"]);
  const quiet = mount();
  quiet.widget.open(quiet.button);
  quiet.widget.close();
  assert.deepEqual(quiet.log, ["closed"], "the microphone is left alone when it is not recording");
});

test("close when it is not open does nothing", () => {
  const { widget, log } = mount();
  widget.close();
  assert.deepEqual(log, []);
});

test("the floating button opens it, and opens it again after it was closed", () => {
  const { widget, button, dialog } = mount();
  button.dispatch("click");
  assert.equal(dialog.open, true);
  widget.close();
  button.dispatch("click");
  assert.equal(dialog.open, true);
  assert.equal(dialog.shows, 2);
});

// ---------- index.html ----------

const PAGE = readFileSync(new URL("../app/static/index.html", import.meta.url), "utf8");
const tagOf = (id) => PAGE.match(new RegExp(`<\\w+[^>]*\\sid="${id}"[^>]*>`))?.[0] ?? "";

test("the page has the floating button wired to the dialog, and no Ask AI tab or panel", () => {
  const fab = tagOf("chat-fab");
  for (const attribute of ['aria-haspopup="dialog"', 'aria-expanded="false"', 'aria-controls="chat-dialog"', "hidden"]) assert.ok(fab.includes(attribute), attribute);
  const dialog = tagOf("chat-dialog");
  assert.match(dialog, /^<dialog /);
  assert.ok(dialog.includes('aria-labelledby="chat-title"') && tagOf("chat-title") !== "");
  assert.ok(!PAGE.includes("tab-ask") && !PAGE.includes("panel-ask") && !PAGE.includes('data-tab="ask"'));
});

test("every part chat.js and main.js take by id is inside the dialog, once", () => {
  const dialog = PAGE.slice(PAGE.indexOf('<dialog class="chat-dialog"'), PAGE.indexOf("</dialog>"));
  for (const id of ["messages", "chips", "ask-form", "question", "news", "ai-status", "ask-lead", "chat-about"]) {
    assert.equal(dialog.split(`id="${id}"`).length, 2, id);
    assert.equal(PAGE.split(`id="${id}"`).length, 2, `${id} appears once in the page`);
  }
});
