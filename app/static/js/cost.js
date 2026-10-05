// The "Flood cost" tab: the owner's own figures in, a rough ringgit loss out. The sums run on the server (app/costs.py).
import { CHANCE_YEARS, SCENARIOS, band, chanceWithin, depthText, h, icon, ringgit } from "./dom.js";
import { t } from "./i18n.js";
import { DEFAULT_RP, emptyState } from "./pick.js";
import { createStockCard } from "./stock.js";

// The browser's own range checks, mirroring floodtools.ESTIMATE_MAX. The server checks again.
const MAX = { value_at_risk_rm: 50_000_000, floor_height_cm: 300, daily_takings_rm: 1_000_000, closed_days: 365, raise_cm: 300, measure_cost_rm: 50_000_000 };
const SIZES = [["small", "cost.sizeSmall"], ["medium", "cost.sizeMedium"], ["complex", "cost.sizeComplex"]];
// The form starts ready to answer: a typical figure for a medium shop, so one press of Estimate gives a result. The owner
// who knows their stock's worth switches to their own value.
const DEFAULT_MODE = "size";
const DEFAULT_SIZE = "medium";

function numberField(name, label, unit, extra = {}) {
  const input = h("input", { class: "field", type: "number", name, id: `cost-${name}`, min: 0, max: MAX[name], step: "any", inputmode: "decimal", ...extra });
  const box = unit === "RM" ? h("div", { class: "money" }, input) : h("div", { class: "unit", "data-unit": unit }, input);
  return { input, node: h("label", { class: "input-label", for: input.id }, label, box) };
}

const metresAbove = (m) => (m > 0 ? t("common.metres", { m: m.toFixed(2) }) : t("cost.none"));

/** The typical shop-size figure is one flat amount per flooded shop (JPS 2003), whatever the depth. */
const isFlat = (result) => SCENARIOS.every((rp) => result.per_flood[rp].damage_share == null);

function lossTable(result, flat) {
  const cols = flat ? ["cost.colSize", "cost.colWater", "cost.colTotal"] : ["cost.colSize", "cost.colWater", "cost.colDamage", "cost.colTrade", "cost.colTotal"];
  return h("div", { class: "table-scroll" }, h("table", { class: `loss-table${flat ? " is-flat" : ""}` },
    h("caption", { class: "visually-hidden" }, t("cost.caption")),
    h("thead", {}, h("tr", {}, cols.map((key) => h("th", { scope: "col" }, t(key))))),
    h("tbody", {}, SCENARIOS.map((rp) => {
      const flood = result.per_flood[rp];
      return h("tr", {}, h("th", { scope: "row" }, t("common.rpYears", { rp })), h("td", {}, metresAbove(flood.water_above_floor_m)),
        !flat && h("td", {}, ringgit(flood.direct_damage_rm)), !flat && h("td", {}, ringgit(flood.indirect_loss_rm)),
        h("td", {}, h("strong", {}, ringgit(flood.total_rm))));
    }))));
}

/** With the flat figure, one line says what any flood that reaches the floor costs, and how to make depth count. */
function flatLine(result) {
  const wettest = result.per_flood[SCENARIOS.at(-1)];
  if (!wettest.direct_damage_rm) return null;
  return h("div", { class: "flat-line" },
    h("p", {}, h("strong", {}, t("cost.flatLine", { total: ringgit(wettest.total_rm) })), " ",
      t("cost.flatParts", { damage: ringgit(wettest.direct_damage_rm), trade: ringgit(wettest.indirect_loss_rm) })),
    h("p", { class: "fineprint" }, t("cost.flatNote")));
}

/** The most frequent flood size that costs the shop anything, as {rp, total}, or null when none does. */
function firstCostlyFlood(result) {
  const rp = [...SCENARIOS].sort((a, b) => Number(a) - Number(b)).find((key) => result.per_flood[key].total_rm > 0);
  return rp ? { rp, total: result.per_flood[rp].total_rm } : null;
}

