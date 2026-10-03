// Run from 11_Platform_Draft:  node --test tests/i18n.test.mjs
// The page in English and Bahasa Melayu (i18n.js, strings/en.js, strings/ms.js, plan Phase D): the two tables hold the
// same keys and placeholders; the honest wording (every depth is "in the model", money is a rough estimate, the
// privacy claims) survives the translation; index.html carries the English of en.js and marks every word it shows.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

import {
  DEFAULT_LANG, LANGS, applyStatic, lang, linkInLang, resolveLang, t, translate, useLang, wireLangSwitch,
} from "../app/static/js/i18n.js";
import en from "../app/static/js/strings/en.js";
import ms from "../app/static/js/strings/ms.js";
import { h } from "../app/static/js/dom.js";
import { installFakeDom } from "./fake_dom.mjs";

const JS = new URL("../app/static/js/", import.meta.url);
const PAGE = readFileSync(new URL("../app/static/index.html", import.meta.url), "utf8");
const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

/** Run `body` with the page in `code`, and put English back after, whatever happens. */
function inLang(code, body) {
  useLang(code);
  try {
    return body();
  } finally {
    useLang(DEFAULT_LANG);
  }
}

// ---------- the tables ----------

test("English and Bahasa Melayu have exactly the same keys", () => {
  const [enKeys, msKeys] = [Object.keys(en).sort(), Object.keys(ms).sort()];
  assert.deepEqual(enKeys.filter((key) => !(key in ms)), [], "in en.js only");
  assert.deepEqual(msKeys.filter((key) => !(key in en)), [], "in ms.js only");
  assert.ok(enKeys.length > 300, `${enKeys.length} keys`);
});

test("every {placeholder} is in both languages, and no text is empty", () => {
  for (const key of Object.keys(en)) {
    for (const table of [en, ms]) assert.ok(typeof table[key] === "string" && table[key].trim().length > 0, key);
    assert.deepEqual(placeholders(ms[key]), placeholders(en[key]), key);
  }
});

test("the tables cannot be changed while the page runs", () => {
  assert.ok(Object.isFrozen(en) && Object.isFrozen(ms));
});

// ---------- t, the language and the link ----------

test("t fills placeholders and falls back to English, then to the key itself", () => {
  const tables = { en: { a: "Hello {name}", b: "Only English" }, ms: { a: "Hai {name}" } };
  assert.equal(translate(tables, "ms", "a", { name: "Ali" }), "Hai Ali");
  assert.equal(translate(tables, "ms", "b"), "Only English", "a key missing in ms reads in English");
  assert.equal(translate(tables, "ms", "nothing.here"), "nothing.here");
  assert.equal(translate(tables, "en", "a"), "Hello {name}", "a placeholder with no value shows, so it is noticed");
  assert.equal(translate(tables, "en", "a", { name: 0 }), "Hello 0");
  assert.equal(t("common.rpYears", { rp: 100 }), "1 in 100 years");
  assert.equal(inLang("ms", () => t("common.rpYears", { rp: 100 })), "1 dalam 100 tahun");
});

test("the language comes from the link, then the remembered choice, then English", () => {
  assert.deepEqual(LANGS, ["en", "ms"]);
  assert.equal(resolveLang({ search: "?lang=ms", stored: "en" }), "ms");
  assert.equal(resolveLang({ search: "?tab=cost&lang=en", stored: "ms" }), "en");
  assert.equal(resolveLang({ search: "?lang=fr", stored: "ms" }), "ms", "a language the page lacks is ignored");
  assert.equal(resolveLang({ search: "", stored: "ms" }), "ms");
  assert.equal(resolveLang({ search: "", stored: "xx" }), "en");
  assert.equal(resolveLang({}), "en");
  assert.equal(lang, "en", "under node there is no link and no storage: English, so every English test reads as before");
  assert.throws(() => useLang("fr"));
});

test("switching keeps the page's query and fragment and only sets lang", () => {
  assert.equal(linkInLang("ms", { search: "?tab=business&rp=100", hash: "#place=pt:3.02998,101.53667" }),
    "?tab=business&rp=100&lang=ms#place=pt:3.02998,101.53667");
  assert.equal(linkInLang("en", { search: "?lang=ms&tab=cost", hash: "" }), "?lang=en&tab=cost");
  assert.equal(linkInLang("ms", {}), "?lang=ms");
});

