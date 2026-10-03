// The "Flood cost" tab: the owner's own figures in, a rough ringgit loss out. The sums run on the server (app/costs.py).
import { SCENARIOS, depthText, h, icon, ringgit } from "./dom.js";

// The browser's own range checks, mirroring floodtools.ESTIMATE_MAX. The server checks again.
const MAX = { value_at_risk_rm: 50_000_000, floor_height_cm: 300, daily_takings_rm: 1_000_000, closed_days: 365, raise_cm: 300, measure_cost_rm: 50_000_000 };
const SIZES = [["small", "A small shop"], ["medium", "A medium shop"], ["complex", "A large complex, such as a mall or hypermarket"]];

function numberField(name, label, unit, extra = {}) {
  const input = h("input", { class: "field", type: "number", name, id: `cost-${name}`, min: 0, max: MAX[name], step: "any", inputmode: "decimal", ...extra });
  const box = unit === "RM" ? h("div", { class: "money" }, input) : h("div", { class: "unit", "data-unit": unit }, input);
  return { input, node: h("label", { class: "input-label", for: input.id }, label, box) };
}

const metresAbove = (m) => (m > 0 ? `${m.toFixed(2)} m` : "none");

function lossTable(result) {
  return h("div", { class: "table-scroll" }, h("table", { class: "loss-table" },
    h("caption", { class: "visually-hidden" }, "Loss in each flood size"),
    h("thead", {}, h("tr", {}, ["Flood size", "Water above floor", "Damage", "Lost trade", "Total"].map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, SCENARIOS.map((rp) => {
      const flood = result.per_flood[rp];
      return h("tr", {}, h("th", { scope: "row" }, `1 in ${rp} years`), h("td", {}, metresAbove(flood.water_above_floor_m)),
        h("td", {}, ringgit(flood.direct_damage_rm)), h("td", {}, ringgit(flood.indirect_loss_rm)), h("td", {}, h("strong", {}, ringgit(flood.total_rm))));
    }))));
}

function verdict(measure, years) {
  if (!measure) return null;
  const saving = `It would save about ${ringgit(measure.benefit_present_value_rm)} over ${years} years, for a cost of ${ringgit(measure.cost_rm)}.`;
  if (measure.worth_it == null) return h("div", { class: "verdict" }, h("strong", {}, `Raising stock ${measure.raise_cm} cm`), h("p", {}, saving));
  return h("div", { class: `verdict ${measure.worth_it ? "is-yes" : "is-no"}` },
    h("strong", {}, `Raising stock ${measure.raise_cm} cm ${measure.worth_it ? "pays for itself" : "does not pay for itself"}`),
    h("p", {}, saving));
}

function results(result) {
  if (!result) {
    return [h("div", { class: "cost-empty" }, icon("cash"), h("strong", {}, "Your estimate shows here"),
      h("p", {}, "Fill in what you know and press Estimate. Leave out what you don't know: the answer says what it assumed."))];
  }
  const { years, discount_rate: rate, present_value_rm: overYears } = result.loss_over_years;
  return [
    h("div", { class: "headline-figures" },
      h("div", { class: "figure-box is-key" }, h("p", { class: "kpi-figure" }, ringgit(result.expected_yearly_loss_rm)),
        h("p", { class: "kpi-label" }, "average loss a year"), h("p", { class: "kpi-note" }, "across the three flood sizes in the model")),
      h("div", { class: "figure-box" }, h("p", { class: "kpi-figure" }, ringgit(overYears)),
        h("p", { class: "kpi-label" }, `over ${years} years`), h("p", { class: "kpi-note" }, `in today's money, at ${Math.round(rate * 100)}% a year`))),
    lossTable(result),
    verdict(result.measure, years),
    h("p", { class: "fineprint" }, "A rough estimate, not a valuation or an insurance figure."),
    h("details", {}, h("summary", {}, "How this is worked out"),
      h("p", {}, `Damage: ${result.basis.direct}.`), h("p", {}, `Lost trade: ${result.basis.indirect}.`),
      h("p", {}, result.method), h("p", {}, result.limits)),
  ].filter(Boolean);
}

const FLOOR_NOTE = "Leave empty if the floor is level with the street.";
const number = (field) => Number(field.input.value || 0);

/** The tab's heading: a point is a 90 m square someone picked, so it has no name. */
export const costTitle = (place) => (place.is_point ? "What a flood could cost at this point" : `What a flood could cost ${place.name}`);

const depthsLine = (place) =>
  `Modelled water at street level: ${SCENARIOS.map((rp) => `${depthText(place.depth_m[rp])} in a 1 in ${rp} years flood`).join(", ")}.`;

/** The form's inputs, built once: the figures, the shop size choice and the optional measure, with the error line and
 *  the submit button. */
function buildFields() {
  const size = h("select", { class: "field", name: "shop_size", id: "cost-shop_size" },
    h("option", { value: "" }, "Choose one"), SIZES.map(([key, text]) => h("option", { value: key }, text)));
  const raise = numberField("raise_cm", "Raise stock by", "cm");
  const measureCost = numberField("measure_cost_rm", "What that costs", "RM");
  return {
    numbers: {
      value: numberField("value_at_risk_rm", "Roughly what it is worth", "RM", { min: 1, required: true, placeholder: "50000" }),
      floor: numberField("floor_height_cm", "Shop floor above the street", "cm", { placeholder: "0" }),
      takings: numberField("daily_takings_rm", "Takings lost per day closed", "RM"),
      days: numberField("closed_days", "Days closed after a flood", "days"),
      raise,
      measureCost,
    },
    size,
    sizeBox: h("label", { class: "input-label", for: size.id, hidden: true }, "My shop is", size),
    floorNote: h("p", { class: "hint" }, FLOOR_NOTE),
    measure: h("details", {}, h("summary", {}, "Test a measure: raise my stock"),
      h("p", { class: "hint" }, "Optional. Needs the value above, and both figures."),
      h("div", { class: "pair" }, raise.node, measureCost.node)),
    error: h("p", { class: "form-error", role: "alert" }),
    submit: h("button", { type: "submit", class: "btn btn-primary" }, "Estimate the cost"),
  };
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
  if ((raiseCm > 0) !== (costRm > 0)) return { error: "To test a measure, give both how far to raise the stock and what it costs." };
  if (raiseCm > 0 && !byValue) return { error: "A measure can only be priced from your own value of stock and equipment, not from a shop size." };
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
  const { numbers, sizeBox, floorNote, measure, error, submit } = fields;
  const modeChoice = (mode, text, checked) => h("label", { class: "choice" },
    h("input", { type: "radio", name: "mode", value: mode, checked, onchange: () => setMode(fields, mode) }), text);
  const form = h("form", { class: "surface cost-form", onsubmit: (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const read = readFigures(form, fields);
    error.textContent = read.error ?? "";
    if (read.figures) onEstimate(read.figures);
  } },
  h("fieldset", {}, h("legend", {}, "Stock and equipment"),
    h("p", { class: "hint" }, "What water could reach: goods, machines, furniture and fittings."),
    modeChoice("value", "I know roughly what it is worth", true),
    modeChoice("size", "I don't know: use a typical figure for my shop size", false),
    numbers.value.node, sizeBox),
  h("fieldset", {}, h("legend", {}, "Your shop"), numbers.floor.node, floorNote),
  h("fieldset", {}, h("legend", {}, "Lost trade"),
    h("p", { class: "hint" }, "Optional. Without it, 30% of the damage is added for cleaning up and lost trade."),
    h("div", { class: "pair" }, numbers.takings.node, numbers.days.node)),
  measure, error, submit);
  numbers.floor.input.addEventListener("input", () => { numbers.floor.input.dataset.touched = "true"; });
  return form;
}

/** What was typed for each place, by its id, so going to another business or point and back never mixes figures up. */
function createDrafts(form, fields) {
  const { numbers, size, measure, floorNote, error } = fields;
  const drafts = new Map();
  const snapshot = () => ({
    mode: form.elements.mode.value, size: size.value, open: measure.open, note: floorNote.textContent,
    touched: numbers.floor.input.dataset.touched === "true",
    ...Object.fromEntries(Object.entries(numbers).map(([key, field]) => [key, field.input.value])),
  });
  function restore(draft) {
    for (const [key, field] of Object.entries(numbers)) field.input.value = draft?.[key] ?? "";
    size.value = draft?.size ?? "";
    form.elements.mode.value = draft?.mode ?? "value";
    setMode(fields, form.elements.mode.value);
    measure.open = draft?.open ?? false;
    if (draft?.touched) numbers.floor.input.dataset.touched = "true";
    else delete numbers.floor.input.dataset.touched;
    floorNote.textContent = draft?.note ?? FLOOR_NOTE;
    error.textContent = "";
  }
  return { save: (id) => drafts.set(id, snapshot()), restore: (id) => restore(drafts.get(id)) };
}

/** Builds the form once. Each business or point keeps its own figures, so switching never mixes them up. */
export function createCost(panel, { onEstimate }) {
  const title = h("h1", { class: "view-title" });
  const depths = h("p", { class: "muted" });
  const fields = buildFields();
  const { numbers, floorNote, error, submit } = fields;
  const form = buildForm(fields, onEstimate);
  const output = h("section", { class: "surface cost-results", "aria-live": "polite", "aria-label": "Your estimate" });
  panel.replaceChildren(
    h("header", { class: "view-head" }, h("p", { class: "kicker" }, "Flood cost"), title, depths),
    h("div", { class: "cost-grid" }, form, output));
  const drafts = createDrafts(form, fields);
  let shownId = null;
  let shownEstimate;

  return {
    /** photoFloorCm fills the floor field unless the owner has typed their own for this place. */
    render(place, photoFloorCm, estimate) {
      const isNewPlace = place.id !== shownId;
      if (isNewPlace) {
        if (shownId) drafts.save(shownId);
        drafts.restore(place.id);
        shownId = place.id;
        title.textContent = costTitle(place);
        depths.textContent = depthsLine(place);
      }
      if (photoFloorCm != null && !numbers.floor.input.dataset.touched && numbers.floor.input.value !== String(photoFloorCm)) {
        numbers.floor.input.value = String(photoFloorCm);
        floorNote.textContent = "Filled in from your shop-front photo. Change it if you know better.";
      }
      if (isNewPlace || estimate !== shownEstimate) {
        shownEstimate = estimate;
        submit.disabled = Boolean(estimate?.busy);
        submit.textContent = estimate?.busy ? "Working it out…" : "Estimate the cost";
        if (!estimate?.busy) error.textContent = estimate?.error ?? "";
        output.replaceChildren(...results(estimate?.result));
      }
    },
  };
}
