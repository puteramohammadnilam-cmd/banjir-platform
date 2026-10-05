// "Not sure what it is worth? Take a photo inside your shop" on the Flood cost tab (plan card G1). Gemini lists what a photo of the shop's
// inside shows and guesses a rough value range for each thing; the server works out which of them sit under the
// modelled water (app/stock.py). Up to MAX_PHOTOS photos add up, the owner can untick what Gemini got wrong, see how high
// things would need to go, and save the list for an insurer. Nothing reaches the cost form until the owner presses a button.
import { RAISE_STEPS } from "./cost-form.js";
import { h, icon, ringgit } from "./dom.js";
import { t } from "./i18n.js";

export const MAX_PHOTOS = 4;
const MAX_VALUE_RM = 50_000_000;   // the form's limit, floodtools.ESTIMATE_MAX["value_at_risk_rm"]
const heightText = (cm) => (cm > 0 ? t("stock.up", { cm }) : t("stock.onFloor"));
const range = (low, high) => t("stock.range", { low: ringgit(low), high: ringgit(high) });
const REVOKE_MS = 10_000;
const CONFIDENCE = { low: "confidence.low", medium: "confidence.medium", high: "confidence.high" };
const sum = (list, field) => list.reduce((total, item) => total + item[field], 0);

/** Every photo's items as one list, for the flood size `rp`, with the ones in `off` (keys "photo-item") not counted.
 *  An item is under water when the water above the floor rises above its lowest part, as in app/stock.py.
 *  ponytail: the latest photo's floor height counts for all photos (the form's floor when it was sent); an earlier photo
 *  read with another floor is judged by the latest one, so the list never mixes two floors. */
export function combine(photos, off, rp) {
  if (!photos.length) return null;
  const latest = photos.at(-1);
  const water = latest.per_flood?.[rp]?.water_above_floor_m ?? 0;
  const items = photos.flatMap((photo, p) => photo.estimate.items.map((item, i) => ({ ...item, key: `${p}-${i}`,
    isCounted: !off.includes(`${p}-${i}`), isUnder: water > item.lowest_cm / 100 })));
  const counted = items.filter((item) => item.isCounted);
  const under = counted.filter((item) => item.isUnder);
  const low = sum(counted, "value_rm_low");
  const high = sum(counted, "value_rm_high");
  return {
    items, water, floorCm: latest.floor_height_cm, count: counted.length, low, high,
    under: { count: under.length, low: sum(under, "value_rm_low"), high: sum(under, "value_rm_high") },
    suggested: Math.min(Math.round((low + high) / 2), MAX_VALUE_RM),
    // how far the lowest thing under water must go up to clear it
    raiseCm: Math.max(0, ...under.map((item) => Math.max(1, Math.round(water * 100) - item.lowest_cm))),
    confidence: latest.estimate.confidence,
  };
}

/** The smallest of the form's "put things higher" answers that clears raiseCm, or null when none does. */
export const raiseStep = (raiseCm) => RAISE_STEPS.find((step) => step >= raiseCm) ?? null;

function itemTable(found, rp, { onToggle, isBusy }) {
  const row = (item) => h("tr", { class: [item.isUnder && "is-under", !item.isCounted && "is-off"].filter(Boolean).join(" ") || null },
    h("th", { scope: "row" }, h("label", { class: "stock-count" },
      h("input", { type: "checkbox", "data-key": item.key, checked: item.isCounted, disabled: isBusy, onchange: () => onToggle(item.key) }), item.item)),
    h("td", {}, heightText(item.lowest_cm)),
    h("td", {}, range(item.value_rm_low, item.value_rm_high)),
    h("td", {}, t(item.isUnder ? "stock.under" : "stock.above")));
  return h("div", { class: "table-scroll" }, h("table", { class: "loss-table stock-table" },
    h("caption", { class: "visually-hidden" }, t("stock.caption")),
    h("thead", {}, h("tr", {}, [t("stock.colItem"), t("stock.colLowest"), t("stock.colValue"), t("stock.colFlood", { rp })].map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, found.items.map(row))));
}

function floodLine(found, rp) {
  const floor = t("stock.floor", { cm: Math.round(found.floorCm) });
  if (!(found.water > 0)) return t("stock.dry", { rp, floor });
  return t("stock.wet", { rp, floor, m: found.water.toFixed(2), under: found.under.count, count: found.count,
    range: range(found.under.low, found.under.high) });
}

/** How high the things under water would need to go, and the form's answer that does it, if one does. */
function raiseAdvice(found, rp, onRaise) {
  if (!found.under.count) return [];
  const step = raiseStep(found.raiseCm);
  if (step === null) return [h("p", { class: "fact-note" }, t("stock.raiseTooHigh", { rp, cm: found.raiseCm }))];
  return [h("div", { class: "stock-use" },
    h("p", {}, t("stock.raise", { rp, cm: found.raiseCm, step })),
    h("button", { type: "button", class: "btn btn-secondary", onclick: () => onRaise(step, found.suggested) }, t("stock.raiseUse", { step })))];
}

/** The counted items as plain text, to keep for an insurer. */
function listText(found, photos) {
  const lines = found.items.filter((item) => item.isCounted)
    .map((item) => `- ${item.item}: ${heightText(item.lowest_cm)}, ${range(item.value_rm_low, item.value_rm_high)}`);
  return [t("stock.fileTitle", { date: new Date().toISOString().slice(0, 10) }), "", ...lines, "",
    t("stock.fileTotal", { range: range(found.low, found.high) }), t("stock.fileNote", { n: photos })].join("\n");
}

/** Saves `text` as a file on the device. A blob: link, which iOS Safari saves where it may only open a data: one. */
function saveText(text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  h("a", { href: url, download: t("stock.fileName") }).click();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_MS);   // once the browser has started the download
}

