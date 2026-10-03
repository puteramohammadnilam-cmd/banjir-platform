// "Your flood plan" on My business (plan card G2). Gemini writes the steps from facts the server gives it (app/plan.py);
// the facts table and the contacts printed with the plan are ours, not the model's.
import { h, ringgit } from "./dom.js";
import { lang, t } from "./i18n.js";

const WORDS = {
  ms: {
    before: "Sebelum banjir", warning: "Bila ada amaran", during: "Semasa banjir", after: "Selepas banjir", contacts: "Hubungi",
    size: "Saiz banjir", chance: "Peluang dalam 10 tahun", street: "Air di jalan", floor: "Air atas lantai", loss: "Kerugian kasar",
    dry: "tiada air dalam model", sizeText: (rp) => `1 dalam ${rp} tahun`,
    line: (size, m, chance) => `${size}: ${m > 0 ? `air ${m.toFixed(2)} m di jalan` : "tiada air di jalan"} dalam model; peluang dalam 10 tahun ${chance}%`,
    modelNote: "Angka daripada model banjir, bukan peta rasmi atau ramalan.",
    footer: "Ditulis oleh Gemini daripada angka di atas. Semak sebelum bergantung padanya. Angka ini dari model, bukan peta rasmi atau ramalan.",
  },
  en: {
    before: "Before a flood", warning: "When a warning comes", during: "During a flood", after: "After a flood", contacts: "Contacts",
    size: "Flood size", chance: "Chance within 10 years", street: "Water in the street", floor: "Water above the floor", loss: "Rough loss",
    dry: "no water in the model", sizeText: (rp) => `1 in ${rp} years`,
    line: (size, m, chance) => `${size}: ${m > 0 ? `${m.toFixed(2)} m of water` : "no water"} in the street in the model; chance within 10 years ${chance}%`,
    modelNote: "Figures from a flood model, not an official map or a forecast.",
    footer: "Written by Gemini from the figures above. Check it before you rely on it. The figures are from a model, not an official map or a forecast.",
  },
};
const LANGUAGES = [["ms", "Bahasa Melayu"], ["en", "English"]];
const metres = (m, words) => (m > 0 ? `${m.toFixed(2)} m` : words.dry);
const WHATSAPP = "https://wa.me/?text=";
const floodSize = (flood) => flood.size.match(/in (\d+)/)[1];

export const MAX_SHARE_CHARS = 3000;   // a WhatsApp link this long still opens; the steps are cut first, never the rest

const lines = (list) => list.filter((line) => line !== undefined && line !== null).join("\n").replace(/\n{3,}/g, "\n\n");

/** The plan as plain text, to send on WhatsApp or with the phone's share button: the same words as the sheet, with the
 *  model note near the top. A long plan loses its last steps (marked "…"), never the figures, contacts or footer. */
export function planText({ plan, facts, contacts, language }) {
  const words = WORDS[language] ?? WORDS.en;
  const head = lines([plan.title, plan.summary, [facts.place, facts.area].filter(Boolean).join(", "), words.modelNote, "",
    ...facts.floods.map((f) => words.line(words.sizeText(floodSize(f)), f.street_depth_m, f.chance_in_10_years_pct))]);
  const tail = lines([words.contacts, ...contacts.map((c) => `- ${c.name}: ${c.how}`), "", words.footer]);
  const steps = [["before", words.before], ["warning", words.warning], ["during", words.during], ["after", words.after]]
    .flatMap(([part, heading]) => (plan[part].length ? ["", heading, ...plan[part].map((step, i) => `${i + 1}. ${step}`)] : []));
  const room = MAX_SHARE_CHARS - head.length - tail.length - 4;
  let body = lines(steps);
  if (body.length > room) body = `${body.slice(0, Math.max(0, room - 1)).replace(/\n[^\n]*$/, "")}\n…`;
  return lines([head, body, "", tail]);
}

/** WhatsApp, and the phone's own share sheet where the browser has one. */
function shareButtons(result) {
  const text = planText(result);
  const share = globalThis.navigator?.share
    && h("button", { type: "button", class: "btn btn-secondary", onclick: () => navigator.share({ title: result.plan.title, text })
      .catch((error) => { if (error?.name !== "AbortError") window.open(whatsapp, "_blank", "noopener"); }) }, t("plan.share"));
  const whatsapp = `${WHATSAPP}${encodeURIComponent(text)}`;   // also where a failed share sheet sends it (not a cancel)
  return h("div", { class: "plan-share" },
    h("a", { class: "btn btn-secondary", href: whatsapp, target: "_blank", rel: "noopener noreferrer" }, t("plan.whatsapp")),
    ...(share ? [share] : []));
}

function factsTable(facts, words) {
  const hasLoss = facts.floods.some((flood) => flood.loss_rm != null);
  const heads = [words.size, words.chance, words.street, words.floor, ...(hasLoss ? [words.loss] : [])];
  return h("table", { class: "loss-table plan-facts" },
    h("thead", {}, h("tr", {}, heads.map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, facts.floods.map((flood) => h("tr", {},
      h("th", { scope: "row" }, words.sizeText(floodSize(flood))), h("td", {}, `${flood.chance_in_10_years_pct}%`),
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
    h("div", { class: "plan-actions", lang },   // the page's buttons, in the page's language
      h("button", { type: "button", class: "btn btn-secondary plan-print", onclick: onPrint }, t("plan.print")),
      shareButtons({ plan, facts, contacts, language })));
}

function languageChoice(onLanguage) {
  const radios = LANGUAGES.map(([value]) => h("input", { type: "radio", name: "plan-language", value, onchange: () => onLanguage(value) }));
  const node = h("fieldset", { class: "plan-language" }, h("legend", {}, t("plan.language")),
    LANGUAGES.map(([, label], i) => h("label", { class: "choice" }, radios[i], label)));
  return { node, show: (language) => radios.forEach((radio, i) => { radio.checked = LANGUAGES[i][0] === language; }) };
}

/** The card. render(state, language) with state {busy, result, error}, `result` the answer of POST /api/plan.
 *  onWrite(language) asks for a plan, onLanguage(language) changes the choice, onPrint() prints the plan. The heading,
 *  the choice, the button and the live region are built once and changed in place, so focus and announcements stay. */
export function createPlanCard({ onWrite, onPrint, onLanguage }) {
  const choice = languageChoice(onLanguage);
  let language = lang;   // until the first render: the page's own language
  const write = h("button", { type: "button", class: "btn btn-primary", onclick: () => onWrite(language) });
  const alert = h("p", { class: "fact-note", role: "alert" });
  const live = h("div", { "aria-live": "polite" });
  const node = h("section", { class: "surface plan-card", "aria-labelledby": "plan-heading" },
    h("h2", { id: "plan-heading", class: "small-heading" }, t("plan.heading")),
    h("p", { class: "hint" }, t("plan.hint")),
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
      write.textContent = t(state?.busy ? "plan.writing" : state?.result ? "plan.again" : "plan.write");
      alert.textContent = state?.error ?? "";
      alert.hidden = !state?.error;
      if (isNewResult) live.replaceChildren(...(state?.result && !state.error ? [sheet(state.result, onPrint)] : []));
    },
  };
}