/** The second headline: the chance of a costly flood within the next CHANCE_YEARS, not a discounted sum. */
function chanceBox(result) {
  const costly = firstCostlyFlood(result);
  if (!costly) return h("div", { class: "figure-box" }, h("p", { class: "kpi-figure" }, "–"), h("p", { class: "kpi-label" }, t("cost.noCostly")));
  const pct = Math.round(chanceWithin(Number(costly.rp), CHANCE_YEARS) * 100);
  return h("div", { class: "figure-box" }, h("p", { class: "kpi-figure" }, t("cost.chanceFigure", { pct })),
    h("p", { class: "kpi-label" }, t("cost.chanceLabel", { years: CHANCE_YEARS })),
    h("p", { class: "kpi-note" }, t("cost.chanceNote", { rp: costly.rp, total: ringgit(costly.total) })));
}

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

/** What the answer was worked out from: a first look the page made by itself, and the shop size whose typical figure
 *  it used. Null when it was the owner's own value, pressed for. */
function basisLine(inputs, isAssumed) {
  const size = SIZES.find(([key]) => key === inputs?.shop_size);
  const words = [size && t("cost.forSize", { size: lowerFirst(t(size[1])) }), isAssumed && t("cost.firstLook")].filter(Boolean);
  return words.length ? h("p", { class: `cost-basis${isAssumed ? " is-first-look" : ""}` }, words.join(" ")) : null;
}

/** The answer, or the empty state with none. isAssumed marks the first look the tab works out when it opens. */
export function results(result, { isAssumed = false } = {}) {
  if (!result) {
    return [h("div", { class: "cost-empty" }, icon("cash"), h("strong", {}, t("cost.emptyTitle")), h("p", {}, t("cost.emptyNote")))];
  }
  const { years, discount_rate: rate, present_value_rm: overYears } = result.loss_over_years;
  const flat = isFlat(result);
  return [
    basisLine(result.inputs, isAssumed),
    h("div", { class: "headline-figures" },
      // floods more frequent than 1 in 10 years are not in the model (costs.expected_yearly), so this is a floor
      h("div", { class: "figure-box is-key" }, h("p", { class: "kpi-figure" }, t("cost.atLeast", { rm: ringgit(result.expected_yearly_loss_rm) })),
        h("p", { class: "kpi-label" }, t("cost.yearly")), h("p", { class: "kpi-note" }, t("cost.yearlyNote", { rp: SCENARIOS[0], big: SCENARIOS.at(-1) }))),
      chanceBox(result)),
    flat && flatLine(result),
    lossTable(result, flat),
    verdict(result.measure, years),
    h("p", { class: "fineprint" }, t("cost.rough")),
    h("details", {}, h("summary", {}, t("cost.how")),   // the method's own words come from the server, in English
      h("p", {}, t("cost.overYearsLine", { rm: ringgit(overYears), years, pct: Math.round(rate * 100) })),
      h("p", {}, t("cost.damage", { text: result.basis.direct })), h("p", {}, t("cost.trade", { text: result.basis.indirect })),
      h("p", {}, result.method), h("p", {}, result.limits)),
  ].filter(Boolean);
}

const FLOOR_NOTE = t("cost.floorNote");
const number = (field) => Number(field.input.value || 0);

/** The tab's heading: a point is a 90 m square someone picked, so it has no name. */
export const costTitle = (place) => (place.is_point ? t("cost.titlePoint") : t("cost.titleBusiness", { name: place.name }));

/** The modelled water at the street in each flood size, as chips in the map's depth colours. */
function depthChips(place) {
  const chip = (rp) => {
    const level = band(place.depth_m[rp]);
    return h("span", { class: `depth-chip${level ? ` band-${level}` : ""}` }, t("cost.depthChip", { rp, depth: depthText(place.depth_m[rp]) }));
  };
  return [h("span", { class: "cost-depths-label" }, t("cost.depthsLabel")), ...SCENARIOS.map(chip)];
}

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

