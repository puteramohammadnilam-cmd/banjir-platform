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
  assert.ok(text.length <= MAX_SHARE_CHARS, String(text.length));
  assert.match(text, /…\n\nHubungi\n- Emergency/);
  assert.match(text, /Ditulis oleh Gemini/);
  assert.match(text, /1 dalam 100 tahun/);
});

test("a dry flood size reads as no water in the street in the model", () => {
  const dry = { ...RESULT, language: "en", facts: { ...FACTS, floods: FACTS.floods.map((f) => ({ ...f, street_depth_m: null })) } };
  assert.match(planText(dry), /1 in 10 years: no water in the street in the model; chance within 10 years 65%/);
});
