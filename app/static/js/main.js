import * as api from "./api.js";
import { createBusiness } from "./card.js";
import { squaresOf } from "./cells.js";
import { createChat } from "./chat.js";
import { createCost } from "./cost.js";
import { h, roadName } from "./dom.js";
import { DEFAULT_LANG, applyStatic, dateLocale, lang, t, wireLangSwitch } from "./i18n.js";
import { createOverview } from "./overview.js";
import { createPin } from "./pin.js";
import { createPlanCard } from "./plan.js";
import { buildAreaReport } from "./area-report.js";
import { addCompared, createCompareCard } from "./compare.js";
import { businessPlace, isPoint, parseRef, readUrl, snapToGrid, writeUrl } from "./place.js";

const PHOTO_MAX_EDGE = 1280;
const PHOTO_QUALITY = 0.85;
const DEFAULT_RP = "100";
const SLOW_START_MS = 400;   // only a start slower than this says it is loading, so a quick one looks as it did
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
  if (typeof bitmap.close === "function") bitmap.close();   // frees the decoded photo now, not whenever the GC gets to it
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
    let text = `${p.name} · ${roadName(p.road.name)}`;
    for (let n = 2; ids.has(text); n += 1) text = `${p.name} · ${roadName(p.road.name)} (${n})`;
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

// ---------- start-up: what the link asks for, and the data to show it ----------

/** The listed areas, the status and the data of the area the link names, else the default area's. With no area in
 *  the link the default's data is asked for at once, beside the list; a named area waits for the list, to check it is
 *  one. The flood model's coverage (its grids, for points) is asked for now but never waited on before the first view. */
async function loadStart(url) {
  const coverage = api.getCoverage().catch(() => null);   // null: points cannot be checked; businesses still work
  const listing = api.getAreas();
  const chosen = url.area === null ? api.getDefaultData()
    : listing.then((list) => api.getAreaData(list.areas.some((area) => area.id === url.area) ? url.area : list.default));
  const [list, status, data] = await Promise.all([listing, api.getStatus(), chosen]);
  return {
    list, status, coverage, area: data.area, town: data.town,
    premises: data.premises.map((premise) => businessPlace(premise, data.area.id)),
    isAreaMissing: url.area !== null && url.area !== data.area.id,
  };
}

const foundPlace = (place, squares = null) => (place ? { place, squares } : null);

/** What a link names, as {place, squares}: a business of the loaded area, or a point the server checks again (POST
 *  /api/point), snapped here first so that only a square's centre is sent, with the flood squares around it that come
 *  in the same answer (cells.js squaresOf; null for a business). null when this build holds no such place; throws when
 *  the server could not be asked. */
async function linkedPlace(ref, start) {
  const parsed = parseRef(ref);
  if (parsed?.kind === "business") return foundPlace(start.premises.find((premise) => premise.id === parsed.id));
  if (parsed?.kind !== "point" || !start.status.points_ready) return null;
  const coverage = await start.coverage;
  const centre = coverage ? snapToGrid(parsed.lat, parsed.lon, coverage.grids) : parsed;
  if (!centre) return null;
  const answer = await api.checkPoint({ lat: centre.lat, lon: centre.lon, source: "pin" });
  return answer.coverage === "covered" ? foundPlace(answer.place, squaresOf(answer)) : null;
}

const missedWords = (area) => t("main.missed", { area: area.name });

/** The place the link names ({place, squares}, as linkedPlace gives it), when this build holds it, and a note for a link
 *  to an area or place it does not hold (a point in the query counts: points are read only from the fragment).
 *  isFailed: the server could not be asked. */
async function openLink(url, start) {
  const missed = missedWords(start.area);
  if (!url.place) return { linked: null, note: start.isAreaMissing || url.pointInQuery ? missed : null };
  try {
    const linked = await linkedPlace(url.place, start);
    return { linked, note: linked && !start.isAreaMissing ? null : missed };
  } catch (error) {
    return { linked: null, note: `${error.message} ${t("main.showing", { area: start.area.name })}`, isFailed: true };
  }
}

