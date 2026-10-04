// Run from 11_Platform_Draft:  node --test tests/plan.test.mjs
// The flood plan on My business (plan.js, plan card G2), on the fake DOM: the language choice, the states, our facts and
// contacts printed beside Gemini's steps, and the print button.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createPlanCard } from "../app/static/js/plan.js";
import { installFakeDom } from "./fake_dom.mjs";

const FACTS = {
  place: "Anetas KARUPATI COFFEE RESTAURANT", kind: "restaurant", area: "Taman Sri Muda",
  floods: [
    { size: "1 in 10 years", chance_in_10_years_pct: 65, street_depth_m: 1.35, water_above_floor_m: 1.35 },
    { size: "1 in 100 years", chance_in_10_years_pct: 10, street_depth_m: 1.88, water_above_floor_m: 1.88 },
    { size: "1 in 500 years", chance_in_10_years_pct: 2, street_depth_m: null, water_above_floor_m: 0 },
  ],
  floor_height_cm: 0, relief_centre: null, estimate: null, model_note: "Depths are from a global river flood model.",
};
const RESULT = {
  language: "ms", facts: FACTS,
  plan: { title: "Pelan banjir kedai anda", summary: "Dalam model, air sampai 1.88 m.", before: ["Simpan dokumen di rak atas."],
    warning: ["Angkat stok."], during: ["Tutup suis utama."], after: ["Bersihkan kedai."] },
  contacts: [{ name: "Emergency (police, fire, ambulance)", how: "999" }, { name: "Majlis Bandaraya Shah Alam", how: "your local council" }],
};

beforeEach(() => installFakeDom());

function mount() {
  const calls = { written: [], printed: 0, languages: [] };
  const card = createPlanCard({
    onWrite: (language) => calls.written.push(language), onPrint: () => { calls.printed += 1; },
    onLanguage: (language) => calls.languages.push(language),
  });
  const button = (words) => card.node.querySelectorAll("button").find((b) => b.textContent === words);
  return { card, calls, button, text: () => card.node.textContent };
}

test("before a plan it explains itself, defaults to Bahasa Melayu and writes in the language chosen", () => {
  const { card, calls, button, text } = mount();
  card.render(undefined, "ms");
  assert.match(text(), /Gemini writes a one-page plan/);
  const radios = card.node.querySelectorAll("input");
  assert.deepEqual(radios.map((r) => r.getAttribute("value")), ["ms", "en"]);
  assert.equal(radios[0].checked, true);
  assert.equal(radios[1].checked, false);
  radios[1].dispatch("change");
  assert.deepEqual(calls.languages, ["en"]);
  button("Write my flood plan").click();
  assert.deepEqual(calls.written, ["ms"]);
  assert.equal(button("Print or save as PDF"), undefined);
});

test("a plan shows Gemini's steps under headings in its own language, beside our facts and contacts", () => {
  const { card, text } = mount();
  card.render({ result: RESULT }, "ms");
  const headings = card.node.querySelectorAll("h4").map((h) => h.textContent);
  assert.deepEqual(headings, ["Sebelum banjir", "Bila ada amaran", "Semasa banjir", "Selepas banjir", "Hubungi"]);
  assert.match(text(), /Pelan banjir kedai anda/);
  const rows = card.node.querySelectorAll("tr").slice(1).map((row) => row.textContent);
  assert.match(rows[1], /1 dalam 100 tahun.*10%.*1\.88 m/);
  assert.match(rows[2], /tiada air dalam model/);
  assert.match(text(), /999/);
  assert.match(text(), /Ditulis oleh Gemini/);
});

test("an English plan has English headings", () => {
  const { card } = mount();
  card.render({ result: { ...RESULT, language: "en" } }, "en");
  assert.deepEqual(card.node.querySelectorAll("h4").map((h) => h.textContent), ["Before a flood", "When a warning comes", "During a flood", "After a flood", "Contacts"]);
});

test("print calls onPrint, and busy and failed states say so", () => {
  const { card, calls, button, text } = mount();
  card.render({ result: RESULT }, "ms");
  button("Print or save as PDF").click();
  assert.equal(calls.printed, 1);
  card.render({ busy: true, result: RESULT }, "ms");
  assert.equal(button("Writing your plan…").disabled, true);
  card.render({ error: "The AI assistant is not set up yet." }, "ms");
  assert.match(card.node.querySelector('[role="alert"]').textContent, /not set up/);
  assert.doesNotMatch(text(), /Pelan banjir/);
});

// ---------- review fixes ----------