test("numbers and ringgit follow the language's locale", async () => {
  const { ringgit } = await import("../app/static/js/dom.js");
  assert.equal(ringgit(50000).replace(/\s/g, " "), "RM 50,000");
  assert.equal(inLang("ms", () => ringgit(1234567)).replace(/\s/g, " "), "RM 1,234,567");
});

// ---------- the page's own HTML ----------

/** A fake document: <html> and a body holding `children` (made after installFakeDom). */
function fakeDocument(...children) {
  const body = h("body", {}, ...children);
  return { documentElement: { lang: "en" }, querySelectorAll: (selector) => body.querySelectorAll(selector) };
}

test("applyStatic sets <html lang> and fills the marked text and attributes", () => {
  installFakeDom();
  const heading = h("h2", { "data-i18n": "footer.heading" }, "About this data");
  const input = h("input", { "data-i18n-attr": "placeholder:header.find; aria-label:ask.question" });
  const page = fakeDocument(heading, input);
  inLang("ms", () => applyStatic(page));
  assert.equal(page.documentElement.lang, "ms");
  assert.equal(heading.textContent, "Tentang data ini");
  assert.equal(input.getAttribute("placeholder"), "Cari perniagaan anda");
  assert.equal(input.getAttribute("aria-label"), "Soalan anda");
  applyStatic(page);
  assert.equal(page.documentElement.lang, "en");
  assert.equal(heading.textContent, "About this data");
});

test("the BM | EN buttons show the page's language as pressed and ask for the other", () => {
  installFakeDom();
  const bm = h("button", { "data-lang": "ms" }, "BM");
  const english = h("button", { "data-lang": "en" }, "EN");
  const picked = [];
  wireLangSwitch(fakeDocument(bm, english), (code) => picked.push(code));
  assert.equal(bm.getAttribute("aria-pressed"), "false");
  assert.equal(english.getAttribute("aria-pressed"), "true");
  bm.click();
  assert.deepEqual(picked, ["ms"]);
});

/** Each element of index.html, as [tag, attributes text, its text with tags removed and spaces collapsed]. */
const elements = (html, attribute) => [...html.matchAll(new RegExp(`<(\\w+)([^>]*\\s${attribute}="([^"]+)"[^>]*)>([\\s\\S]*?)</\\1>`, "g"))]
  .map(([, tag, attrs, key, inner]) => ({ tag, attrs, key, text: inner.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim() }));

test("index.html's English is en.js's, word for word, so the page reads the same before and after start-up", () => {
  const marked = elements(PAGE, "data-i18n");
  assert.ok(marked.length > 35, `${marked.length} marked elements`);
  for (const { key, text } of marked) assert.equal(text, en[key], key);
  for (const [, pairs] of PAGE.matchAll(/data-i18n-attr="([^"]+)"/g)) {
    for (const [attribute, key] of pairs.split(";").map((pair) => pair.split(":").map((part) => part.trim()))) {
      assert.ok(key in en, key);
      const tag = PAGE.match(new RegExp(`<[^>]*data-i18n-attr="${pairs}"[^>]*>`))[0];
      assert.equal(tag.match(new RegExp(`\\s${attribute}="([^"]*)"`))?.[1], en[key], `${attribute} of ${key}`);
    }
  }
});

const VOID = new Set(["input", "link", "meta", "img", "br", "use", "path", "circle", "rect", "source"]);

/** Every piece of text inside <header>, <nav>, <main> and <footer> that no element marks for translation (data-i18n,
 *  or translate="no" for a name), as [text, the open tags around it]. Text that JS fills later has no text here. */