function initialState(url, start, linked) {
  const place = linked?.place ?? start.premises[0];
  return {
    tab: url.tab ?? (linked ? "business" : "overview"),
    rp: url.rp ?? DEFAULT_RP,
    areaId: start.area.id,
    placeKey: place.id,
    points: place.is_point ? { [place.id]: place } : {},   // points checked on this visit, by id
    squares: linked?.squares ? { [place.id]: linked.squares } : {},   // {blocks, cells} that came with the latest point, by its id
    photos: {},    // by place id: { busy, preview, estimate, water_above_floor_m, error }
    stocks: {},    // by place id: { busy, result, error }: the photo of the stock (POST /api/stock)
    plans: {},     // by place id: { busy, result, error }: the flood plan (POST /api/plan)
    planLanguage: lang,   // the plan is written in the page's language unless the owner picks the other
    compare: [],   // ids of the places side by side on My business, oldest first (compare.js)
    listings: {},  // by business id: { busy } | { configured, place } | { error }
    estimates: {}, // by place id: { busy, result } | { result } | { error, result }
    rain: start.status.maps_ready ? { busy: true, configured: true } : { configured: false },
  };   // aim mode, the mode in which a point is picked, is the Area overview's own and lives in pin.js
}

// ---------- the running page ----------

/** The page's state. A change makes a new state object and redraws, passing the old one so views can compare. */
function createStore(initial) {
  let state = initial;
  let redraw = () => {};
  return {
    get state() { return state; },
    listen(onChange) { redraw = onChange; },
    update(change) {
      const previous = state;
      state = { ...state, ...change };
      redraw(state, previous);
    },
  };
}

/** The selected place: a business of the area, or a point checked on this visit. */
const placeOf = (app, state) => app.byId.get(state.placeKey) ?? state.points[state.placeKey];

/** The page's own link (place.js writeUrl): the area only when it is not the default, a point only in the fragment, the
 *  language only when it is not English. A link without one opens in the reader's own remembered choice. */
const linkFor = (app, state) => writeUrl({
  area: state.areaId === app.start.list.default ? null : state.areaId, place: state.placeKey, tab: state.tab, rp: state.rp,
  lang: lang === DEFAULT_LANG ? null : lang,
});

/** Switch tab from a button inside the page, and take keyboard focus to the new tab's heading. */
function goto(app, tab, change = {}) {
  app.store.update({ tab, ...change });
  const panel = $(`panel-${tab}`);
  const heading = panel.querySelector("h1") ?? panel;
  if (heading !== panel) heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
}

// picking a business is what loads its Google Maps listing, so picking it again after an error retries
function select(app, id) {
  app.store.update({ placeKey: id });
  loadListing(app, id);
}

function open(app, id) {
  goto(app, "business", { placeKey: id });
  loadListing(app, id);
}

/** Show a point the server has checked on My business: from a link here, or from a pin or a GPS fix (pin.js), with the
 *  flood squares that came in the same answer ({blocks, cells}, or null). The pin on the map and the squares around it
 *  follow from the selected place, in render. Only the latest point's squares are kept: an older point's were drawn
 *  when it was opened. */
function openPoint(app, place, squares) {
  goto(app, "business", {
    placeKey: place.id, points: { ...app.store.state.points, [place.id]: place }, squares: squares ? { [place.id]: squares } : {},
  });
}

/** Another area is another page (location.assign), so nothing of this one carries over but the flood size. */
function changeArea(app, areaId) {
  location.assign(linkFor(app, { ...app.store.state, areaId, tab: "overview", placeKey: null }));
}

/** The flood model's coverage, for checking points: the one asked for at start-up, else asked for again, as that first
 *  try may have failed. Rejects when the server cannot be asked. */
const coverageOf = async (app) => (await app.start.coverage) ?? api.getCoverage();

/** "Move the pin" on My business: the Area overview's map in aim mode, the cross on the point shown now. */
function movePin(app, pin) {
  goto(app, "overview");
  pin.start({ at: placeOf(app, app.store.state) });
}

