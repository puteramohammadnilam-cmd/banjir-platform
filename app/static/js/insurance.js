// The "Insurance" tab: what a flood could cost this place in the model (from Flood cost's estimate), set beside a yearly
// price the owner was quoted for flood cover; how flood cover usually works in Malaysia; questions to ask an insurer; and
// help after a flood. It names no insurer and gives no verdict on a quote: analysing someone's cover or recommending a
// product is financial advice, which needs a licence. Every fact comes from 05_Raw_Data_Sources/shah_alam/insurance/FINDINGS.md.
import { CHANCE_YEARS, SCENARIOS, chanceWithin, h, icon, ringgit } from "./dom.js";
import { drawing } from "./drawing.js";
import { t } from "./i18n.js";
import { emptyState } from "./pick.js";

const WORKS = ["insurance.works1", "insurance.works2", "insurance.works3", "insurance.works4", "insurance.works5", "insurance.works6"];
const QUESTIONS = Array.from({ length: 12 }, (_, i) => `insurance.q${i + 1}`);
const LINKS = {
  raft: "https://www.bnm.gov.my/funds4sme",
  fmos: "https://www.fmos.org.my/en/our-scope/",
  calculator: "https://bcc.piam.org.my/",
};
const MAX_QUOTE_RM = 10_000_000;

const link = (href, text) => h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
const card = (heading, ...body) => h("section", { class: "surface insurance-card" }, h("h2", {}, heading), ...body);

/** What a shop's own fire or flood cover is about in one flood: its total without the vehicles parked there (motor
 *  cover) and the workers' pay (their loss), which Flood cost may also count. */
const shopLoss = (flood) => flood.total_rm - (flood.vehicles_rm ?? 0) - (flood.wages_rm ?? 0);

/** The model's figures from a Flood cost estimate, the shop's own: the yearly floor and the biggest flood's loss with
 *  its chance; leftOut when vehicles or workers' pay were counted there and are not here. */
export function riskFigures(result) {
  if (!result) return null;
  const rp = SCENARIOS.at(-1);
  const flood = result.per_flood[rp];
  return { yearly: result.expected_yearly_shop_loss_rm ?? result.expected_yearly_loss_rm, bad: shopLoss(flood), rp,
    pct: Math.round(chanceWithin(Number(rp), CHANCE_YEARS) * 100),
    leftOut: SCENARIOS.some((key) => shopLoss(result.per_flood[key]) !== result.per_flood[key].total_rm) };
}

/** Rows to set side by side: the quote (when typed) and the model's two figures, each with its share of the largest. */
export function compareRows(quoteRm, figures) {
  const rows = [
    quoteRm > 0 && { key: "quote", label: t("insurance.rowQuote"), rm: quoteRm },
    { key: "yearly", label: t("insurance.rowYearly"), rm: figures.yearly },
    { key: "bad", label: t("insurance.rowBad", { rp: figures.rp, pct: figures.pct }), rm: figures.bad },
  ].filter(Boolean);
  const largest = Math.max(...rows.map((row) => row.rm), 1);
  return rows.map((row) => ({ ...row, share: row.rm / largest }));
}

function compareTable(quoteRm, figures) {
  return h("ul", { class: "insurance-compare" }, compareRows(quoteRm, figures).map((row) =>
    h("li", { class: `is-${row.key}` },
      h("span", { class: "insurance-row-label" }, row.label),
      h("strong", {}, ringgit(row.rm)),
      h("span", { class: "insurance-bar", style: `--share: ${Math.round(row.share * 100)}%`, "aria-hidden": "true" }))));
}

/** The model's cost of a flood here, or what to do while there is none yet. */
function riskBody(estimate, figures, goto) {
  const change = h("button", { type: "button", class: "btn btn-secondary", onclick: () => goto("cost") }, icon("cash"), t("insurance.change"));
  if (!figures) return [h("p", { class: "muted" }, t(estimate?.busy ? "cost.working" : "insurance.noEstimate")), change];
  return [
    h("div", { class: "insurance-figures" },
      h("p", {}, h("span", { class: "kpi-figure" }, t("cost.atLeast", { rm: ringgit(figures.yearly) })), h("span", { class: "kpi-label" }, t("cost.yearly"))),
      h("p", {}, h("span", { class: "kpi-figure" }, ringgit(figures.bad)), h("span", { class: "kpi-label" }, t("insurance.badLabel", { rp: figures.rp, pct: figures.pct })))),
    estimate.assumed && h("p", { class: "cost-first-look" }, t("insurance.assumed")),
    h("p", { class: "hint" }, t(estimate.assumed ? "insurance.basisAssumed" : "insurance.basis")),
    figures.leftOut && h("p", { class: "hint" }, t("insurance.leftOut")), change,
  ].filter(Boolean);
}

