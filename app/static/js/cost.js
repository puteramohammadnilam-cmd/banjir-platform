// The "Flood cost" tab: the owner's own figures in, a rough ringgit loss out. The sums run on the server (app/costs.py).
import { SIZES, createCostForm } from "./cost-form.js";
import { CHANCE_YEARS, SCENARIOS, chanceWithin, depthText, h, icon, renderPicker, ringgit } from "./dom.js";
import { t } from "./i18n.js";
import { DEFAULT_RP, emptyState } from "./pick.js";
import { createStockCard } from "./stock.js";

const metresAbove = (m) => (m > 0 ? t("common.metres", { m: m.toFixed(2) }) : t("cost.none"));

/** The typical shop-size figure is one flat amount per flooded shop (JPS 2003), whatever the depth. */
const isFlat = (result) => SCENARIOS.every((rp) => result.per_flood[rp].damage_share == null);

/** A thin bar, as wide as `share` (0 to 1) of the cell, so the table's totals read as sizes. Decorative: the figure is
 *  beside it, and none for a flood that costs nothing. */
const lossBar = (share) => h("span", { class: "loss-bar", style: `--share: ${Math.round(share * 100)}%`, "aria-hidden": "true" });

/** Every flood size's loss, the one on show (rp) marked, each total with a bar against the largest. */
function lossTable(result, flat, rp) {
  const cols = flat ? ["cost.colSize", "cost.colWater", "cost.colTotal"] : ["cost.colSize", "cost.colWater", "cost.colDamage", "cost.colTrade", "cost.colTotal"];
  const largest = Math.max(...SCENARIOS.map((key) => result.per_flood[key].total_rm));
  return h("div", { class: "table-scroll" }, h("table", { class: `loss-table${flat ? " is-flat" : ""}` },
    h("caption", { class: "visually-hidden" }, t("cost.caption")),
    h("thead", {}, h("tr", {}, cols.map((key) => h("th", { scope: "col" }, t(key))))),
    h("tbody", {}, SCENARIOS.map((key) => {
      const flood = result.per_flood[key];
      const isChosen = key === rp;
      return h("tr", { class: isChosen ? "is-chosen" : null, "aria-current": isChosen ? "true" : null },
        h("th", { scope: "row" }, t("common.rpYears", { rp: key })), h("td", {}, metresAbove(flood.water_above_floor_m)),
        !flat && h("td", {}, ringgit(flood.direct_damage_rm)), !flat && h("td", {}, ringgit(flood.indirect_loss_rm)),
        h("td", { class: "loss-total" }, h("strong", {}, ringgit(flood.total_rm)), flood.total_rm > 0 && lossBar(flood.total_rm / largest)));
    }))));
}

/** The key figure split in two: damage and lost sales, as one bar and its two figures. None for a flood that costs nothing. */
function splitBar(flood) {
  if (!(flood.total_rm > 0)) return null;
  return h("div", { class: "split" },
    h("div", { class: "split-bar", "aria-hidden": "true" },
      h("span", { class: "split-damage", style: `flex-grow: ${flood.direct_damage_rm}` }),
      h("span", { class: "split-trade", style: `flex-grow: ${flood.indirect_loss_rm}` })),
    h("p", { class: "split-legend" },
      h("span", { class: "split-key is-damage" }, t("cost.splitDamage", { rm: ringgit(flood.direct_damage_rm) })),
      h("span", { class: "split-key is-trade" }, t("cost.splitTrade", { rm: ringgit(flood.indirect_loss_rm) }))));
}

/** The key figure: what the flood size on show (the page's "Size of flood", rp) costs, what it is made of, with its
 *  water in the model and its chance of coming at least once in the next CHANCE_YEARS, one line each. */
function floodBox(result, rp, basis) {
  const flood = result.per_flood[rp];
  const water = flood.depth_m > 0
    ? t("cost.floodWater", { street: depthText(flood.depth_m), floor: metresAbove(flood.water_above_floor_m) })
    : t("cost.floodDry");
  const chance = t("cost.floodChance", { pct: Math.round(chanceWithin(Number(rp), CHANCE_YEARS) * 100), years: CHANCE_YEARS });
  return h("div", { class: "figure-box is-key" },
    basis,
    h("p", { class: "kpi-figure" }, flood.total_rm > 0 ? t("cost.floodFigure", { rm: ringgit(flood.total_rm) }) : ringgit(0)),
    h("p", { class: "kpi-label" }, t("cost.floodLabel", { rp })),
    splitBar(flood),
    h("ul", { class: "figure-facts" }, h("li", {}, icon("clock"), chance), h("li", {}, icon("wave"), water)));
}

/** The average a year over every flood size. Floods more frequent than 1 in 10 years are not in the model
 *  (costs.expected_yearly), so it is a floor: "at least" says so, and why is under How this is worked out. */
const yearlyBox = (result) => h("div", { class: "figure-box" },
  h("p", { class: "kpi-figure" }, t("cost.atLeast", { rm: ringgit(result.expected_yearly_loss_rm) })),
  h("p", { class: "kpi-label" }, t("cost.yearly")));