/** Whether to work out a first look now: Flood cost is on show with a place that has no estimate yet. */
export const needsFirstLook = (state, place) => state.tab === "cost" && Boolean(place) && !state.estimates[state.placeKey];

/** Whether `next` answers the owner's own press of Estimate: not a first look, and not a failure. */
export const isOwnAnswer = (previous, next) => Boolean(previous?.busy && next?.result && !next.busy && !next.assumed && !next.error);

/** Draws one place's estimate: the button, the error under the form, and the answer, or a working line while there is
 *  none yet. An answer to the owner's own press gets a short line for screen readers and is brought into view. */
function showEstimate({ output, status, submit, error }, estimate, isAnswered) {
  submit.disabled = Boolean(estimate?.busy);
  submit.textContent = t(estimate?.busy ? "cost.working" : "cost.submit");
  if (!estimate?.busy) error.textContent = estimate?.error ?? "";
  const isWaiting = estimate?.busy && !estimate.result;
  output.replaceChildren(...(isWaiting ? [h("p", { class: "muted" }, t("cost.working"))]
    : results(estimate?.result, { isAssumed: Boolean(estimate?.assumed) })));
  const yearly = isAnswered && t("cost.atLeast", { rm: ringgit(estimate.result.expected_yearly_loss_rm) });
  status.textContent = yearly ? `${t("cost.output")}: ${yearly} ${t("cost.yearly")}` : "";
  if (isAnswered) bringIntoView(output);
}

/** The form's inputs, built once: the figures, the shop size choice and the optional measure, with the error line and
 *  the submit button. */
function buildFields() {
  const size = h("select", { class: "field", name: "shop_size", id: "cost-shop_size" },
    h("option", { value: "" }, t("cost.choose")), SIZES.map(([key, text]) => h("option", { value: key }, t(text))));
  size.value = DEFAULT_SIZE;
  const raise = numberField("raise_cm", t("cost.raiseBy"), "cm");
  const measureCost = numberField("measure_cost_rm", t("cost.measureCost"), "RM");
  const fields = {
    numbers: {
      value: numberField("value_at_risk_rm", t("cost.value"), "RM", { min: 1, required: true, placeholder: "50000" }),
      floor: numberField("floor_height_cm", t("cost.floor"), "cm", { placeholder: "0" }),
      takings: numberField("daily_takings_rm", t("cost.takings"), "RM"),
      days: numberField("closed_days", t("cost.days"), t("cost.unitDays")),
      raise,
      measureCost,
    },
    size,
    sizeBox: h("label", { class: "input-label", for: size.id, hidden: true }, t("cost.myShop"), size),
    floorNote: h("p", { class: "hint" }, FLOOR_NOTE),
    valueNote: h("p", { class: "hint", "aria-live": "polite" }),
    measure: h("details", {}, h("summary", {}, t("cost.measure")),
      h("p", { class: "hint" }, t("cost.measureHint")),
      h("div", { class: "pair" }, raise.node, measureCost.node)),
    error: h("p", { class: "form-error", role: "alert" }),
    submit: h("button", { type: "submit", class: "btn btn-primary" }, t("cost.submit")),
  };
  setMode(fields, DEFAULT_MODE);
  return fields;
}

/** Show the value field or the shop size choice, as `mode` ("value" or "size") asks. */
function setMode({ numbers, size, sizeBox }, mode) {
  numbers.value.node.hidden = mode !== "value";
  numbers.value.input.required = mode === "value";
  sizeBox.hidden = mode !== "size";
  size.required = mode === "size";
}

/** The figures to send, or the problem to show. The server checks these too; saying so here keeps its wording, written
 *  for the AI model, out of the form. */
