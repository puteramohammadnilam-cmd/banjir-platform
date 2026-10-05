// The Flood cost form as six plain questions, each with ready answers to tap, "Not sure", and a way to type one's own
// figure. A picked range counts as about its middle, said under it. The figures sent (app/costs.py, app/wider_costs.py):
// value or shop size, built-in works, floor height, daily takings and days closed, workers not paid while shut, the
// value of vehicles parked at the shop, and the measure's height and cost.
import { h, ringgit } from "./dom.js";
import { t } from "./i18n.js";

// The browser's own range checks, mirroring floodtools.ESTIMATE_MAX. The server checks again.
const MAX = { value_at_risk_rm: 50_000_000, floor_height_cm: 300, daily_takings_rm: 1_000_000, measure_cost_rm: 50_000_000, built_in_rm: 50_000_000 };
export const SIZES = [["small", "cost.sizeSmall"], ["medium", "cost.sizeMedium"], ["complex", "cost.sizeComplex"]];
const OWN = "own";
const UNSURE = "unsure";
const SIZE = "size";
// "Over RM 150k" counts as this round figure, not a middle: said so under it.
const OPEN_TOP_WORTH = "200000";
// The server takes ringgit from 1 up (floodtools.ESTIMATE_MAX and its checks); a value box starts there too.
const MIN = { value_at_risk_rm: 1, measure_cost_rm: 1, built_in_rm: 1 };

// Each answer is [value, string key]. A number is what the answer counts as: a range's rough middle (and for an open
// top, a round figure above its floor), a step's height, a customer count or a spend.
const CHOICES = {
  worth: [["5000", "cost.worthUnder10"], ["30000", "cost.worth10to50"], ["100000", "cost.worth50to150"], ["200000", "cost.worthOver150"],
    [SIZE, "common.notSure"], [OWN, "common.typeOwn"]],
  floor: [["0", "cost.floorLevel"], ["15", "cost.floorStep"], ["45", "cost.floorSteps"], [OWN, "common.typeOwn"]],
  customers: [["10", "cost.custUnder20"], ["35", "cost.cust20to50"], ["75", "cost.cust50to100"], ["150", "cost.custOver100"],
    [UNSURE, "common.notSure"], [OWN, "cost.custOwn"]],
  spend: [["5", "cost.spend5"], ["15", "cost.spend15"], ["30", "cost.spend30"], ["50", "cost.spend50"]],
  days: [["3", "cost.days3"], ["7", "cost.days7"], ["14", "cost.days14"], ["30", "cost.days30"]],
  raise: [["0", "cost.raiseSkip"], ["15", "cost.raisePallets"], ["50", "cost.raiseRacks"], ["100", "cost.raiseTop"]],
  measureCost: [["250", "cost.costUnder500"], ["1250", "cost.cost500to2k"], ["3500", "cost.cost2kto5k"], [OWN, "common.typeOwn"]],
  builtIn: [["0", "cost.builtInNone"], ["5000", "cost.builtInUnder10"], ["20000", "cost.builtIn10to30"], ["50000", "cost.builtIn30to80"],
    [OWN, "common.typeOwn"]],
  workers: [["0", "cost.workersNone"], ["1", "cost.workers1"], ["2", "cost.workers2"], ["4", "cost.workers3to5"], ["8", "cost.workers6to10"]],
  paid: [["no", "cost.paidNo"], ["yes", "cost.paidYes"]],
  cars: [["0", "cost.carsNone"], ["1", "cost.cars1"], ["2", "cost.cars2"], ["3", "cost.cars3"], ["5", "cost.cars5"]],
  carValue: [["30000", "cost.carValue30"], ["60000", "cost.carValue60"], ["100000", "cost.carValue100"], ["150000", "cost.carValue150"]],
  motos: [["0", "cost.motosNone"], ["1", "cost.motos1"], ["2", "cost.motos2"], ["5", "cost.motos5"]],
  motoValue: [["3000", "cost.motoValue3"], ["6000", "cost.motoValue6"], ["10000", "cost.motoValue10"]],
};
// Ready to answer at once: a typical figure for a medium shop, the floor level with the road, lost trade not sure (the
// guideline's 30%), no measure.
// No built-in works, workers or vehicles until the owner says so; workers are taken as unpaid while shut until they say not.
const DEFAULTS = Object.freeze({ worth: SIZE, floor: "0", customers: UNSURE, spend: "15", days: "7", raise: "0", measureCost: "1250",
  builtIn: "0", workers: "0", paid: "no", cars: "0", carValue: "60000", motos: "0", motoValue: "6000" });