/** The list, the water line, the advice and the buttons. While a photo is read the list cannot change. */
function findings(photos, off, rp, on) {
  const found = combine(photos, off, rp);
  const confidence = CONFIDENCE[found.confidence] ? t(CONFIDENCE[found.confidence]) : found.confidence;
  return [
    itemTable(found, rp, on),
    h("p", {}, floodLine(found, rp)),
    ...raiseAdvice(found, rp, on.onRaise),
    h("p", { class: "fineprint" }, t("stock.guess", { n: photos.length, confidence })),
    found.count > 0 && h("div", { class: "stock-use" },
      h("button", { type: "button", class: "btn btn-primary", onclick: () => on.onUse(found.suggested) }, t("stock.use")),
      h("p", { class: "hint" }, t("stock.useHint", { value: ringgit(found.suggested) }))),
    found.count > 0 && h("div", { class: "stock-use" },
      h("button", { type: "button", class: "btn btn-secondary", onclick: () => saveText(listText(found, photos.length)) }, t("stock.save")),
      h("p", { class: "hint" }, t("stock.saveHint"))),
    h("button", { type: "button", class: "btn btn-link", disabled: on.isBusy, onclick: on.onClear }, t("stock.clear")),
  ];
}

/** One short line for screen readers and eyes: why the latest photo added nothing, or what is counted now. */
function statusLine(state, rp) {
  if (state?.reject) return t(state.reject === "notInside" ? "stock.notInside" : "stock.nothing");
  if (!state?.photos?.length) return "";
  const found = combine(state.photos, state.off ?? [], rp);
  return t("stock.status", { count: found.count, all: found.items.length, range: range(found.low, found.high) });
}

/** The picker's words: reading, the first photo, or another one with how many so far. */
const pickerWords = (state, count) => t(state?.busy ? "common.photoReading" : count ? "stock.addMore" : "stock.add", { n: count + 1, max: MAX_PHOTOS });

/** The card. render(state, rp, placeId) with state {busy, photos, off, reject, error}: the answers of POST /api/stock
 *  that listed things (`photos`), the keys of items the owner unticked (`off`), why the latest photo added nothing
 *  ("notInside" or "nothing"), the flood size on show and the place they are for. onPhoto(file) sends a photo;
 *  onUse(value) puts the value in the cost form; onRaise(cm, value) picks that "put things higher" answer; onToggle(key)
 *  and onClear() change the list. The picker is built once and changed in place, so focus stays; only the short status
 *  line is live, so ticking a box does not read the whole list out again. isReady is false when the build has no Gemini
 *  key: the picker is then off, with a line that says why. */
export function createStockCard({ onPhoto, onUse, onRaise = () => {}, onToggle = () => {}, onClear = () => {}, isReady = true }) {
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "visually-hidden",
    onchange: (event) => { onPhoto(event.target.files[0]); event.target.value = ""; } });
  const words = h("span");
  const picker = h("label", { class: "btn btn-secondary photo-button" }, icon("camera"), words, input);
  const heading = h("h2", { id: "stock-heading", class: "small-heading", tabindex: "-1" }, t("stock.heading"));
  const full = h("p", { class: "hint" }, t("stock.full", { max: MAX_PHOTOS }));
  const alert = h("p", { class: "fact-note", role: "alert" });
  const status = h("p", { class: "stock-status", "aria-live": "polite" });
  const list = h("div", { class: "stock-findings" });
  const node = h("section", { class: "surface stock-card", "aria-labelledby": "stock-heading" }, heading,
    h("p", { class: "hint" }, t("stock.hint")), h("p", { class: "hint" }, t("stock.tips")),
    picker, full, !isReady && h("p", { class: "fact-note ai-off" }, t("common.needsAi")), alert, status, list,
    h("p", { class: "fineprint" }, t("common.photoPrivacy")));
  // Start again takes its own button away: focus goes to the card's heading, not the page
  const on = { onUse, onRaise, onToggle, onClear: () => { onClear(); heading.focus(); } };
  let shown = {};

  /** The picker on or off, with its words; a photo just read gives focus back to it (or, when full, to the heading). */
  function showPicker(state, count, isDone) {
    const isOff = Boolean(state?.busy) || !isReady || count >= MAX_PHOTOS;
    input.disabled = isOff;
    if (isDone && [input, document.body].includes(document.activeElement)) (isOff ? heading : input).focus();
    if (isOff) picker.setAttribute("aria-disabled", "true");
    else picker.removeAttribute("aria-disabled");
    words.textContent = pickerWords(state, count);
    full.hidden = count < MAX_PHOTOS;
  }

  return {
    node,
    render(state, rp, placeId = null) {
      if (state === shown.state && rp === shown.rp && placeId === shown.placeId) return;
      // the same place's photo read: another place's state is not "done" just because it is not busy
      const isDone = placeId === shown.placeId && Boolean(shown.state?.busy) && !state?.busy;
      shown = { state, rp, placeId };
      const photos = state?.photos ?? [];
      showPicker(state, photos.length, isDone);
      alert.textContent = state?.error ?? "";
      alert.hidden = !state?.error;
      status.textContent = statusLine(state, rp);
      status.setAttribute("class", state?.reject ? "stock-status fact-note" : "stock-status");
      // a ticked or unticked box is rebuilt: keep focus on it
      const focusKey = document.activeElement?.getAttribute?.("data-key");
      list.replaceChildren(...(photos.length ? findings(photos, state.off ?? [], rp, { ...on, isBusy: Boolean(state.busy) }) : []).filter(Boolean));
      if (focusKey) list.querySelector(`[data-key="${focusKey}"]`)?.focus();
    },
  };
}