function readFigures(form, { numbers, size }) {
  const byValue = form.elements.mode.value === "value";
  const [raiseCm, costRm] = [number(numbers.raise), number(numbers.measureCost)];
  if ((raiseCm > 0) !== (costRm > 0)) return { error: t("cost.errBoth") };
  if (raiseCm > 0 && !byValue) return { error: t("cost.errSize") };
  return {
    figures: {
      value_at_risk_rm: byValue ? number(numbers.value) : 0, shop_size: byValue ? "" : size.value,
      floor_height_cm: number(numbers.floor), daily_takings_rm: number(numbers.takings), closed_days: number(numbers.days),
      raise_cm: raiseCm, measure_cost_rm: costRm,
    },
  };
}

/** The form: stock, shop, lost trade and the optional measure. Submitting checks it and calls onEstimate(figures). */
function buildForm(fields, onEstimate) {
  const { numbers, sizeBox, floorNote, valueNote, measure, error, submit } = fields;
  const modeChoice = (mode, text, checked) => h("label", { class: "choice" },
    h("input", { type: "radio", name: "mode", value: mode, checked, onchange: () => setMode(fields, mode) }), text);
  const form = h("form", { class: "surface cost-form", onsubmit: (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const read = readFigures(form, fields);
    error.textContent = read.error ?? "";
    if (read.figures) onEstimate(read.figures);
  } },
  h("fieldset", {}, h("legend", {}, t("cost.stockLegend")),
    h("p", { class: "hint" }, t("cost.stockHint")),
    modeChoice("value", t("cost.modeValue"), DEFAULT_MODE === "value"),
    modeChoice("size", t("cost.modeSize"), DEFAULT_MODE === "size"),
    numbers.value.node, valueNote, sizeBox),
  h("fieldset", {}, h("legend", {}, t("cost.shopLegend")), numbers.floor.node, floorNote),
  h("fieldset", {}, h("legend", {}, t("cost.tradeLegend")),
    h("p", { class: "hint" }, t("cost.tradeHint")),
    h("div", { class: "pair" }, numbers.takings.node, numbers.days.node)),
  measure, error, submit);
  numbers.floor.input.addEventListener("input", () => { numbers.floor.input.dataset.touched = "true"; });
  return form;
}

/** What was typed for each place, by its id, so going to another business or point and back never mixes figures up. */
function createDrafts(form, fields) {
  const { numbers, size, measure, floorNote, valueNote, error } = fields;
  const drafts = new Map();
  const snapshot = () => ({
    mode: form.elements.mode.value, size: size.value, open: measure.open, note: floorNote.textContent, valueNote: valueNote.textContent,
    touched: numbers.floor.input.dataset.touched === "true",
    ...Object.fromEntries(Object.entries(numbers).map(([key, field]) => [key, field.input.value])),
  });
  function restore(draft) {
    for (const [key, field] of Object.entries(numbers)) field.input.value = draft?.[key] ?? "";
    size.value = draft?.size ?? DEFAULT_SIZE;
    form.elements.mode.value = draft?.mode ?? DEFAULT_MODE;
    setMode(fields, form.elements.mode.value);
    measure.open = draft?.open ?? false;
    if (draft?.touched) numbers.floor.input.dataset.touched = "true";
    else delete numbers.floor.input.dataset.touched;
    floorNote.textContent = draft?.note ?? FLOOR_NOTE;
    valueNote.textContent = draft?.valueNote ?? "";
    error.textContent = "";
  }
  return { save: (id) => drafts.set(id, snapshot()), restore: (id) => restore(drafts.get(id)) };
}

/** "Use these figures" from the stock photo: the value goes in the form, said to be Gemini's guess, and focus goes to
 *  it so the owner sees what changed. */
function useStockValue(form, fields, value) {
  form.elements.mode.value = "value";
  setMode(fields, "value");
  fields.numbers.value.input.value = String(value);
  fields.valueNote.textContent = t("cost.fromStock");
  fields.numbers.value.input.focus();
}

/** The tab's heading: the title, the modelled water as chips, and a line only screen readers get, saying when the
 *  owner's estimate is in. The answer itself is not a live region: a first look on every place would be read out whole. */