async function sendPhoto(app, file) {
  const { store } = app;
  const id = store.state.placeKey;
  if (!file || store.state.photos[id]?.busy) return;
  const setPhoto = (photo) => store.update({ photos: { ...store.state.photos, [id]: photo } });
  const before = store.state.photos[id];   // kept until the new photo is read, and if reading it fails
  setPhoto({ ...before, busy: true, error: null });
  try {
    const image = await shrinkPhoto(file).catch(() => { throw new Error(t("common.photoUnreadable")); });
    setPhoto({ ...before, busy: true, error: null, preview: image });
    setPhoto({ preview: image, ...(await api.sendPhoto({ place: id, image })) });
  } catch (error) {
    setPhoto({ ...before, busy: false, error: error.message });
  }
  // the details were rebuilt; if focus fell to the page, put it back on the photo picker
  if (store.state.placeKey === id && document.activeElement === document.body) {
    $("panel-business").querySelector("input[type=file]")?.focus();
  }
}

/** A photo of the stock inside: Gemini lists it, the server says what is under the modelled water. The last result
 *  stays on show while a new photo is read, and if reading it fails. */
async function sendStock(app, file, floorCm) {
  const { store } = app;
  const id = store.state.placeKey;
  if (store.state.stocks[id]?.busy) return;
  const before = store.state.stocks[id];
  const setStock = (value) => store.update({ stocks: { ...store.state.stocks, [id]: value } });
  setStock({ result: before?.result, busy: true });
  try {
    const image = await shrinkPhoto(file).catch(() => { throw new Error(t("common.photoUnreadable")); });
    setStock({ result: await api.sendStock({ place: id, image, floor_height_cm: floorCm }) });
  } catch (error) {
    setStock({ result: before?.result, error: error.message });
  }
}

/** The figures the plan is written from: the owner's last estimate for this place, else the floor from the shop-front
 *  photo, else none. */
function planFigures(state, id) {
  const inputs = state.estimates[id]?.result?.inputs;
  if (inputs) return inputs;
  const photo = state.photos[id]?.estimate;
  return photo?.is_shop_front ? { floor_height_cm: photo.floor_height_cm } : {};
}

async function writePlan(app, language) {
  const { store } = app;
  const id = store.state.placeKey;
  if (store.state.plans[id]?.busy) return;
  const before = store.state.plans[id];
  const setPlan = (value) => store.update({ plans: { ...store.state.plans, [id]: value } });
  setPlan({ result: before?.result, busy: true });
  try {
    setPlan({ result: await api.writePlan({ place: id, language, ...planFigures(store.state, id) }) });
  } catch (error) {
    setPlan({ result: before?.result, error: error.message });
  }
}

/** Prints one sheet alone (the flood plan or the area summary): a copy goes in #print-root, a child of the body, and
 *  views.css prints only that while it holds something. It is emptied after printing; where the browser never says so
 *  (iOS), the screen is unchanged anyway, as #print-root is never shown on screen. */
function printSheet(sheet) {
  if (!sheet) return;
  let root = $("print-root");
  if (!root) {
    root = h("div", { id: "print-root" });
    document.body.append(root);
    window.addEventListener("afterprint", () => root.replaceChildren());
  }
  root.replaceChildren(sheet.cloneNode(true));
  window.print();
}

async function sendEstimate(app, figures) {
  const { store } = app;
  const id = store.state.placeKey;
  const setEstimate = (estimate) => store.update({ estimates: { ...store.state.estimates, [id]: estimate } });
  const shown = store.state.estimates[id]?.result;
  setEstimate({ busy: true, result: shown });
  try {
    setEstimate({ result: await api.estimate({ place: id, ...figures }) });
  } catch (error) {
    setEstimate({ error: error.message, result: shown });
  }
}

/** How Google Maps lists a business. Never for a point: it is not a business, and it is not sent to Google. */
async function loadListing(app, id) {
  const { store, start } = app;
  const listing = store.state.listings[id];
  if (!start.status.maps_ready || isPoint(id) || (listing && !listing.error)) return;   // retry after an error
  const setListing = (value) => store.update({ listings: { ...store.state.listings, [id]: value } });
  setListing({ busy: true });
  try {
    setListing(await api.getPlace(id));
  } catch (error) {
    setListing({ error: error.message });
  }
}