function verdict(measure, years) {
  if (!measure) return null;
  const saving = t("cost.saving", { benefit: ringgit(measure.benefit_present_value_rm), years, cost: ringgit(measure.cost_rm) });
  const cm = measure.raise_cm;
  if (measure.worth_it == null) return h("div", { class: "verdict" }, h("strong", {}, t("cost.raise", { cm })), h("p", {}, saving));
  return h("div", { class: `verdict ${measure.worth_it ? "is-yes" : "is-no"}` },
    h("strong", {}, t(measure.worth_it ? "cost.raisePays" : "cost.raiseNotPays", { cm })),
    h("p", {}, saving));
}

const lowerFirst = (text) => text.charAt(0).toLocaleLowerCase() + text.slice(1);

/** What the answer was worked out from, as small tags on the key figure: the shop size whose typical figure it used,
 *  and that it is a first look the page made by itself. Null when it was the owner's own value, pressed for. */
function basisTags(inputs, isAssumed) {
  const size = SIZES.find(([key]) => key === inputs?.shop_size);
  const tags = [size && t("cost.tagSize", { size: lowerFirst(t(size[1])) }), isAssumed && t("cost.tagFirstLook")].filter(Boolean);
  return tags.length ? h("ul", { class: `cost-basis${isAssumed ? " is-first-look" : ""}` }, tags.map((tag) => h("li", {}, tag))) : null;
}

/** The answer, or the empty state with none. isAssumed marks the first look the tab works out when it opens; rp is
 *  the flood size on show, which the key figure is about. */
export function results(result, { isAssumed = false, rp = DEFAULT_RP } = {}) {
  if (!result) {
    return [h("div", { class: "cost-empty" }, icon("cash"), h("strong", {}, t("cost.emptyTitle")), h("p", {}, t("cost.emptyNote")))];
  }
  const { years, discount_rate: rate, present_value_rm: overYears } = result.loss_over_years;
  const flat = isFlat(result);
  return [
    h("div", { class: "headline-figures" }, floodBox(result, rp, basisTags(result.inputs, isAssumed)), yearlyBox(result)),
    lossTable(result, flat, rp),
    flat && h("p", { class: "fineprint" }, t("cost.flatNote")),
    verdict(result.measure, years),
    h("p", { class: "fineprint" }, t("cost.rough")),
    h("details", {}, h("summary", {}, t("cost.how")),   // the method's own words come from the server, in English
      h("p", {}, t("cost.yearlyNote", { rp: SCENARIOS[0], big: SCENARIOS.at(-1) })),
      h("p", {}, t("cost.overYearsLine", { rm: ringgit(overYears), years, pct: Math.round(rate * 100) })),
      h("p", {}, t("cost.damage", { text: result.basis.direct })), h("p", {}, t("cost.trade", { text: result.basis.indirect })),
      h("p", {}, result.method), h("p", {}, result.limits)),
  ].filter(Boolean);
}

/** The tab's heading: a point is a 90 m square someone picked, so it has no name. */
export const costTitle = (place) => (place.is_point ? t("cost.titlePoint") : t("cost.titleBusiness", { name: place.name }));

/** After the owner presses Estimate the answer may be off screen (on a phone it sits above the form): bring it in. */
function bringIntoView(node) {
  const top = node.getBoundingClientRect?.().top;
  if (top == null || (top >= 0 && top < globalThis.innerHeight)) return;
  const isCalm = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  node.scrollIntoView?.({ block: "start", behavior: isCalm ? "auto" : "smooth" });
}

/** One place's estimate as main.js keeps it. `assumed` marks the first look the tab works out by itself when it opens:
 *  the flood plan leaves it out (plan.planFigures), and if it fails nothing is said, as the owner asked for nothing. */
export const estimateState = {
  busy: (before, isAssumed) => ({ busy: true, result: before?.result, assumed: Boolean(isAssumed || before?.assumed) }),
  done: (result, isAssumed) => ({ result, assumed: isAssumed }),
  failed: (before, message, isAssumed) =>
    (isAssumed ? { assumed: true } : { error: message, result: before?.result, assumed: Boolean(before?.assumed) }),
};

/** Whether to work out a first look now: Flood cost or Insurance (which shows its figures) is on show with a place that
 *  has no estimate yet. */
export const needsFirstLook = (state, place) => ["cost", "insurance"].includes(state.tab) && Boolean(place) && !state.estimates[state.placeKey];

/** Whether `next` answers the owner's own press of Estimate: not a first look, and not a failure. */
export const isOwnAnswer = (previous, next) => Boolean(previous?.busy && next?.result && !next.busy && !next.assumed && !next.error);

/** Draws one place's estimate for the flood size on show (rp): the button, the error under the form, and the answer, or a
 *  working line while there is none yet. An answer to the owner's own press gets a short line for screen readers and is
 *  brought into view. */
