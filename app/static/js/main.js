import * as api from "./api.js";
import { renderCard } from "./card.js";
import { createChat } from "./chat.js";
import { BANDS, SCENARIOS, band, chanceWithin, h } from "./dom.js";
import { renderHistory } from "./history.js";
import { createMap } from "./map.js";

const PHOTO_MAX_EDGE = 1280;
const PHOTO_QUALITY = 0.85;
const CHANCE_YEARS = 10;   // about one shop lease
const $ = (id) => document.getElementById(id);

function renderLegend(element, hasShelters) {
  const items = [
    ...BANDS.map((b, i) => h("li", {}, h("span", { class: `swatch band-${i + 1}` }), b.words, h("span", { class: "muted" }, b.range))),
    h("li", {}, h("span", { class: "dot dot-dry" }), "No water in the model"),
    hasShelters && h("li", {}, h("span", { class: "shelter-pin" }), "Flood relief centre"),
  ];
  element.replaceChildren(...items.filter(Boolean));
}

/** Shrink and re-encode in the browser: smaller upload, and location data in the file is dropped. */
async function shrinkPhoto(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, PHOTO_MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = h("canvas", { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
  const context = canvas.getContext("2d");
  context.fillStyle = "#fff";   // JPEG has no transparency
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", PHOTO_QUALITY);
}

function start({ premises, town }, status) {
  const params = new URLSearchParams(location.search);
  const byId = new Map(premises.map((p) => [p.id, p]));
  let state = {
    rp: SCENARIOS.includes(params.get("rp")) ? params.get("rp") : "100",
    selectedId: byId.has(params.get("shop")) ? params.get("shop") : premises[0].id,
    photos: {},   // by premise id: { busy, preview, estimate, water_above_floor_m, error }
    listings: {}, // by premise id: { busy } | { configured, place } | { error }
  };

  const map = createMap($("map"), town, premises, (id) => update({ selectedId: id }));
  const ledgerRows = new Map(premises.map((p) => {
    const row = h("button", { type: "button", onclick: () => update({ selectedId: p.id }) },
      h("span", { class: "name" }, p.name),
      SCENARIOS.map((rp) => {
        const level = band(p.depth_m[rp]);
        return h("span", { class: `cell${level ? ` band-${level}` : ""}`, title: `1 in ${rp} years` }, level ? p.depth_m[rp].toFixed(1) : "–");
      }));
    return [p.id, row];
  }));
  $("ledger-heading").textContent = `All ${premises.length} businesses`;
  renderLegend($("legend"), town.shelters.length > 0);
  $("ledger").replaceChildren(...[...ledgerRows.values()].map((row) => h("li", {}, row)));

  async function onPhoto(file) {
    const id = state.selectedId;
    if (!file || state.photos[id]?.busy) return;
    const setPhoto = (photo) => update({ photos: { ...state.photos, [id]: photo } });
    setPhoto({ busy: true });
    try {
      const image = await shrinkPhoto(file).catch(() => { throw new Error("That file could not be read as a photo."); });
      setPhoto({ busy: true, preview: image });
      setPhoto({ preview: image, ...(await api.sendPhoto({ business_id: id, image })) });
    } catch (error) {
      setPhoto({ error: error.message });
    }
    // the card was rebuilt, so put keyboard focus back on the photo picker
    if (state.selectedId === id) $("card").querySelector("input[type=file]")?.focus();
  }

  async function loadListing(id) {
    if (!status.maps_ready || (state.listings[id] && !state.listings[id].error)) return;   // retry after an error
    const setListing = (listing) => update({ listings: { ...state.listings, [id]: listing } });
    setListing({ busy: true });
    try {
      setListing(await api.getPlace(id));
    } catch (error) {
      setListing({ error: error.message });
    }
  }

  function render() {
    const premise = byId.get(state.selectedId);
    map.show(state.rp, state.selectedId);
    renderCard($("card"), premise, state.rp, state.photos[state.selectedId], onPhoto, state.listings[state.selectedId]);
    for (const button of document.querySelectorAll(".scenario button")) {
      button.setAttribute("aria-pressed", String(button.dataset.rp === state.rp));
    }
    for (const [id, row] of ledgerRows) row.setAttribute("aria-current", String(id === state.selectedId));
    const wet = premises.filter((p) => band(p.depth_m[state.rp])).length;
    $("tally").replaceChildren(h("strong", {}, `${wet} of ${premises.length}`), ` businesses get water in the model in a 1 in ${state.rp} years flood.`);
    history.replaceState(null, "", `?shop=${encodeURIComponent(state.selectedId)}&rp=${state.rp}`);
  }

  function update(change) {
    state = { ...state, ...change };
    render();
    loadListing(state.selectedId);
  }

  for (const button of document.querySelectorAll(".scenario button")) {
    const chance = Math.round(chanceWithin(Number(button.dataset.rp), CHANCE_YEARS) * 100);
    button.querySelector(".chance").textContent = `${chance}% chance in ${CHANCE_YEARS} years`;
    button.addEventListener("click", () => update({ rp: button.dataset.rp }));
  }
  createChat({ messages: $("messages"), chips: $("chips"), form: $("ask-form"), input: $("question"), news: $("news"), getSelectedId: () => state.selectedId });
  if (!status.ai_ready) {
    $("ai-status").textContent = "The AI assistant is not connected yet. Add a Gemini key to the .env file and restart.";
    $("ai-status").hidden = false;
  }
  render();
  loadListing(state.selectedId);
  if (status.maps_ready) showRain();
}

const RAIN_TIME = { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kuala_Lumpur" };

async function showRain() {
  try {
    const { rain } = await api.getRain();
    if (!rain) return;
    const time = (iso) => new Date(iso).toLocaleTimeString("en-MY", RAIN_TIME);
    const when = rain.wettest?.start ? ` Heaviest around ${time(rain.wettest.start)}.` : "";
    const asOf = rain.first_hour ? ` Forecast from ${time(rain.first_hour)}.` : "";
    $("rain").replaceChildren(h("strong", {}, `Next ${rain.hours} hours: about ${rain.total_mm} mm of rain`),
      ` around Taman Sri Muda, chance up to ${rain.max_chance_pct}%.${when} `,
      h("span", { class: "muted" }, `Google Weather forecast, not a flood warning.${asOf}`));
    $("rain").hidden = false;
  } catch {
    // the banner is extra: if the forecast is down the rest of the page still works
  }
}

renderHistory($("history"));   // needs no data from the server
try {
  start(...(await Promise.all([api.getData(), api.getStatus()])));
} catch (error) {
  $("load-error").textContent = `The flood data could not be loaded. ${error.message}`;
  $("load-error").hidden = false;
}