const DEFAULT_SIZE = "medium";
// Minimum Wages Order 2024, P.U. (A) 376: RM1,700 a month, RM65.38 a day for a six-day week. The server counts the
// same (wider_costs.MIN_WAGE_DAY_RM); here it only says the ringgit beside the answer.
const MIN_WAGE_DAY_RM = 65.38;

const isNumber = (value) => value !== OWN && value !== UNSURE && value !== SIZE;
const typed = (input) => Number(input.value || 0);

/** A row of answers as radio buttons that look like chips. Tapping one calls onChange(value). */
function chips(name, onChange) {
  const radios = CHOICES[name].map(([value, key]) => {
    const radio = h("input", { type: "radio", name: `cost-${name}`, value, class: "chip-radio", onchange: () => onChange(value) });
    return { value, radio, node: h("label", { class: "answer-chip" }, radio, h("span", {}, t(key))) };
  });
  return { radios, node: h("div", { class: "chips-row" }, radios.map((choice) => choice.node)) };
}

function numberBox(name, label, unit) {
  const input = h("input", { class: "field", type: "number", name, id: `cost-${name}`, min: MIN[name] ?? 0, max: MAX[name], step: "any", inputmode: "decimal" });
  const box = unit === "RM" ? h("div", { class: "money" }, input) : h("div", { class: "unit", "data-unit": unit }, input);
  return { input, node: h("label", { class: "input-label", for: input.id }, label, box) };
}

const question = (title, ...body) => h("fieldset", { class: "question" }, h("legend", { class: "question-title" }, title), ...body);
/** A follow-on question inside one: its own fieldset, so a screen reader names the answers with it. */
const subQuestion = (title) => h("fieldset", { class: "sub-question" }, h("legend", { class: "sub-label" }, title));

/** The parts of the form, before they are laid out: each question's chips, the boxes for one's own figure, and the
 *  lines that say what a pick counts as. */
function buildParts(sync) {
  const groups = Object.fromEntries(Object.keys(CHOICES).map((name) => [name, chips(name, () => sync(name))]));
  const size = h("select", { class: "field", name: "shop_size", id: "cost-shop_size", onchange: () => sync() },
    SIZES.map(([key, text]) => h("option", { value: key }, t(text))));
  return {
    groups, size,
    sizeBox: h("label", { class: "input-label", for: size.id }, t("cost.myShop"), size),
    boxes: { value: numberBox("value_at_risk_rm", t("cost.value"), "RM"), floor: numberBox("floor_height_cm", t("cost.floor"), "cm"),
      takings: numberBox("daily_takings_rm", t("cost.takings"), "RM"), measureCost: numberBox("measure_cost_rm", t("cost.measureCost"), "RM"),
      builtIn: numberBox("built_in_rm", t("cost.builtInOwn"), "RM") },
    worthLine: h("p", { class: "hint answer-line" }),
    tradeLine: h("p", { class: "hint answer-line" }),
    valueNote: h("p", { class: "hint", "aria-live": "polite" }),
    floorNote: h("p", { class: "hint" }),
    spendBox: subQuestion(t("cost.spendQ")),
    daysBox: subQuestion(t("cost.daysQ")),
    costBox: subQuestion(t("cost.costQ")),
    builtInBox: subQuestion(t("cost.builtInQ")),
    paidBox: subQuestion(t("cost.paidQ")),
    carValueBox: subQuestion(t("cost.carValueQ")),
    motosBox: subQuestion(t("cost.motosQ")),
    motoValueBox: subQuestion(t("cost.motoValueQ")),
    workersLine: h("p", { class: "hint answer-line" }),
    vehiclesLine: h("p", { class: "hint answer-line" }),
    error: h("p", { class: "form-error", role: "alert" }),
    submit: h("button", { type: "submit", class: "btn btn-primary" }, t("cost.submit")),
  };
}

/** Each follow-on question gets its answers: the chips, then a box for one's own figure where there is one. */
function fillSubQuestions(parts) {
  const { groups, boxes } = parts;
  parts.spendBox.append(groups.spend.node);
  parts.daysBox.append(groups.days.node);
  parts.costBox.append(groups.measureCost.node, boxes.measureCost.node);
  parts.builtInBox.append(h("p", { class: "hint" }, t("cost.builtInHint")), groups.builtIn.node, boxes.builtIn.node);
  parts.paidBox.append(groups.paid.node);
  parts.carValueBox.append(groups.carValue.node);
  parts.motosBox.append(groups.motos.node);
  parts.motoValueBox.append(groups.motoValue.node);
}

