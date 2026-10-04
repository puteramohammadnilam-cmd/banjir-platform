// The page's language: English (the default) or Bahasa Melayu. It is chosen once, as the page starts: ?lang= in the
// link, else the last choice remembered in this browser, else English. Switching loads the page again with ?lang=, so
// every module reads the language once and nothing has to be redrawn in place. The words are in strings/en.js and
// strings/ms.js, by key; t(key, vars) fills {name} placeholders. No DOM is needed here except in applyStatic and
// wireLangSwitch, so node can test the rest (tests/i18n.test.mjs).
import en from "./strings/en.js";
import ms from "./strings/ms.js";

export const LANGS = Object.freeze(["en", "ms"]);
export const DEFAULT_LANG = "en";
const TABLES = Object.freeze({ en, ms });
const STORE_KEY = "banjir-check-lang";
const NUMBER_LOCALE = Object.freeze({ en: "en-MY", ms: "ms-MY" });
const DATE_LOCALE = Object.freeze({ en: "en-GB", ms: "ms-MY" });
const isLang = (value) => LANGS.includes(value);

/** The language for a link's query and the remembered choice: the link's ?lang= when valid, else the stored one when
 *  valid, else English. */
export function resolveLang({ search = "", stored = null } = {}) {
  const asked = new URLSearchParams(search).get("lang");
  if (isLang(asked)) return asked;
  return isLang(stored) ? stored : DEFAULT_LANG;
}

/** Storage can be missing, blocked or full (a private window): the choice then lasts only as long as the link has it. */
function readStored() {
  try {
    return globalThis.localStorage?.getItem(STORE_KEY) ?? null;
  } catch {
    return null;
  }
}

function remember(code) {
  try {
    globalThis.localStorage?.setItem(STORE_KEY, code);
  } catch {
    // not remembered: the link's ?lang= still carries the choice
  }
}

/** Which language the link itself asks for, or null. */
const askedInLink = () => {
  const asked = new URLSearchParams(globalThis.location?.search ?? "").get("lang");
  return isLang(asked) ? asked : null;
};

export let lang = resolveLang({ search: globalThis.location?.search ?? "", stored: readStored() });
if (askedInLink()) remember(lang);   // a link in BM keeps the page in BM on the next visit, too

/** Sets the language without loading the page again: for tests, which build views under node in either language. */
export function useLang(code) {
  if (!isLang(code)) throw new Error(`Unknown language: ${code}`);
  lang = code;
}

/** The text for `key` in `tables[code]`, English when the key is missing there, the key itself when it is missing
 *  everywhere. {name} placeholders take vars.name; one with no value is left as it is, so it shows. */
export function translate(tables, code, key, vars = {}) {
  const text = tables[code]?.[key] ?? tables[DEFAULT_LANG]?.[key];
  if (text === undefined) return key;
  return text.replace(/\{(\w+)\}/g, (whole, name) => (vars[name] === undefined ? whole : String(vars[name])));
}

/** The text for `key` in the page's language (see translate). */
export const t = (key, vars = {}) => translate(TABLES, lang, key, vars);

/** A word an area's data gives in each language ({en, ms}, such as its word for a section), in the page's language,
 *  else English; lower-cased for the middle of a sentence. "" when the data gives none. */
export function dataWord(words, { lower = false } = {}) {
  const word = words?.[lang] ?? words?.[DEFAULT_LANG] ?? "";
  return lower ? word.toLocaleLowerCase(lang) : word;
}

/** A number with the page's grouping, as Intl gives it for Malaysia. */
export const formatNumber = (value, options = {}) => Number(value).toLocaleString(NUMBER_LOCALE[lang], options);

/** The locale for Intl number formats (ringgit) and for dates. */
export const numberLocale = () => NUMBER_LOCALE[lang];
export const dateLocale = () => DATE_LOCALE[lang];

/** The link for this page in another language: the same query and fragment, with lang= set. */
export function linkInLang(code, { search = "", hash = "" } = {}) {
  const query = new URLSearchParams(search);
  query.set("lang", code);
  return `?${query.toString()}${hash}`;
}

/** Remember the choice and load the page again in that language. The state of the page lives in its link. */
export function setLang(code) {
  if (!isLang(code) || code === lang) return;
  remember(code);
  location.assign(linkInLang(code, location));
}

/** Fill the page's own HTML: data-i18n="key" sets an element's text, data-i18n-attr="attr:key;attr:key" its
 *  attributes (placeholder, aria-label, title, content). `root` is the document, which also gets <html lang>. */
export function applyStatic(root) {
  if (root.documentElement) root.documentElement.lang = lang;
  for (const element of root.querySelectorAll("[data-i18n]")) element.textContent = t(element.getAttribute("data-i18n"));
  for (const element of root.querySelectorAll("[data-i18n-attr]")) {
    for (const pair of element.getAttribute("data-i18n-attr").split(";")) {
      const [attribute, key] = pair.split(":").map((part) => part.trim());
      if (attribute && key) element.setAttribute(attribute, t(key));
    }
  }
}

/** The header's BM | EN buttons (data-lang="ms" / "en"): the page's language is pressed; the other reloads in it. */
export function wireLangSwitch(root, onPick = setLang) {
  for (const button of root.querySelectorAll("[data-lang]")) {
    const code = button.getAttribute("data-lang");
    button.setAttribute("aria-pressed", String(code === lang));
    button.addEventListener("click", () => onPick(code));
  }
}