function showEstimate({ output, status, submit, error }, estimate, { isAnswered, isNewEstimate, rp }) {
  submit.disabled = Boolean(estimate?.busy);
  submit.textContent = t(estimate?.busy ? "cost.working" : "cost.submit");
  // another size of flood only redraws the answer: the form's own message (a measure half given) stays
  if (isNewEstimate && !estimate?.busy) error.textContent = estimate?.error ?? "";
  const isWaiting = estimate?.busy && !estimate.result;
  const wasOpen = Boolean(output.querySelector("details")?.open);   // "How this is worked out" stays as it was
  output.replaceChildren(...(isWaiting ? [h("p", { class: "muted" }, t("cost.working"))]
    : results(estimate?.result, { isAssumed: Boolean(estimate?.assumed), rp })));
  if (wasOpen) output.querySelector("details")?.setAttribute("open", "");
  const flood = isAnswered && estimate.result.per_flood[rp];
  status.textContent = flood ? `${t("cost.output")}: ${ringgit(flood.total_rm)} ${t("cost.floodLabel", { rp })}` : "";
  if (isAnswered) bringIntoView(output);
}

/** The tab's heading: the title, the size of flood (the same choice as on the Area overview and My business), and a
 *  line only screen readers get, saying when the owner's estimate is in. The answer itself is not a live region: a first
 *  look on every place would be read out whole. */
function buildHead() {
  const title = h("h1", { class: "view-title" });
  const picker = h("div", { class: "cost-picker" });
  const status = h("p", { class: "visually-hidden", role: "status" });
  return { title, picker, status, node: h("header", { class: "view-head" }, h("p", { class: "kicker" }, t("cost.kicker")), title, picker, status) };
}

/** The empty state while nothing is picked; the form and its figures (`parts`), kept as they were, once a place is. */
function showEmpty(empty, parts, isEmpty, { onFind, onCheckPoint }) {
  if (!isEmpty) empty.replaceChildren();
  else if (!empty.children.length) empty.append(emptyState({ kicker: t("cost.kicker"), onFind, onCheckPoint }));
  for (const part of parts) part.hidden = isEmpty;
}

/** Builds the form once. Each business or point keeps its own figures, so switching never mixes them up.
 *  onPick(rp) picks the size of flood for the whole page, as the Area overview's picker does; floodExample(place) is
 *  the month of a past flood bigger than the model shows there, for the note under the picker, or null.
 *  onStockPhoto(file, floorCm) sends a photo of the stock with the floor height in the form; isReady is false when the
 *  build has no Gemini key, which switches the photo off. With no place picked the
 *  tab shows the empty state (pick.js), with onFind and onCheckPoint behind its buttons. */
export function createCost(panel, { onEstimate, onPick = () => {}, floodExample = () => null, onStockPhoto = () => {}, onFind = () => {}, onCheckPoint = null, isReady = true }) {
  const head = buildHead();
  const form = createCostForm(onEstimate);
  const stock = createStockCard({ onPhoto: (file) => file && onStockPhoto(file, form.floorCm()), onUse: (value) => form.useValue(value), isReady });
  const output = h("section", { class: "surface cost-results", "aria-label": t("cost.output") });
  const empty = h("div");   // first, so that its h1 is the one goto() focuses while it is on show
  // the answer comes first, so a phone shows it before the form; views.css puts it beside the form on wide screens
  const parts = [head.node, h("div", { class: "cost-grid" }, output, form.node, stock.node)];
  panel.replaceChildren(empty, ...parts);
  let shownId = null;
  let shownEstimate;
  let shownRp;

  return {
    /** photoFloorCm fills the floor field unless the owner has typed their own for this place. estimate is the place's
     *  estimate (estimateState), stockState its stock photo ({busy, result, error}) and rp the flood size on show, which
     *  the picker in the heading changes for every tab (onPick). */
    render(place, photoFloorCm, estimate, stockState, rp = DEFAULT_RP) {
      showEmpty(empty, parts, !place, { onFind, onCheckPoint });
      if (!place) return;
      stock.render(stockState, rp);
      const isNewPlace = place.id !== shownId;
      if (isNewPlace) {
        if (shownId) form.save(shownId);
        form.restore(place.id);
        shownId = place.id;
        head.title.textContent = costTitle(place);
      }
      form.useFloor(photoFloorCm);
      const isNewRp = rp !== shownRp;
      shownRp = rp;
      if (isNewRp || isNewPlace) renderPicker(head.picker, rp, onPick, floodExample(place));   // the note is the place's area's
      const isNewEstimate = isNewPlace || estimate !== shownEstimate;
      if (isNewEstimate || isNewRp) {
        const isAnswered = !isNewPlace && isOwnAnswer(shownEstimate, estimate);
        shownEstimate = estimate;
        showEstimate({ output, status: head.status, submit: form.submit, error: form.error }, estimate, { isAnswered, isNewEstimate, rp });
      }
    },
    /** What the form would send now, or null while it holds a problem. */
    figures: () => form.figures(),
  };
}