function buildHead() {
  const title = h("h1", { class: "view-title" });
  const depths = h("p", { class: "cost-depths" });
  const status = h("p", { class: "visually-hidden", role: "status" });
  return { title, depths, status, node: h("header", { class: "view-head" }, h("p", { class: "kicker" }, t("cost.kicker")), title, depths, status) };
}

/** The floor from the shop-front photo goes in the form, unless the owner has typed their own for this place. */
function useFloorFromPhoto({ numbers, floorNote }, photoFloorCm) {
  const { input } = numbers.floor;
  if (photoFloorCm == null || input.dataset.touched || input.value === String(photoFloorCm)) return;
  input.value = String(photoFloorCm);
  floorNote.textContent = t("cost.fromPhoto");
}

/** The figures the form would send now, or null while it holds a problem (a required value left empty, a measure half
 *  given): what the tab works out by itself when it opens on a place. */
function formFigures(form, fields) {
  if (form.checkValidity && !form.checkValidity()) return null;
  return readFigures(form, fields).figures ?? null;
}

/** Builds the form once. Each business or point keeps its own figures, so switching never mixes them up.
 *  onStockPhoto(file, floorCm) sends a photo of the stock with the floor height in the form; isReady is false when the
 *  build has no Gemini key, which switches the photo off. With no place picked the
 *  tab shows the empty state (pick.js), with onFind and onCheckPoint behind its buttons. */
export function createCost(panel, { onEstimate, onStockPhoto = () => {}, onFind = () => {}, onCheckPoint = null, isReady = true }) {
  const head = buildHead();
  const fields = buildFields();
  const form = buildForm(fields, onEstimate);
  const stock = createStockCard({ onPhoto: (file) => file && onStockPhoto(file, number(fields.numbers.floor)), onUse: (value) => useStockValue(form, fields, value), isReady });
  const output = h("section", { class: "surface cost-results", "aria-label": t("cost.output") });
  const empty = h("div");   // first, so that its h1 is the one goto() focuses while it is on show
  // the answer comes first, so a phone shows it before the form; views.css puts it beside the form on wide screens
  const parts = [head.node, h("div", { class: "cost-grid" }, output, form, stock.node)];
  panel.replaceChildren(empty, ...parts);
  const drafts = createDrafts(form, fields);
  let shownId = null;
  let shownEstimate;
  /** The empty state while nothing is picked; the form and its figures, kept as they were, once a place is. */
  const showEmpty = (isEmpty) => {
    if (!isEmpty) empty.replaceChildren();
    else if (!empty.children.length) empty.append(emptyState({ kicker: t("cost.kicker"), onFind, onCheckPoint }));
    for (const part of parts) part.hidden = isEmpty;
  };

  return {
    /** photoFloorCm fills the floor field unless the owner has typed their own for this place. estimate is the place's
     *  estimate (estimateState), stockState its stock photo ({busy, result, error}) and rp the flood size on show. */
    render(place, photoFloorCm, estimate, stockState, rp = DEFAULT_RP) {
      showEmpty(!place);
      if (!place) return;
      stock.render(stockState, rp);
      const isNewPlace = place.id !== shownId;
      if (isNewPlace) {
        if (shownId) drafts.save(shownId);
        drafts.restore(place.id);
        shownId = place.id;
        head.title.textContent = costTitle(place);
        head.depths.replaceChildren(...depthChips(place));
      }
      useFloorFromPhoto(fields, photoFloorCm);
      if (isNewPlace || estimate !== shownEstimate) {
        const isAnswered = !isNewPlace && isOwnAnswer(shownEstimate, estimate);
        shownEstimate = estimate;
        showEstimate({ output, status: head.status, submit: fields.submit, error: fields.error }, estimate, isAnswered);
      }
    },
    /** What the form would send now, or null (formFigures). */
    figures: () => formFigures(form, fields),
  };
}
