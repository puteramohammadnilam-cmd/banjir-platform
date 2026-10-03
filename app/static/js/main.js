import * as api from "./api.js";
import { createBusiness } from "./card.js";
import { createChat } from "./chat.js";
import { createCost } from "./cost.js";
import { SCENARIOS, h } from "./dom.js";
import { createOverview } from "./overview.js";

const TABS = ["overview", "business", "cost", "ask"];
const PHOTO_MAX_EDGE = 1280;
const PHOTO_QUALITY = 0.85;
const $ = (id) => document.getElementById(id);

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

/** Tabs as in the ARIA pattern: arrow keys, Home and End move between them; only the chosen one is in the tab order. */
function wireTabs(onPick) {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => onPick(tab.dataset.tab));
    tab.addEventListener("keydown", (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: tabs.length - 1 - i }[event.key];
      if (step === undefined) return;
      event.preventDefault();
      const next = tabs[(i + step + tabs.length) % tabs.length];
      next.focus();
      onPick(next.dataset.tab);
    });
  });
  return (current) => {
    for (const tab of tabs) {
      const selected = tab.dataset.tab === current;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      $(tab.getAttribute("aria-controls")).hidden = !selected;
    }
  };
}

/** The header search: the browser's own suggestion list, one entry per business, made unique with its road. */
function wireFinder(premises, onOpen, onNoMatch) {
  const ids = new Map();
  for (const p of [...premises].sort((a, b) => a.name.localeCompare(b.name))) {
    let text = `${p.name} · ${p.road.name}`;
    for (let n = 2; ids.has(text); n += 1) text = `${p.name} · ${p.road.name} (${n})`;
    ids.set(text, p.id);
  }
  $("business-names").replaceChildren(...[...ids.keys()].map((text) => h("option", { value: text })));
  const input = $("finder-input");
  const open = (id) => { input.value = ""; input.blur(); onOpen(id); };
  input.addEventListener("input", () => { if (ids.has(input.value)) open(ids.get(input.value)); });
  $("finder").addEventListener("submit", (event) => {
    event.preventDefault();
    const needle = input.value.trim().toLowerCase();
    if (!needle) return;
    const hit = [...ids].find(([text]) => text.toLowerCase().includes(needle));
    if (hit) open(hit[1]);
    else onNoMatch(needle);
  });
}

function start({ premises, town }, status) {
  const params = new URLSearchParams(location.search);
  const byId = new Map(premises.map((p) => [p.id, p]));
  const shop = byId.has(params.get("shop")) ? params.get("shop") : null;
  let state = {
    tab: TABS.includes(params.get("tab")) ? params.get("tab") : shop ? "business" : "overview",
    rp: SCENARIOS.includes(params.get("rp")) ? params.get("rp") : "100",
    selectedId: shop ?? premises[0].id,
    photos: {},    // by premise id: { busy, preview, estimate, water_above_floor_m, error }
    listings: {},  // by premise id: { busy } | { configured, place } | { error }
    estimates: {}, // by premise id: { busy, result } | { result } | { error, result }
    rain: status.maps_ready ? { busy: true, configured: true } : { configured: false },
  };

  const pickRp = (rp) => update({ rp });
  /** Switch tab from a button inside the page, and take keyboard focus to the new tab's heading. */
  const goto = (tab, change = {}) => {
    update({ tab, ...change });
    const panel = $(`panel-${tab}`);
    const heading = panel.querySelector("h1") ?? panel;
    if (heading !== panel) heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  };
  // picking a shop is what loads its Google Maps listing, so picking it again after an error retries
  const select = (id) => { update({ selectedId: id }); loadListing(id); };
  const open = (id) => { goto("business", { selectedId: id }); loadListing(id); };
  const overview = createOverview({ premises, town, onSelect: select, onOpen: open, onPick: pickRp });
  const business = createBusiness($("panel-business"), {
    onPhoto, onPick: pickRp, goto,
    showOnMap: () => { goto("overview"); overview.map.focus(state.selectedId); },
  });
  const cost = createCost($("panel-cost"), { onEstimate });
  const showTab = wireTabs((tab) => update({ tab }));   // the tab bar keeps focus on the tab itself
  wireFinder(premises, open, (needle) => {   // nothing matched: show the filtered list instead
    $("directory-filter").value = needle;
    $("directory-filter").dispatchEvent(new Event("input"));
    goto("overview");
    $("directory-filter").scrollIntoView({ block: "center" });
  });

  async function onPhoto(file) {
    const id = state.selectedId;
    if (!file || state.photos[id]?.busy) return;
    const setPhoto = (photo) => update({ photos: { ...state.photos, [id]: photo } });
    const before = state.photos[id];   // kept until the new photo is read, and if reading it fails
    setPhoto({ ...before, busy: true, error: null });
    try {
      const image = await shrinkPhoto(file).catch(() => { throw new Error("That file could not be read as a photo."); });
      setPhoto({ ...before, busy: true, error: null, preview: image });
      setPhoto({ preview: image, ...(await api.sendPhoto({ business_id: id, image })) });
    } catch (error) {
      setPhoto({ ...before, busy: false, error: error.message });
    }
    // the details were rebuilt; if focus fell to the page, put it back on the photo picker
    if (state.selectedId === id && document.activeElement === document.body) {
      $("panel-business").querySelector("input[type=file]")?.focus();
    }
  }

  async function onEstimate(figures) {
    const id = state.selectedId;
    const setEstimate = (estimate) => update({ estimates: { ...state.estimates, [id]: estimate } });
    const shown = state.estimates[id]?.result;
    setEstimate({ busy: true, result: shown });
    try {
      setEstimate({ result: await api.estimate({ business_id: id, ...figures }) });
    } catch (error) {
      setEstimate({ error: error.message, result: shown });
    }
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

  function render(previous) {
    const premise = byId.get(state.selectedId);
    const photo = state.photos[state.selectedId];
    showTab(state.tab);
    overview.render(state);
    business.render({ premise, rp: state.rp, photo, listing: state.listings[state.selectedId] });
    cost.render(premise, photo?.estimate?.is_shop_front ? photo.estimate.floor_height_cm : null, state.estimates[state.selectedId]);
    $("ask-business").textContent = premise.name;
    if (previous && previous.tab !== state.tab) {
      if (state.tab === "overview") overview.map.refresh();   // the map was measured while its tab was hidden
      window.scrollTo({ top: 0 });
    }
    history.replaceState(null, "", `?tab=${state.tab}&shop=${encodeURIComponent(state.selectedId)}&rp=${state.rp}`);
  }

  function update(change) {
    const previous = state;
    state = { ...state, ...change };
    render(previous);
  }

  createChat({ messages: $("messages"), chips: $("chips"), form: $("ask-form"), input: $("question"), news: $("news"), getSelectedId: () => state.selectedId });
  if (!status.ai_ready) {
    $("ai-status").textContent = "The AI assistant is not connected yet. Add a Gemini key to the .env file and restart.";
    $("ai-status").hidden = false;
  }
  render(null);
  loadListing(state.selectedId);
  if (status.maps_ready) {
    api.getRain().then(
      ({ configured, rain }) => update({ rain: { configured, data: rain } }),
      () => update({ rain: { configured: true, error: true } }));
  }
}

try {
  start(...(await Promise.all([api.getData(), api.getStatus()])));
} catch (error) {
  $("load-error").textContent = `The flood data could not be loaded. ${error.message}`;
  $("load-error").hidden = false;
}
