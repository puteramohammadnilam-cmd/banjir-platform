// "Fill in from a photo of your stock" on the Flood cost tab (plan card G1). Gemini lists what a photo of the shop's
// inside shows and guesses a rough value range for each thing; the server works out which of them sit under the
// modelled water (app/stock.py). Nothing reaches the cost form until the owner presses "Use these figures".
import { h, icon, ringgit } from "./dom.js";

const heightText = (cm) => (cm > 0 ? `${cm} cm up` : "on the floor");
const range = (low, high) => `${ringgit(low)} to ${ringgit(high)}`;

function itemTable(items, under, rp) {
  return h("div", { class: "table-scroll" }, h("table", { class: "loss-table stock-table" },
    h("caption", { class: "visually-hidden" }, "What the photo shows"),
    h("thead", {}, h("tr", {}, ["Item", "Lowest part", "Gemini's rough value", `In a 1 in ${rp} years flood`].map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, items.map((item, i) => h("tr", { class: under.has(i) ? "is-under" : null },
      h("th", { scope: "row" }, item.item), h("td", {}, heightText(item.lowest_cm)),
      h("td", {}, range(item.value_rm_low, item.value_rm_high)),
      h("td", {}, under.has(i) ? "Under water" : "Above the water"))))));
}

function floodLine(flood, rp, count, floorCm) {
  const floor = `with the floor ${Math.round(floorCm)} cm above the street`;
  if (!(flood.water_above_floor_m > 0)) return `In a 1 in ${rp} years flood, ${floor}, the model puts no water above your floor.`;
  return `In a 1 in ${rp} years flood, ${floor}, the model puts ${flood.water_above_floor_m.toFixed(2)} m of water above your floor: `
    + `${flood.under_water.length} of ${count} items would be under it, worth ${range(flood.value_rm_low, flood.value_rm_high)} by Gemini's guess.`;
}

function findings(result, rp, onUse) {
  const { estimate } = result;
  if (!estimate.is_shop_inside) {
    return [h("p", { class: "fact-note" }, "That photo does not look like the inside of a shop. Try one that shows your shelves and equipment.")];
  }
  if (!estimate.items.length) {
    return [h("p", { class: "fact-note" }, "Gemini saw no stock or equipment in that photo. Try one that shows your shelves and equipment.")];
  }
  const flood = result.per_flood[rp];
  return [
    itemTable(estimate.items, new Set(flood.under_water), rp),
    h("p", {}, floodLine(flood, rp, estimate.items.length, result.floor_height_cm)),
    h("p", { class: "fineprint" }, `Gemini's rough guess from one photo, not a valuation (it says its confidence is ${estimate.confidence}). Things the photo does not show are not counted.`),
    h("div", { class: "stock-use" },
      h("button", { type: "button", class: "btn btn-primary", onclick: () => onUse(result.suggested_value_rm) }, "Use these figures"),
      h("p", { class: "hint" }, `Puts ${ringgit(result.suggested_value_rm)}, the middle of the guess for everything in the photo, in "Roughly what it is worth". You can change it.`)),
  ];
}

/** The card. render(state, rp) with state {busy, result, error} (the answer of POST /api/stock as `result`) and the
 *  flood size on show. onPhoto(file) sends a photo; onUse(value) puts the suggested value in the cost form. The picker
 *  and the live region are built once and changed in place, so focus and announcements stay. */
export function createStockCard({ onPhoto, onUse }) {
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "visually-hidden",
    onchange: (event) => { onPhoto(event.target.files[0]); event.target.value = ""; } });
  const words = h("span");
  const picker = h("label", { class: "btn btn-secondary photo-button" }, icon("camera"), words, input);
  const alert = h("p", { class: "fact-note", role: "alert" });
  const live = h("div", { "aria-live": "polite" });
  const node = h("section", { class: "surface stock-card", "aria-labelledby": "stock-heading" },
    h("h2", { id: "stock-heading", class: "small-heading" }, "Fill in from a photo of your stock"),
    h("p", { class: "hint" }, "Take a photo inside your shop. Gemini lists what it sees and guesses a rough value. Nothing is filled in until you press Use these figures."),
    picker, alert, live,
    h("p", { class: "fineprint" }, "The photo is shrunk in your browser, sent to Google Gemini, and not saved by this tool."));
  let shown = {};
  return {
    node,
    render(state, rp) {
      if (state === shown.state && rp === shown.rp) return;
      shown = { state, rp };
      input.disabled = Boolean(state?.busy);
      if (state?.busy) picker.setAttribute("aria-disabled", "true");
      else picker.removeAttribute("aria-disabled");
      words.textContent = state?.busy ? "Reading the photo…" : state?.result ? "Try another photo" : "Add a photo of your stock";
      alert.textContent = state?.error ?? "";
      alert.hidden = !state?.error;
      live.replaceChildren(...(state?.result ? findings(state.result, rp, onUse) : []));
    },
  };
}
