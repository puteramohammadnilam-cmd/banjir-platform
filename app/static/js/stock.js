// "Not sure what it is worth? Take a photo inside your shop" on the Flood cost tab (plan card G1). Gemini lists what a photo of the shop's
// inside shows and guesses a rough value range for each thing; the server works out which of them sit under the
// modelled water (app/stock.py). Nothing reaches the cost form until the owner presses "Use these figures".
import { h, icon, ringgit } from "./dom.js";
import { t } from "./i18n.js";

const heightText = (cm) => (cm > 0 ? t("stock.up", { cm }) : t("stock.onFloor"));
const range = (low, high) => t("stock.range", { low: ringgit(low), high: ringgit(high) });
const CONFIDENCE = { low: "confidence.low", medium: "confidence.medium", high: "confidence.high" };

function itemTable(items, under, rp) {
  return h("div", { class: "table-scroll" }, h("table", { class: "loss-table stock-table" },
    h("caption", { class: "visually-hidden" }, t("stock.caption")),
    h("thead", {}, h("tr", {}, [t("stock.colItem"), t("stock.colLowest"), t("stock.colValue"), t("stock.colFlood", { rp })].map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, items.map((item, i) => h("tr", { class: under.has(i) ? "is-under" : null },
      h("th", { scope: "row" }, item.item), h("td", {}, heightText(item.lowest_cm)),
      h("td", {}, range(item.value_rm_low, item.value_rm_high)),
      h("td", {}, t(under.has(i) ? "stock.under" : "stock.above")))))));
}

function floodLine(flood, rp, count, floorCm) {
  const floor = t("stock.floor", { cm: Math.round(floorCm) });
  if (!(flood.water_above_floor_m > 0)) return t("stock.dry", { rp, floor });
  return t("stock.wet", { rp, floor, m: flood.water_above_floor_m.toFixed(2), under: flood.under_water.length, count,
    range: range(flood.value_rm_low, flood.value_rm_high) });
}

function findings(result, rp, onUse) {
  const { estimate } = result;
  if (!estimate.is_shop_inside) {
    return [h("p", { class: "fact-note" }, t("stock.notInside"))];
  }
  if (!estimate.items.length) {
    return [h("p", { class: "fact-note" }, t("stock.nothing"))];
  }
  const flood = result.per_flood[rp];
  return [
    itemTable(estimate.items, new Set(flood.under_water), rp),
    h("p", {}, floodLine(flood, rp, estimate.items.length, result.floor_height_cm)),
    h("p", { class: "fineprint" }, t("stock.guess", { confidence: CONFIDENCE[estimate.confidence] ? t(CONFIDENCE[estimate.confidence]) : estimate.confidence })),
    h("div", { class: "stock-use" },
      h("button", { type: "button", class: "btn btn-primary", onclick: () => onUse(result.suggested_value_rm) }, t("stock.use")),
      h("p", { class: "hint" }, t("stock.useHint", { value: ringgit(result.suggested_value_rm) }))),
  ];
}

/** The card. render(state, rp) with state {busy, result, error} (the answer of POST /api/stock as `result`) and the
 *  flood size on show. onPhoto(file) sends a photo; onUse(value) puts the suggested value in the cost form. The picker
 *  and the live region are built once and changed in place, so focus and announcements stay. isReady is false when the
 *  build has no Gemini key: the picker is then off, with a line that says why. */
export function createStockCard({ onPhoto, onUse, isReady = true }) {
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "visually-hidden",
    onchange: (event) => { onPhoto(event.target.files[0]); event.target.value = ""; } });
  const words = h("span");
  const picker = h("label", { class: "btn btn-secondary photo-button" }, icon("camera"), words, input);
  const alert = h("p", { class: "fact-note", role: "alert" });
  const live = h("div", { "aria-live": "polite" });
  const node = h("section", { class: "surface stock-card", "aria-labelledby": "stock-heading" },
    h("h2", { id: "stock-heading", class: "small-heading" }, t("stock.heading")),
    h("p", { class: "hint" }, t("stock.hint")),
    picker, !isReady && h("p", { class: "fact-note ai-off" }, t("common.needsAi")), alert, live,
    h("p", { class: "fineprint" }, t("common.photoPrivacy")));
  let shown = {};
  return {
    node,
    render(state, rp) {
      if (state === shown.state && rp === shown.rp) return;
      const isDone = Boolean(shown.state?.busy) && !state?.busy;
      shown = { state, rp };
      const isOff = Boolean(state?.busy) || !isReady;
      input.disabled = isOff;
      // a disabled picker loses focus to the page: give it back once the photo is read (or failed)
      if (isDone && [input, document.body].includes(document.activeElement)) input.focus();
      if (isOff) picker.setAttribute("aria-disabled", "true");
      else picker.removeAttribute("aria-disabled");
      words.textContent = t(state?.busy ? "common.photoReading" : state?.result ? "common.photoAgain" : "stock.add");
      alert.textContent = state?.error ?? "";
      alert.hidden = !state?.error;
      live.replaceChildren(...(state?.result ? findings(state.result, rp, onUse) : []));
    },
  };
}
