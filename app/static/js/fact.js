// One fact beside the drawing on My business, built so it reads at a glance: the label, the answer in a large line, a
// coloured tone with a chip that says it in two or three words, one short line, and the limits folded under "How to
// read this". The tone is about flooding only ("high", "some" or "low"), never a promise that a place stays dry.
import { h, icon } from "./dom.js";
import { formatNumber, t } from "./i18n.js";

export const TONES = Object.freeze(["high", "some", "low"]);

/** A fact card. `value` is the answer (text or nodes); `tone` one of TONES or null; `chip` its words; `lead` nodes that
 *  stay on show; `more` nodes folded away. Empty parts are left out, so a card with no limits has no fold. */
export function factCard({ iconName, label, value, tone = null, chip = null, lead = [], more = [], className = "" }) {
  const toneOk = TONES.includes(tone) ? tone : null;
  const folded = [more].flat().filter(Boolean);
  return h("section", { class: `fact${className ? ` ${className}` : ""}`, "data-tone": toneOk },
    h("div", { class: "fact-top" },
      h("h3", { class: "fact-label" }, icon(iconName), label),
      chip && h("span", { class: "fact-chip" }, chip)),
    value != null && h("p", { class: "fact-value" }, value),
    ...[lead].flat(),
    folded.length > 0 && h("details", { class: "fact-more" }, h("summary", {}, t("fact.more")), ...folded));
}

/** A group of facts under a small heading; null when none of them shows. */
export function factGroup(heading, facts) {
  const shown = facts.filter(Boolean);
  return shown.length ? h("section", { class: "fact-group" }, h("h2", { class: "fact-group-heading" }, heading), ...shown) : null;
}

/** The labels of the facts under `root` whose "How to read this" is open, so a rebuild can open them again. */
export const openFolds = (root) => new Set([...root.querySelectorAll(".fact")]
  .filter((fact) => fact.querySelector(".fact-more")?.getAttribute("open") != null)
  .map((fact) => fact.querySelector(".fact-label").textContent));

/** Open again the folds of the facts under `root` whose labels are in `labels` (from openFolds). */
export function reopenFolds(root, labels) {
  for (const fact of root.querySelectorAll(".fact")) {
    if (labels.has(fact.querySelector(".fact-label").textContent)) fact.querySelector(".fact-more")?.setAttribute("open", "");
  }
}

const KM_FROM_M = 1000;
/** "850 m" or "3.0 km": a distance as a person says it. */
export function distanceText(metres) {
  const whole = Math.round(metres);
  if (whole < KM_FROM_M) return t("common.metresAway", { m: formatNumber(whole) });
  return t("common.kmAway", { km: formatNumber(metres / KM_FROM_M, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) });
}