/** The six questions, in order, with the measure last and optional. */
function layout(parts) {
  const { groups, sizeBox, boxes, worthLine, tradeLine, valueNote, floorNote, spendBox, daysBox, costBox } = parts;
  fillSubQuestions(parts);
  const hint = (key) => h("p", { class: "hint" }, t(key));
  return [
    question(t("cost.q1"), hint("cost.q1Hint"), groups.worth.node, worthLine, sizeBox, boxes.value.node, valueNote,
      h("p", { class: "example" }, t("cost.q1Example")), parts.builtInBox),
    question(t("cost.q2"), groups.floor.node, boxes.floor.node, floorNote),
    question(t("cost.q3"), hint("cost.q3Hint"), groups.customers.node, spendBox, boxes.takings.node, daysBox, tradeLine),
    question(t("cost.qWorkers"), hint("cost.qWorkersHint"), groups.workers.node, parts.paidBox, parts.workersLine),
    question(t("cost.qVehicles"), hint("cost.qVehiclesHint"), groups.cars.node, parts.carValueBox, parts.motosBox, parts.motoValueBox,
      parts.vehiclesLine),
    question(t("cost.q4"), hint("cost.q4Hint"), groups.raise.node, costBox),
  ];
}

const chosen = (group) => group.radios.find((choice) => choice.radio.checked)?.value ?? null;
function choose(group, value) {
  for (const choice of group.radios) choice.radio.checked = choice.value === value;
}

/** What each answer counts as, read off the chips and boxes. */
function answers(parts) {
  const pick = Object.fromEntries(Object.entries(parts.groups).map(([name, group]) => [name, chosen(group)]));
  const customers = pick.customers;
  const daily = customers === OWN ? typed(parts.boxes.takings.input)
    : isNumber(customers) ? Number(customers) * Number(pick.spend) : 0;
  const raise = Number(pick.raise);
  const hasValue = pick.worth === OWN || isNumber(pick.worth);   // built-in works add only to the owner's own value
  return {
    pick, daily, days: Number(pick.days), raise, hasValue,
    builtIn: !hasValue ? 0 : pick.builtIn === OWN ? typed(parts.boxes.builtIn.input) : Number(pick.builtIn),
    vehicles: Number(pick.cars) * Number(pick.carValue) + Number(pick.motos) * Number(pick.motoValue),
    unpaid: pick.paid === "no" ? Number(pick.workers) : 0,
    value: pick.worth === OWN ? typed(parts.boxes.value.input) : isNumber(pick.worth) ? Number(pick.worth) : 0,
    floor: pick.floor === OWN ? typed(parts.boxes.floor.input) : Number(pick.floor),
    measureCost: raise > 0 ? (pick.measureCost === OWN ? typed(parts.boxes.measureCost.input) : Number(pick.measureCost)) : 0,
  };
}

/** What the value pick counts as, in words: a range's middle, the open top's round figure, or the shop size's figure. */
function worthWords(pick, value) {
  if (pick === OPEN_TOP_WORTH) return t("cost.worthUsesOver", { rm: ringgit(value) });
  if (isNumber(pick)) return t("cost.worthUses", { rm: ringgit(value) });
  return pick === SIZE ? t("cost.worthSize") : "";
}

/** Show what goes with each pick: one's own box, the shop size, the spend, the measure's cost; and say what a pick
 *  counts as. A box out of sight is switched off too, so a figure left in it can never block Estimate unseen. */
function show(parts) {
  const { pick, daily, days, value, raise, hasValue } = answers(parts);
  const boxShown = { value: pick.worth === OWN, floor: pick.floor === OWN, takings: pick.customers === OWN, measureCost: raise > 0 && pick.measureCost === OWN,
    builtIn: hasValue && pick.builtIn === OWN };
  for (const [name, box] of Object.entries(parts.boxes)) {
    box.node.hidden = !boxShown[name];
    box.input.disabled = !boxShown[name];
  }
  parts.boxes.value.input.required = boxShown.value;
  parts.sizeBox.hidden = pick.worth !== SIZE;
  parts.worthLine.textContent = worthWords(pick.worth, value);
  parts.spendBox.hidden = !isNumber(pick.customers);
  parts.tradeLine.textContent = daily > 0 ? t("cost.tradeLine", { day: ringgit(daily), days, total: ringgit(daily * days) })
    : pick.customers === UNSURE ? t("cost.tradeUnsure") : "";
  parts.costBox.hidden = !(raise > 0);
  showWider(parts);
}