function unmarkedText(html) {
  const found = [];
  const open = [];
  for (const [, closing, tag, attrs, selfClosing, text] of html.matchAll(/<(\/?)(\w+)([^>]*?)(\/?)>|([^<]+)/g)) {
    if (text !== undefined) {
      const words = text.replace(/\s+/g, " ").trim();
      const inPage = open.some((el) => ["header", "nav", "main", "footer"].includes(el.tag));
      const marked = open.some((el) => /\sdata-i18n="|\stranslate="no"/.test(el.attrs));
      if (words && inPage && !marked) found.push([words, open.map((el) => el.tag).join(">")]);
    } else if (closing) {
      while (open.length && open.pop().tag !== tag);
    } else if (!selfClosing && !VOID.has(tag.toLowerCase())) {
      open.push({ tag, attrs });
    }
  }
  return found;
}

test("every word index.html shows in the header, tabs, main part and footer is marked for translation", () => {
  assert.deepEqual(unmarkedText(PAGE), []);
  assert.deepEqual(unmarkedText("<main><p>Plain words</p><p data-i18n=\"x\">Marked</p></main>"), [["Plain words", "main>p"]],
    "the scan finds unmarked text");
});

test("every key the scripts name is in en.js", () => {
  const prefixes = new Set(Object.keys(en).map((key) => key.split(".")[0]));
  const scripts = readdirSync(JS).filter((name) => name.endsWith(".js"));
  for (const name of scripts) {
    const source = readFileSync(new URL(name, JS), "utf8");
    for (const [, key] of source.matchAll(/["`]([a-z]+\.[A-Za-z0-9.]+)["`]/g)) {
      if (prefixes.has(key.split(".")[0]) && !key.endsWith(".js")) assert.ok(key in en, `${name}: ${key}`);
    }
  }
});

// ---------- honest wording, in both languages ----------

/** English phrases that must keep their meaning in Bahasa Melayu: any key whose English has the first has the second. */
const KEPT = [
  [/\bin the model\b|\bmodelled\b/i, /dalam model/],
  [/not a forecast/, /bukan ramalan/],
  [/not a flood warning/, /bukan amaran banjir/],
  [/not a valuation/, /bukan penilaian/],
  [/not an official/, /bukan peta banjir rasmi|bukan peta rasmi/],
  [/not saved by this tool/, /tidak disimpan oleh alat ini/],
  [/never (your|its) coordinates/, /tidak pernah mendapat koordinat/],
  [/We do not keep it/, /Kami tidak menyimpannya/],
  [/about 300 m/, /kira-kira 300 m/],
  [/about 1 km/, /kira-kira 1 km/],
  [/not a promise/, /bukan jaminan/],
];

test("every depth stays 'in the model', and every limit and privacy claim is said in Bahasa Melayu too", () => {
  for (const [english, malay] of KEPT) {
    const keys = Object.keys(en).filter((key) => english.test(en[key]));
    assert.ok(keys.length > 0, `${english} is used`);
    for (const key of keys) assert.match(ms[key], malay, key);
  }
});

test("the Bahasa Melayu holds the key honest phrases word for word", () => {
  assert.match(ms["common.noWater"], /^tiada air dalam model$/);
  assert.equal(ms["cost.rough"], "Anggaran kasar, bukan penilaian atau angka insurans.");
  assert.match(ms["footer.money"], /anggaran kasar, bukan penilaian atau angka insurans/);
  assert.match(ms["overview.rainNote"], /Google Weather, bukan amaran banjir/);
  const dialog = ms["pin.dialogBody"];
  for (const claim of ["petak banjir 90 m", "hanya petak itu dihantar ke pelayan kami", "Kami tidak menyimpannya", "selepas tanda #",
    "OpenStreetMap", "kira-kira 300 m", "nama kawasan, kedalaman air banjir dan pusat pemindahan banjir terdekat berserta jaraknya",
    "tidak pernah mendapat koordinat anda", "Google Weather tidak mendapat lebih daripada petak anda yang dibundarkan kepada kira-kira 1 km"]) {
    assert.ok(dialog.includes(claim), claim);
  }
  assert.match(ms["voice.note"], /Google Gemini.*tidak disimpan oleh alat ini/);
  assert.match(ms["common.photoPrivacy"], /dikecilkan dalam pelayar anda, dihantar kepada Google Gemini, dan tidak disimpan/);
});

test("nothing promises safety or a flood, in either language", () => {
  for (const [key, text] of Object.entries(ms)) {
    assert.doesNotMatch(text, /selamat|\bakan banjir|\btidak akan banjir|\bpasti banjir/i, `ms ${key}`);
  }
  for (const [key, text] of Object.entries(en)) {
    assert.doesNotMatch(text, /\bsafe\b|will flood|won't flood|will not flood/i, `en ${key}`);
  }
});

test("the glossary is kept: flood sizes, chance and relief centre read the same everywhere in Bahasa Melayu", () => {
  for (const [key, text] of Object.entries(en)) {
    if (/1 in \{rp\} years|1 in 1?0?0 years/.test(text)) assert.match(ms[key], /1 dalam (\{rp\}|100) tahun/, key);
    if (/relief centre/i.test(text)) assert.match(ms[key], /pusat pemindahan/i, key);
  }
  assert.equal(ms["scenario.chance"], "Peluang {pct}% dalam {years} tahun");
  assert.doesNotMatch(Object.values(ms).join(" "), /\b(kamu|anda semua|nggak|gimana|banget|kantor)\b/, "not Indonesian");
});