test("the controls are kept across renders, so choosing a language keeps focus, and the choice is shown", () => {
  const { card } = mount();
  card.render(undefined, "ms");
  const [ms, en] = card.node.querySelectorAll("input");
  const write = card.node.querySelector("button");
  card.render(undefined, "en");
  assert.equal(card.node.querySelectorAll("input")[1], en, "the same radio, not a new one");
  assert.equal(card.node.querySelector("button"), write);
  assert.equal(en.checked, true);
  assert.equal(ms.checked, false);
});

test("a section the server left empty has no heading", () => {
  const { card } = mount();
  card.render({ result: { ...RESULT, plan: { ...RESULT.plan, during: [] } } }, "ms");
  assert.deepEqual(card.node.querySelectorAll("h4").map((h) => h.textContent), ["Sebelum banjir", "Bila ada amaran", "Selepas banjir", "Hubungi"]);
});

// ---------- sharing ----------

import { planText } from "../app/static/js/plan.js";

test("the plan as text has the title, our figures, numbered steps, contacts and the footer", () => {
  const text = planText(RESULT);
  assert.match(text, /^Pelan banjir kedai anda\n/);
  assert.match(text, /1 dalam 100 tahun: air 1\.88 m di jalan dalam model; peluang dalam 10 tahun 10%/);
  assert.match(text, /^Pelan banjir kedai anda\n.*\n.*\nAngka daripada model banjir/);
  assert.match(text, /Sebelum banjir\n1\. Simpan dokumen di rak atas\./);
  assert.match(text, /Hubungi\n- Emergency \(police, fire, ambulance\): 999/);
  assert.match(text, /Ditulis oleh Gemini/);
});

test("a plan offers WhatsApp with its text, and the phone's own share where there is one", () => {
  const { card } = mount();
  card.render({ result: RESULT }, "ms");
  const link = card.node.querySelectorAll("a").find((a) => a.textContent === "Send on WhatsApp");
  assert.ok(link.getAttribute("href").startsWith("https://wa.me/?text="));
  assert.equal(decodeURIComponent(link.getAttribute("href").slice("https://wa.me/?text=".length)), planText(RESULT));
  assert.equal(link.getAttribute("rel"), "noopener noreferrer");
});

import { MAX_SHARE_CHARS } from "../app/static/js/plan.js";

test("a long plan is cut in its steps, never in its figures, contacts or footer", () => {
  const long = { ...RESULT, plan: { ...RESULT.plan, before: Array.from({ length: 30 }, (_, i) => `Langkah ${i} ${"x".repeat(180)}`) } };
  const text = planText(long);
  assert.ok(encodeURIComponent(text).length <= MAX_SHARE_CHARS, String(encodeURIComponent(text).length));
  assert.match(text, /…\n\nHubungi\n- Emergency/);
  assert.match(text, /Ditulis oleh Gemini/);
  assert.match(text, /1 dalam 100 tahun/);
});

test("a dry flood size reads as no water in the street in the model", () => {
  const dry = { ...RESULT, language: "en", facts: { ...FACTS, floods: FACTS.floods.map((f) => ({ ...f, street_depth_m: null })) } };
  assert.match(planText(dry), /1 in 10 years: no water in the street in the model; chance within 10 years 65%/);
});

// ---------- review batch 3 ----------

test("a failed write again keeps the plan on show, with the error beside it", () => {
  const { card, text } = mount();
  card.render({ result: RESULT }, "ms");
  const sheet = card.node.querySelector(".plan-sheet");
  card.render({ busy: true, result: RESULT }, "ms");
  card.render({ result: RESULT, error: "Too many requests. Please wait a moment." }, "ms");
  assert.match(card.node.querySelector('[role="alert"]').textContent, /Too many requests/);
  assert.equal(card.node.querySelector('[role="alert"]').hidden, false);
  assert.equal(card.node.querySelector(".plan-sheet"), sheet, "the same sheet, not rebuilt");
  assert.match(text(), /Pelan banjir kedai anda/);
  card.render({ result: RESULT }, "ms");
  assert.equal(card.node.querySelector('[role="alert"]').hidden, true, "the error goes with the next try");
});

test("the Write button gets focus back when the plan is done, if the page took it", () => {
  const { card, button } = mount();
  const body = {};
  document.body = body;
  card.render(undefined, "ms");
  const write = button("Write my flood plan");
  write.focus = () => { document.activeElement = write; };
  document.activeElement = write;
  card.render({ busy: true }, "ms");
  document.activeElement = body;   // the disabled button lost it
  card.render({ result: RESULT }, "ms");
  assert.equal(document.activeElement, write);

  card.render({ busy: true, result: RESULT }, "ms");
  const elsewhere = {};
  document.activeElement = elsewhere;
  card.render({ result: RESULT, error: "x" }, "ms");
  assert.equal(document.activeElement, elsewhere, "focus the user moved is left alone");
});

