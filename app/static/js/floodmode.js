// "Flood is coming" on My business: one screen to open when a warning is out, with six steps to tick off, each filled
// in from what the page already knows about the place: how high to lift things (the water in the model, less the floor
// height from a shop-front photo, and the things a stock photo put under it), where to move the car (car.js), power,
// papers and cash, photos for an insurer, and when to go, with the nearest relief centre. In a native modal <dialog>:
// the browser traps focus and Escape closes it. Ticks are for this screen only and are not kept.
import { carStep } from "./car.js";
import { band, depthText, h } from "./dom.js";
import { drawing } from "./drawing.js";
import { distanceText } from "./fact.js";
import { forecastLine } from "./forecast.js";
import { t } from "./i18n.js";
import { combine } from "./stock.js";

const LIFT_STEP_CM = 5;     // a lift height is rounded up to this
const MAX_ITEMS_NAMED = 5;
const INFOBANJIR = "https://publicinfobanjir.water.gov.my/";

/** The water above the floor in centimetres (street depth less the floor height); 0 when none. */
const aboveFloorCm = (depthM, floorCm = 0) => Math.max(0, (band(depthM) ? depthM * 100 : 0) - floorCm);

/** The water above the floor, rounded up to LIFT_STEP_CM: how high to lift things. 0 when none. */
export const liftCm = (depthM, floorCm = 0) => Math.ceil(aboveFloorCm(depthM, floorCm) / LIFT_STEP_CM) * LIFT_STEP_CM;

/** The things a stock photo shows (ticked ones) whose lowest part is under the water above the floor: the same floor
 *  as the lift height, so the two never disagree. */
function underWater(stock, rp, aboveCm) {
  if (!stock?.photos?.length) return [];
  return combine(stock.photos, stock.off ?? [], rp).items.filter((item) => item.isCounted && aboveCm > item.lowest_cm).map((item) => item.item);
}

function liftStep({ premise, rp, floorCm, stock }) {
  const depth = premise.depth_m?.[rp];
  const cm = liftCm(depth, floorCm);
  if (!cm) return [h("p", {}, t("mode.liftNone", { rp }))];
  const items = underWater(stock, rp, aboveFloorCm(depth, floorCm));
  const named = items.slice(0, MAX_ITEMS_NAMED).join(", ") + (items.length > MAX_ITEMS_NAMED ? t("mode.andMore", { n: items.length - MAX_ITEMS_NAMED }) : "");
  return [h("p", { class: "step-answer" }, t("mode.liftCm", { cm })),
    h("p", {}, t(floorCm ? "mode.liftWhyFloor" : "mode.liftWhy", { depth: depthText(depth), rp, floor: Math.round(floorCm) })),
    items.length > 0 && h("p", {}, t("mode.liftFirst", { items: named }))];
}

/** The car step: where to move it (car.js), "finding" while that is asked, or the plain advice without an answer. */
function carBody({ premise, rp, dry }) {
  if (dry?.busy) return [h("p", {}, t("car.finding"))];
  return carStep(premise, rp, dry) ?? [h("p", {}, t("mode.carEarly"))];
}

function goStep(premise) {   // the river forecast link is Google's, beside the official one
  const shelter = premise.shelter;
  return [
    h("p", {}, shelter ? t("mode.goShelter", { name: shelter.name, distance: distanceText(shelter.distance_m) }) : t("mode.goNoShelter")),
    h("p", {}, t("mode.goCall"), " ", h("a", { href: INFOBANJIR, target: "_blank", rel: "noopener noreferrer", translate: "no" }, "JPS Public Infobanjir"), "."),
    forecastLine(premise),
  ];
}

/** The six steps as [id, heading key, body nodes]. */
const steps = (context) => [
  ["lift", "mode.liftHeading", liftStep(context)],
  ["car", "mode.carHeading", carBody(context)],
  ["power", "mode.powerHeading", [h("p", {}, t("mode.power")), h("p", {}, t("mode.powerAfter"))]],
  ["papers", "mode.papersHeading", [h("p", {}, t("mode.papers"))]],
  ["photos", "mode.photoHeading", [h("p", {}, t("mode.photos"))]],
  ["go", "mode.goHeading", goStep(context.premise)],
];

const stepItem = ([id, heading, body], i) => h("li", { class: "mode-step", "data-step": id },
  h("label", { class: "mode-tick" }, h("input", { type: "checkbox" }), h("span", { class: "mode-num" }, String(i + 1)), h("strong", {}, t(heading))),
  h("div", { class: "mode-body" }, ...body.filter(Boolean)));

/** The checklist under its heading: for whom and which flood size, leaving first if the water is already rising, the
 *  steps, and the limits. */
export function checklist(context) {
  const name = context.premise.is_point || !context.premise.name ? t("share.pointName") : context.premise.name;
  return [
    h("p", { class: "muted" }, t("mode.lead", { name, rp: context.rp })),
    h("p", { class: "mode-urgent", role: "note" }, t("mode.urgent")),
    drawing("e-ready"),
    h("ol", { class: "mode-steps" }, steps(context).map(stepItem)),
    h("p", { class: "fineprint" }, t("mode.limit")),
  ];
}

/** The dialog, built once and added to the page. open(context, opener) fills it for the place and shows it, with the
 *  dialog itself focused so its heading is read first; refresh(context) puts in the car step's answer when it arrives
 *  while open, keeping the ticks; closing gives focus back to the button that opened it, or to the one now on the page. */
export function createFloodMode(doc = document) {
  const body = h("div", { class: "mode-content" });
  const close = () => dialog.close();
  const closeTop = h("button", { type: "button", class: "btn btn-secondary", onclick: close }, t("mode.close"));
  const head = h("div", { class: "mode-head" },
    h("div", {}, h("p", { class: "kicker" }, t("mode.kicker")), h("h2", { id: "mode-heading", class: "view-title" }, t("mode.heading"))), closeTop);
  const dialog = h("dialog", { class: "dialog flood-mode", "aria-labelledby": "mode-heading", tabindex: "-1" }, head, body,
    h("button", { type: "button", class: "btn btn-secondary mode-close-end", onclick: close }, t("mode.close")));
  let opener = null;
  dialog.addEventListener("close", () => {
    (opener?.isConnected ? opener : doc.querySelector?.(".mode-open"))?.focus();   // the side is rebuilt while open
    opener = null;
  });
  doc.body.append(dialog);
  return {
    dialog,
    open(context, from = null) {
      opener = from;
      body.replaceChildren(...checklist(context));
      dialog.showModal();
      dialog.focus();
    },
    refresh(context) {
      const car = dialog.open && body.querySelector('[data-step="car"]')?.querySelector(".mode-body");
      if (car) car.replaceChildren(...carBody(context).filter(Boolean));
    },
  };
}

/** The button on My business that opens it. */
export const floodModeButton = (onOpen) => h("button", { type: "button", class: "btn btn-primary mode-open",
  onclick: (event) => onOpen(event.currentTarget) }, t("mode.open"));