function loadRain(app) {
  if (!app.start.status.maps_ready) return;
  api.getRain(app.start.area.id).then(
    ({ configured, rain }) => app.store.update({ rain: { configured, data: rain } }),
    () => app.store.update({ rain: { configured: true, error: true } }));
}

/** Opens the place a link names once the page runs: a link that differs from this page only in its fragment (the
 *  browser does not load the page again for it), or Retry after a link that failed. Only the latest call opens its
 *  place, and only if nothing else was picked while the server was asked. */
function linkFollower(app) {
  let latest = 0;
  const follow = async (ref) => {
    const { store, start } = app;
    if (!ref || ref === store.state.placeKey) return;
    const turn = ++latest;
    const from = store.state.placeKey;
    const isCurrent = () => turn === latest && store.state.placeKey === from;
    try {
      const linked = await linkedPlace(ref, start);
      if (!isCurrent()) return;
      showNote(linked ? null : missedWords(start.area));
      if (!linked) history.replaceState(null, "", linkFor(app, store.state));
      else if (linked.place.is_point) openPoint(app, linked.place, linked.squares);
      else open(app, linked.place.id);
    } catch (error) {
      if (isCurrent()) showNote(error.message, () => follow(ref));
    }
  };
  return follow;
}

/** The flood plan and the compare card under My business, and the area summary's print button. */
function createExtras(app) {
  const { start, store } = app;
  const plan = createPlanCard({
    onWrite: (language) => writePlan(app, language), onPrint: () => printSheet($("panel-business").querySelector(".plan-sheet")),
    onLanguage: (planLanguage) => store.update({ planLanguage }),
  });
  $("print-area").addEventListener("click", () => printSheet(buildAreaReport({
    area: start.area, premises: start.premises, date: new Date().toLocaleDateString(dateLocale(), { day: "numeric", month: "short", year: "numeric" }),
  })));
  const compare = createCompareCard({
    onAdd: (id) => store.update({ compare: addCompared(store.state.compare, id) }),
    onRemove: (id) => store.update({ compare: store.state.compare.filter((kept) => kept !== id) }),
    onOpen: (place) => (place.is_point ? openPoint(app, place, null) : open(app, place.id)),
  });
  $("panel-business").append(plan.node, compare.node);
  return { plan, compare };
}

function createViews(app) {
  const { start, store } = app;
  const pickRp = (rp) => store.update({ rp });
  const overview = createOverview({
    area: start.area, areas: start.list.areas, premises: start.premises, town: start.town, onPick: pickRp,
    onSelect: (id) => select(app, id), onOpen: (id) => open(app, id),
    onArea: (areaId) => changeArea(app, areaId),
    // "Check any point in Malaysia", and the map's own button: aim mode and the location go in pin.js
    onCheckPoint: start.status.points_ready ? (opener) => pin.start({ opener }) : null,
  });
  const pin = createPin({
    map: overview.map, anchor: $("map"), area: start.area, tabBar: document.querySelector(".tabs"),
    getCoverage: () => coverageOf(app),
    onChecked: (place, squares) => openPoint(app, place, squares),
  });
  const business = createBusiness($("panel-business"), {
    area: start.area, areas: start.list.areas, onPhoto: (file) => sendPhoto(app, file), onPick: pickRp, goto: (tab) => goto(app, tab),
    showOnMap: () => { goto(app, "overview"); overview.map.focus(store.state.placeKey); },
    onMovePin: () => movePin(app, pin),
    // a point in another listed area: that area's own page, with the point kept (it travels in the fragment)
    onOpenArea: (areaId) => location.assign(linkFor(app, { ...store.state, areaId })),
  });
  const { plan, compare } = createExtras(app);
  const cost = createCost($("panel-cost"), {
    onEstimate: (figures) => sendEstimate(app, figures), onStockPhoto: (file, floorCm) => sendStock(app, file, floorCm),
  });
  const showTab = wireTabs((tab) => store.update({ tab }));   // the tab bar keeps focus on the tab itself
  wireFinder(start.premises, (id) => open(app, id), (needle) => {   // nothing matched: show the filtered list instead
    $("directory-filter").value = needle;
    $("directory-filter").dispatchEvent(new Event("input"));
    goto(app, "overview");
    $("directory-filter").scrollIntoView({ block: "center" });
  });
  const chat = createChat({
    messages: $("messages"), chips: $("chips"), form: $("ask-form"), input: $("question"), news: $("news"),
    getPlaceRef: () => store.state.placeKey, areaId: start.area.id, areaName: start.area.name, areas: start.list.areas,
  });
  return { overview, business, cost, chat, showTab, pin, plan, compare };
}