/** The quote box and its comparison; the comparison redraws as the owner types. */
function quoteCard(state, figures) {
  const output = h("div", { "aria-live": "polite" });
  const input = h("input", { class: "field", type: "number", id: "insurance-quote", min: 0, max: MAX_QUOTE_RM, step: "any", inputmode: "decimal", value: state.quote || null });
  const draw = () => {
    state.quote = Math.min(Math.max(Number(input.value) || 0, 0), MAX_QUOTE_RM);
    output.replaceChildren(...(figures ? [compareTable(state.quote, figures), h("p", { class: "fineprint" }, t("insurance.notLikeForLike"))] : []));
  };
  input.addEventListener("input", draw);
  draw();
  return card(t("insurance.quoteHeading"),
    h("label", { class: "input-label", for: input.id }, t("insurance.quoteLabel"), h("div", { class: "money" }, input)),
    h("p", { class: "hint" }, t("insurance.quoteHint")), output);
}

/** The cards that are the same for every place: how cover works, questions to ask, help after a flood. */
function staticCards() {
  return [
    card(t("insurance.worksHeading"), drawing("c-cover"), h("ul", { class: "insurance-list" }, WORKS.map((key) => h("li", {}, t(key)))),
      h("p", { class: "insurance-example" }, t("insurance.example")),
      h("p", { class: "fineprint" }, t("insurance.worksSource"), " ", link(LINKS.calculator, t("insurance.calculator")))),
    card(t("insurance.askHeading"), h("ol", { class: "insurance-questions" }, QUESTIONS.map((key) => h("li", {}, t(key))))),
    card(t("insurance.helpHeading"),
      h("p", {}, t("insurance.help1"), " ", link(LINKS.raft, t("insurance.help1Link"))),
      h("p", {}, t("insurance.help2")),
      h("p", {}, t("insurance.help3"), " ", link(LINKS.fmos, t("insurance.help3Link")))),
  ];
}

/** Built once. render(place, estimate) draws it for a place and its Flood cost estimate ({busy, result}); with no place
 *  it shows the empty state (pick.js). goto(tab) opens another tab. The quote typed is kept per place for this visit. */
export function createInsurance(panel, { goto, onFind = () => {}, onCheckPoint = null }) {
  const empty = h("div");
  const head = h("header", { class: "view-head" });
  const body = h("div", { class: "insurance-grid" });
  const fixed = h("div", { class: "insurance-grid" }, ...staticCards());
  panel.replaceChildren(empty, head, body, fixed);
  const quotes = new Map();
  let shown = null;   // nothing drawn yet: the first render always draws, even with no place
  return {
    render(place, estimate) {
      if (shown && place === shown.place && estimate === shown.estimate) return;
      shown = { place, estimate };
      for (const part of [head, body, fixed]) part.hidden = !place;
      if (!place) {
        head.replaceChildren();   // so the tab's heading to focus is the empty state's, not a hidden old one
        if (!empty.children.length) empty.append(emptyState({ kicker: t("tab.insurance"), onFind, onCheckPoint }));
        return;
      }
      empty.replaceChildren();
      if (!quotes.has(place.id)) quotes.set(place.id, { quote: 0 });
      const figures = riskFigures(estimate?.result);
      head.replaceChildren(h("p", { class: "kicker" }, t("tab.insurance")),
        h("h1", { class: "view-title" }, place.is_point ? t("insurance.titlePoint") : t("insurance.title", { name: place.name })),
        h("p", { class: "muted" }, t("insurance.lead")));
      body.replaceChildren(card(t("insurance.riskHeading"), ...riskBody(estimate, figures, goto)), quoteCard(quotes.get(place.id), figures));
    },
  };
}
