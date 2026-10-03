// "Your flood plan" on My business (plan card G2). Gemini writes the steps from facts the server gives it (app/plan.py);
// the facts table and the contacts printed with the plan are ours, not the model's.
import { h, ringgit } from "./dom.js";

const WORDS = {
  ms: {
    before: "Sebelum banjir", warning: "Bila ada amaran", during: "Semasa banjir", after: "Selepas banjir", contacts: "Hubungi",
    size: "Saiz banjir", chance: "Peluang dalam 10 tahun", street: "Air di jalan", floor: "Air atas lantai", loss: "Kerugian kasar",
    dry: "tiada air dalam model", sizeText: (rp) => `1 dalam ${rp} tahun`,
    footer: "Ditulis oleh Gemini daripada angka di atas. Semak sebelum bergantung padanya. Angka ini dari model, bukan peta rasmi atau ramalan.",
  },
  en: {
    before: "Before a flood", warning: "When a warning comes", during: "During a flood", after: "After a flood", contacts: "Contacts",
    size: "Flood size", chance: "Chance within 10 years", street: "Water in the street", floor: "Water above the floor", loss: "Rough loss",
    dry: "no water in the model", sizeText: (rp) => `1 in ${rp} years`,
    footer: "Written by Gemini from the figures above. Check it before you rely on it. The figures are from a model, not an official map or a forecast.",
  },
};
const LANGUAGES = [["ms", "Bahasa Melayu"], ["en", "English"]];
const metres = (m, words) => (m > 0 ? `${m.toFixed(2)} m` : words.dry);

function factsTable(facts, words) {
  const hasLoss = facts.floods.some((flood) => flood.loss_rm != null);
  const heads = [words.size, words.chance, words.street, words.floor, ...(hasLoss ? [words.loss] : [])];
  return h("table", { class: "loss-table plan-facts" },
    h("thead", {}, h("tr", {}, heads.map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, facts.floods.map((flood) => h("tr", {},
      h("th", { scope: "row" }, words.sizeText(flood.size.match(/in (\d+)/)[1])), h("td", {}, `${flood.chance_in_10_years_pct}%`),
      h("td", {}, metres(flood.street_depth_m, words)), h("td", {}, metres(flood.water_above_floor_m, words)),
      ...(hasLoss ? [h("td", {}, flood.loss_rm == null ? "" : ringgit(flood.loss_rm))] : [])))));
}

/** A section of steps, or nothing when the server left it empty (it drops steps the model should not have written). */
const steps = (heading, list) => (list.length ? [h("h4", {}, heading), h("ol", {}, list.map((step) => h("li", {}, step)))] : []);

function sheet({ plan, facts, contacts, language }, onPrint) {
  const words = WORDS[language] ?? WORDS.en;
  return h("article", { class: "plan-sheet", lang: language === "ms" ? "ms" : "en" },
    h("h3", {}, plan.title), plan.summary ? h("p", {}, plan.summary) : null,
    h("p", { class: "muted small" }, [facts.place, facts.area].filter(Boolean).join(", ")),
    h("div", { class: "table-scroll" }, factsTable(facts, words)),
    ...steps(words.before, plan.before), ...steps(words.warning, plan.warning),
    ...steps(words.during, plan.during), ...steps(words.after, plan.after),
    h("h4", {}, words.contacts), h("ul", {}, contacts.map((c) => h("li", {}, h("strong", {}, c.name), `: ${c.how}`))),
    h("p", { class: "fineprint" }, words.footer),
    h("button", { type: "button", class: "btn btn-secondary plan-print", onclick: onPrint }, "Print or save as PDF"));
}

function languageChoice(onLanguage) {
  const radios = LANGUAGES.map(([value]) => h("input", { type: "radio", name: "plan-language", value, onchange: () => onLanguage(value) }));
  const node = h("fieldset", { class: "plan-language" }, h("legend", {}, "Language"),
    LANGUAGES.map(([, label], i) => h("label", { class: "choice" }, radios[i], label)));
  return { node, show: (language) => radios.forEach((radio, i) => { radio.checked = LANGUAGES[i][0] === language; }) };
}

/** The card. render(state, language) with state {busy, result, error}, `result` the answer of POST /api/plan.
 *  onWrite(language) asks for a plan, onLanguage(language) changes the choice, onPrint() prints the plan. The heading,
 *  the choice, the button and the live region are built once and changed in place, so focus and announcements stay. */
export function createPlanCard({ onWrite, onPrint, onLanguage }) {
  const choice = languageChoice(onLanguage);
  let language = "ms";
  const write = h("button", { type: "button", class: "btn btn-primary", onclick: () => onWrite(language) });
  const alert = h("p", { class: "fact-note", role: "alert" });
  const live = h("div", { "aria-live": "polite" });
  const node = h("section", { class: "surface plan-card", "aria-labelledby": "plan-heading" },
    h("h2", { id: "plan-heading", class: "small-heading" }, "Your flood plan"),
    h("p", { class: "hint" }, "Gemini writes a one-page plan for this place from the flood model's figures, and your cost estimate if you made one. Print it or save it as a PDF."),
    choice.node, write, alert, live);
  let shown = {};
  return {
    node,
    render(state, chosen) {
      if (state === shown.state && chosen === shown.chosen) return;
      const isNewResult = state?.result !== shown.state?.result || Boolean(state?.error) !== Boolean(shown.state?.error);
      shown = { state, chosen };
      language = chosen;
      choice.show(chosen);
      write.disabled = Boolean(state?.busy);
      write.textContent = state?.busy ? "Writing your plan…" : state?.result ? "Write it again" : "Write my flood plan";
      alert.textContent = state?.error ?? "";
      alert.hidden = !state?.error;
      if (isNewResult) live.replaceChildren(...(state?.result && !state.error ? [sheet(state.result, onPrint)] : []));
    },
  };
}