function render(app, views, state, previous) {
  const place = placeOf(app, state);
  const photo = state.photos[state.placeKey];
  views.showTab(state.tab);
  views.overview.render({ rp: state.rp, selectedId: state.placeKey, rain: state.rain });
  views.business.render({ premise: place, rp: state.rp, photo, listing: state.listings[state.placeKey] });
  views.cost.render(place, photo?.estimate?.is_shop_front ? photo.estimate.floor_height_cm : null, state.estimates[state.placeKey],
    state.stocks[state.placeKey], state.rp);
  views.plan.render(state.plans[state.placeKey], state.planLanguage);
  views.compare.render({ current: place, compared: state.compare.map((id) => placeOf(app, { ...state, placeKey: id })).filter(Boolean) });
  views.chat.render(place);   // the chips, the question box and the flood news that fit the place
  $("ask-business").textContent = place.is_point ? t("ask.thisPoint") : place.name;
  views.pin.render({ tab: state.tab, place, squares: state.squares[state.placeKey] });   // ends aim mode off the Area overview; puts a point's pin and its squares on the map
  if (previous && previous.tab !== state.tab) {
    if (state.tab === "overview") views.overview.map.refresh();   // the map was measured while its tab was hidden
    window.scrollTo({ top: 0 });
  }
  history.replaceState(null, "", linkFor(app, state));
}

/** The area's name in the header. It comes from the area's config: the page itself names no place. */
function showAreaName(area) {
  $("area-name").textContent = area.display_name;
  $("area-name").hidden = false;
}

function startApp(start, initial) {
  const app = { start, byId: new Map(start.premises.map((premise) => [premise.id, premise])), store: createStore(initial) };
  showAreaName(start.area);
  const views = createViews(app);
  app.store.listen((state, previous) => render(app, views, state, previous));
  if (!start.status.ai_ready) {
    $("ai-status").textContent = t("main.aiOff");
    $("ai-status").hidden = false;
  }
  render(app, views, initial, null);
  loadListing(app, initial.placeKey);
  loadRain(app);
  const follow = linkFollower(app);
  window.addEventListener("hashchange", () => follow(readUrl(location).place));
  return follow;
}

/** The note about a link, with a Retry button when the server could not be asked; no text hides it. */
function showNote(text, onRetry = null) {
  const retry = onRetry && h("button", { type: "button", class: "btn btn-secondary", onclick: onRetry }, t("common.retry"));
  $("link-note").replaceChildren(...[text, retry].filter(Boolean));
  $("link-note").hidden = !text;
}

function showStartError(error) {
  $("load-error").replaceChildren(`${t("main.loadFailed")} ${error.message}`,
    h("button", { type: "button", class: "btn btn-secondary", onclick: () => location.reload() }, t("common.retry")));
  $("load-error").hidden = false;
}

/** Read the link, load what it needs and start the page. A slow start says so; a failed one says why, with Retry. */
async function main() {
  const loading = $("loading");
  const slow = setTimeout(() => { loading.textContent = t("main.loading"); }, SLOW_START_MS);
  try {
    const url = readUrl(location);
    if (url.pointInQuery) history.replaceState(null, "", writeUrl(url));   // before any request can send it as Referer
    const start = await loadStart(url);
    const { linked, note, isFailed } = await openLink(url, start);
    const follow = startApp(start, initialState(url, start, linked));
    showNote(note, isFailed ? () => follow(url.place) : null);
  } catch (error) {
    showStartError(error);
  } finally {
    clearTimeout(slow);
    loading.textContent = "";
  }
}

applyStatic(document);   // index.html's own words in the page's language, and <html lang>, before anything is drawn
wireLangSwitch(document);
main();