const encoded = (text) => encodeURIComponent(text).length;

test("the WhatsApp cap counts the percent-encoded text, not the characters", () => {
  // Malay text with curly quotes and line breaks: every one of them is 3 to 9 encoded characters
  const steps = Array.from({ length: 40 }, (_, i) => `Langkah ${i}: simpan dokumen penting ‘di rak atas’ — jauh dari air banjir yang naik.`);
  const result = { ...RESULT, plan: { ...RESULT.plan, before: steps, warning: steps.slice(0, 10) } };
  const text = planText(result);
  assert.ok(encoded(text) <= MAX_SHARE_CHARS, String(encoded(text)));
  assert.ok(text.length < encoded(text) - 200, "the raw length is well under the encoded one, so a raw cap would have let it through");
  assert.match(text, /…\n\nHubungi\n- Emergency/);
  assert.match(text, /Ditulis oleh Gemini/);
  assert.match(text, /1 dalam 100 tahun/);
  const link = `https://wa.me/?text=${encodeURIComponent(text)}`;
  assert.ok(link.length <= MAX_SHARE_CHARS + "https://wa.me/?text=".length);
});

test("a cut plan ends on a whole step, never on a heading with nothing under it", () => {
  const many = Array.from({ length: 12 }, (_, i) => `Langkah ${i} ${"x".repeat(150)}`);
  const text = planText({ ...RESULT, plan: { title: "T", summary: "S", before: many, warning: many, during: many, after: many } });
  const body = text.slice(text.indexOf("Sebelum banjir"), text.indexOf("…"));
  assert.match(body.trimEnd(), /\d+\. Langkah \d+ x+$/);
});

test("a plan whose figures and contacts alone are too long still gives a valid link that fits", () => {
  const huge = { ...RESULT, plan: { ...RESULT.plan, title: `Pelan ${"é😀".repeat(1500)}`, summary: "s".repeat(800) } };
  const text = planText(huge);
  assert.ok(encoded(text) <= MAX_SHARE_CHARS, String(encoded(text)));
  assert.doesNotThrow(() => encodeURIComponent(text), "no character was cut in half");
  assert.match(text, /Ditulis oleh Gemini/, "the footer is the last to go");
  assert.match(text, /Hubungi\n- Emergency/);
  const absurd = { ...RESULT, contacts: Array.from({ length: 400 }, (_, i) => ({ name: `Hubungi ${i} ${"😀".repeat(5)}`, how: "999" })) };
  const tail = planText(absurd);
  assert.ok(encoded(tail) <= MAX_SHARE_CHARS);
  assert.doesNotThrow(() => encodeURIComponent(tail));
});

test("a failed share sheet sends this page to WhatsApp, not into a popup; a cancelled one does nothing", async () => {
  const wasNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  try {
    for (const [failure, goes] of [[new DOMException("closed", "AbortError"), false], [new Error("NotAllowedError"), true]]) {
      Object.defineProperty(globalThis, "navigator", { value: { share: async () => { throw failure; } }, configurable: true });
      const opened = [];
      globalThis.window = { open: (...args) => opened.push(args) };
      globalThis.location = { href: "https://example.test/#p" };
      const { card, button } = mount();
      card.render({ result: RESULT }, "ms");
      button("Share…").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      assert.deepEqual(opened, [], "window.open is blocked on iOS after an await");
      if (goes) assert.equal(globalThis.location.href, `https://wa.me/?text=${encodeURIComponent(planText(RESULT))}`);
      else assert.equal(globalThis.location.href, "https://example.test/#p");
    }
  } finally {
    if (wasNavigator) Object.defineProperty(globalThis, "navigator", wasNavigator);
    else delete globalThis.navigator;
    delete globalThis.window;
    delete globalThis.location;
  }
});

test("with the AI switched off the write button is off and a line says why", () => {
  const calls = [];
  const card = createPlanCard({ onWrite: (language) => calls.push(language), onPrint() {}, onLanguage() {}, isReady: false });
  card.render(undefined, "ms");
  const write = card.node.querySelectorAll("button").find((b) => b.textContent === "Write my flood plan");
  assert.equal(write.disabled, true);
  write.click();
  assert.deepEqual(calls, []);
  assert.match(card.node.textContent, /Needs the AI assistant, which is switched off in this test build\./);
  card.render({ busy: false, error: "x" }, "en");   // a later render does not switch it back on
  assert.equal(write.disabled, true);
});

test("with the AI on there is no such line and the button works", () => {
  const { card, button } = mount();
  card.render(undefined, "ms");
  assert.equal(button("Write my flood plan").disabled, false);
  assert.doesNotMatch(card.node.textContent, /switched off/);
});