/** Built-in works only beside one's own value; the workers' pay and the vehicles, said in ringgit as they are picked. */
function showWider(parts) {
  const { pick, days, hasValue, unpaid, vehicles } = answers(parts);
  parts.builtInBox.hidden = !hasValue;
  const workers = Number(pick.workers);
  parts.paidBox.hidden = workers === 0;
  parts.workersLine.textContent = workers === 0 ? ""
    : unpaid > 0 ? t("cost.workersLine", { rm: ringgit(Math.round(unpaid * MIN_WAGE_DAY_RM * days)), days, wage: MIN_WAGE_DAY_RM.toFixed(2) })
      : t("cost.workersPaid");
  parts.carValueBox.hidden = Number(pick.cars) === 0;
  parts.motoValueBox.hidden = Number(pick.motos) === 0;
  parts.vehiclesLine.textContent = vehicles > 0 ? t("cost.vehiclesLine", { rm: ringgit(vehicles) }) : "";
}

/** The figures to send, or the problem to show. */
function readFigures(parts) {
  const { pick, value, floor, daily, days, raise, measureCost, builtIn, vehicles, unpaid } = answers(parts);
  if (raise > 0 && pick.worth === SIZE) return { error: t("cost.errSize") };
  if (raise > 0 && !(measureCost >= 1)) return { error: t("cost.errBoth") };
  return {
    figures: {
      value_at_risk_rm: value, shop_size: pick.worth === SIZE ? parts.size.value : "", floor_height_cm: floor,
      daily_takings_rm: daily, closed_days: days, raise_cm: raise, measure_cost_rm: measureCost,
      built_in_rm: builtIn, vehicles_rm: vehicles, unpaid_workers: unpaid,
    },
  };
}

/** Put every answer back as `draft` left it (a snapshot), or as the form starts. */
function restore(parts, draft) {
  for (const [name, group] of Object.entries(parts.groups)) choose(group, draft?.picks?.[name] ?? DEFAULTS[name]);
  for (const [name, box] of Object.entries(parts.boxes)) box.input.value = draft?.boxes?.[name] ?? "";
  parts.size.value = draft?.size ?? DEFAULT_SIZE;
  parts.valueNote.textContent = draft?.valueNote ?? "";
  parts.floorNote.textContent = draft?.floorNote ?? "";
  parts.floorTouched = Boolean(draft?.floorTouched);
  parts.error.textContent = "";
  show(parts);
}

const snapshot = (parts) => ({
  picks: Object.fromEntries(Object.entries(parts.groups).map(([name, group]) => [name, chosen(group)])),
  boxes: Object.fromEntries(Object.entries(parts.boxes).map(([name, box]) => [name, box.input.value])),
  size: parts.size.value, valueNote: parts.valueNote.textContent, floorNote: parts.floorNote.textContent, floorTouched: parts.floorTouched,
});

/** The form, built once. onEstimate(figures) hears a press of Estimate with no problem in the form. Each place keeps its
 *  own answers: save(id) before showing another place, restore(id) after. */
export function createCostForm(onEstimate) {
  const parts = buildParts((name) => {
    // a tap answers the question itself: the photo's note on it no longer holds
    if (name === "worth") parts.valueNote.textContent = "";
    if (name === "floor") {
      parts.floorTouched = true;
      parts.floorNote.textContent = "";
    }
    show(parts);
  });
  for (const box of Object.values(parts.boxes)) box.input.addEventListener("input", () => show(parts));
  parts.boxes.floor.input.addEventListener("input", () => {
    parts.floorTouched = true;
    parts.floorNote.textContent = "";
  });
  const form = h("form", { class: "surface cost-form", onsubmit: (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const read = readFigures(parts);
    parts.error.textContent = read.error ?? "";
    if (read.figures) onEstimate(read.figures);
  } }, ...layout(parts), parts.error, parts.submit);
  const drafts = new Map();
  restore(parts, null);
  return {
    node: form, submit: parts.submit, error: parts.error,
    save: (id) => drafts.set(id, snapshot(parts)),
    restore: (id) => restore(parts, drafts.get(id)),
    floorCm: () => answers(parts).floor,
    /** What Estimate would send now, or null while the form holds a problem. */
    figures: () => ((form.checkValidity && !form.checkValidity()) ? null : readFigures(parts).figures ?? null),
    /** The stock photo's value: typed in as one's own, said to be Gemini's guess, with focus on it. */
    useValue(value) {
      choose(parts.groups.worth, OWN);
      parts.boxes.value.input.value = String(value);
      parts.valueNote.textContent = t("cost.fromStock");
      show(parts);
      parts.boxes.value.input.focus();
    },
    /** The shop-front photo's floor height, unless the owner has answered that question for this place. */
    useFloor(cm) {
      if (cm == null || parts.floorTouched) return;
      choose(parts.groups.floor, OWN);
      parts.boxes.floor.input.value = String(cm);
      parts.floorNote.textContent = t("cost.fromPhoto");
      show(parts);
    },
  };
}
