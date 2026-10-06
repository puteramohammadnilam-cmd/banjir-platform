import * as api from "./api.js";
import { createBusiness } from "./card.js";
import { createChat } from "./chat.js";
import { createChatWidget } from "./chat-widget.js";
import { createCost, estimateState, needsFirstLook } from "./cost.js";
import { h } from "./dom.js";
import { DEFAULT_LANG, applyStatic, dateLocale, lang, t, wireLangSwitch } from "./i18n.js";
import { createInsurance } from "./insurance.js";
import { createOverview, mapFrame } from "./overview.js";
import { createPin } from "./pin.js";
import { createPlanCard, planFigures } from "./plan.js";
import { syncReferenceNav, wireReferenceNav } from "./reference.js";
import { MAX_PHOTOS } from "./stock.js";
import { createFloodMode } from "./floodmode.js";
import { buildAreaReport } from "./area-report.js";
import { addCompared, createCompareCard } from "./compare.js";
import { initialState, rememberPlace, sectionFinder, wireFinder } from "./pick.js";
import { isPoint, pageLink, readUrl, writeUrl } from "./place.js";
import { isCityView, linkedPlace, loadCityIndex, loadStart, missedWords, openLink, sectionOf } from "./start.js";
import * as realVoice from "./voice.js";

const PHOTO_MAX_EDGE = 1280;
const PHOTO_QUALITY = 0.85;
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

/** The view a link names (place.js writeUrl): the area only when it is not the default, the page's section (sectionId:
 *  another section's, null for the whole city), a point only in the fragment, the language only when it is not
 *  English. A link without one opens in the reader's own remembered choice. Another area's link names no section. */
const viewFor = (app, state, { sectionId = app.start.section?.id ?? null } = {}) => ({
  area: state.areaId === app.start.list.default ? null : state.areaId,
  section: state.areaId === app.start.area.id ? sectionId : null,
  place: state.placeKey, tab: state.tab, rp: state.rp, lang: lang === DEFAULT_LANG ? null : lang,
});

/** The page's own link, tab included. */
const linkFor = (app, state, options) => writeUrl(viewFor(app, state, options));

/** The link to another area's or section's page (place.js pageLink): no tab, so its query is the same whether or not a
 *  point goes along in the fragment. That page still asks for its own data (a section's is its own request), as every
 *  visit to it does. */
const otherPageLink = (app, state, options) => pageLink(viewFor(app, state, options));

/** Switch tab from a button inside the page, and take keyboard focus to the new tab's heading. */
function goto(app, tab, change = {}) {
  app.store.update({ tab, ...change });
  const panel = $(`panel-${tab}`);
  const heading = panel.querySelector("h1") ?? panel;
  if (heading !== panel) heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
}

// picking a business is what loads its Google Maps listing, so picking it again after an error retries. A business
// someone picked is remembered for their next visit (pick.js); one a link opened is not, as someone else chose it.
function select(app, id) {
  rememberPlace(app.start.area.id, id);
  app.store.update({ placeKey: id });
  loadListing(app, id);
  loadDrySpot(app, id);   // picking it again after an error asks again
}

/** A business of the city that is not on this page (the whole city's list and search, or a section's search once the
 *  city's index is in) is on its section's page: that page, on My business. False when no index names its section. */
function openElsewhere(app, id) {
  const section = sectionOf(app.cityIndex ?? app.start.index, id);
  if (!section) return false;
  location.assign(otherPageLink(app, { ...app.store.state, placeKey: id }, { sectionId: section }));
  return true;
}

function open(app, id, { isPicked = true } = {}) {
  if (!app.byId.has(id) && openElsewhere(app, id)) return;
  if (isPicked) rememberPlace(app.start.area.id, id);
  goto(app, "business", { placeKey: id });
  loadListing(app, id);
  loadDrySpot(app, id);
}

/** "Find your shop": the Area overview, with focus in its search. */
function findShop(app) {
  goto(app, "overview");
  $("finder-hero-input").focus();
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
  location.assign(otherPageLink(app, { ...app.store.state, areaId, placeKey: null }));
}

/** The link to a section's Area overview (null: the whole city's), with the flood size on show. */
const sectionLink = (app, sectionId) => otherPageLink(app, { ...app.store.state, placeKey: null }, { sectionId });

/** Another section, or the whole city, is another page too, opened the same way. */
function changeSection(app, sectionId) {
  location.assign(sectionLink(app, sectionId));
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

/** A photo of the stock inside: Gemini lists it, the server says what is under the modelled water. A photo that lists
 *  something is added to the place's photos (stock.js MAX_PHOTOS); one that lists nothing only says why. The photos so
 *  far stay on show while a new one is read, and if reading it fails. */
async function sendStock(app, file, floorCm) {
  const { store } = app;
  const id = store.state.placeKey;
  // one photo at a time, and no more than the card takes: a fifth would shift the keys of the items left out
  if (store.state.stocks[id]?.busy || (store.state.stocks[id]?.photos?.length ?? 0) >= MAX_PHOTOS) return;
  const before = { photos: [], off: [], ...store.state.stocks[id], reject: null, error: null };
  const setStock = (value) => store.update({ stocks: { ...store.state.stocks, [id]: value } });
  setStock({ ...before, busy: true });
  try {
    const image = await shrinkPhoto(file).catch(() => { throw new Error(t("common.photoUnreadable")); });
    const result = await api.sendStock({ place: id, image, floor_height_cm: floorCm, language: lang });
    const reject = !result.estimate.is_shop_inside ? "notInside" : !result.estimate.items.length ? "nothing" : null;
    setStock({ ...before, reject, photos: reject ? before.photos : [...before.photos, result] });
  } catch (error) {
    setStock({ ...before, error: error.message });
  }
}

/** Counts a listed item in or out (key "photo-item"), or starts the place's stock photos again. */
function toggleStock(app, key) {
  const { store } = app;
  const id = store.state.placeKey;
  const now = store.state.stocks[id];
  if (!now?.photos) return;
  const off = now.off.includes(key) ? now.off.filter((k) => k !== key) : [...now.off, key];
  store.update({ stocks: { ...store.state.stocks, [id]: { ...now, off } } });
}
const clearStock = (app) => app.store.update({ stocks: { ...app.store.state.stocks, [app.store.state.placeKey]: undefined } });

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

/** Work out the cost for the place on show. isAssumed marks the first look the tab works out by itself (estimateState). */
async function sendEstimate(app, figures, { isAssumed = false } = {}) {
  const { store } = app;
  const id = store.state.placeKey;
  const setEstimate = (estimate) => store.update({ estimates: { ...store.state.estimates, [id]: estimate } });
  const before = store.state.estimates[id];
  setEstimate(estimateState.busy(before, isAssumed));
  try {
    setEstimate(estimateState.done(await api.estimate({ place: id, ...figures }), isAssumed));
  } catch (error) {
    setEstimate(estimateState.failed(before, error.message, isAssumed));
  }
}

/** Flood cost opens with an answer: the first time a place is on show there, the form's figures as they stand (a
 *  typical medium shop unless the owner has typed others) are worked out as a first look. */
function estimateOnOpen(app, views, state, place) {
  if (!needsFirstLook(state, place)) return;
  const figures = views.cost.figures();
  if (figures) sendEstimate(app, figures, { isAssumed: true });
}

/** How Google Maps lists a business. Never for a point: it is not a business, and it is not sent to Google. */
async function loadListing(app, id) {
  const { store, start } = app;
  const listing = store.state.listings[id];
  if (!id || !start.status.maps_ready || isPoint(id) || (listing && !listing.error)) return;   // retry after an error
  const setListing = (value) => store.update({ listings: { ...store.state.listings, [id]: value } });
  setListing({ busy: true });
  try {
    setListing(await api.getPlace(id));
  } catch (error) {
    setListing({ error: error.message });
  }
}

/** What the "Flood is coming" checklist is worked out from: the place on show and its flood size, the floor height a
 *  shop-front photo gave, its stock photos and where to move the car. */
function floodContext(app) {
  const { state } = app.store;
  const id = state.placeKey;
  const photo = state.photos[id]?.estimate;
  return { premise: placeOf(app, state), rp: state.rp, floorCm: photo?.is_shop_front ? photo.floor_height_cm : 0,
    stock: state.stocks[id], dry: state.drySpots[id] };
}

/** Where to move the car, for a business or a point: asked once per place, and again when a place whose answer was an
 *  error is picked again (select, open). render asks for a place it has no answer for. */
async function loadDrySpot(app, id) {
  const { store } = app;
  const known = store.state.drySpots[id];
  if (!id || (known && !known.error)) return;
  const setDry = (value) => store.update({ drySpots: { ...store.state.drySpots, [id]: value } });
  setDry({ busy: true });
  try {
    setDry(await api.getDrySpot(id));
  } catch (error) {
    setDry({ error: error.message });
  }
}

function loadRain(app) {
  if (!app.start.status.maps_ready) return;
  api.getRain(app.start.area.id, app.start.section?.id).then(
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
      showNote(linked ? null : missedWords(start.page));
      if (!linked) history.replaceState(null, "", linkFor(app, store.state));
      else if (linked.place.is_point) openPoint(app, linked.place, linked.squares);
      else open(app, linked.place.id, { isPicked: false });
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
    isReady: start.status.ai_ready,
    onWrite: (language) => writePlan(app, language), onPrint: () => printSheet($("panel-business").querySelector(".plan-sheet")),
    onLanguage: (planLanguage) => store.update({ planLanguage }),
  });
  const isCity = isCityView(start);   // the whole city's summary: from the index, with its sections ranked
  $("print-area").addEventListener("click", () => printSheet(buildAreaReport({
    area: start.page, premises: isCity ? start.index : start.premises, sections: isCity ? start.sections : null, word: start.area.section_word,
    date: new Date().toLocaleDateString(dateLocale(), { day: "numeric", month: "short", year: "numeric" }),
  })));
  const compare = createCompareCard({
    onAdd: (id) => store.update({ compare: addCompared(store.state.compare, id) }),
    onRemove: (id) => store.update({ compare: store.state.compare.filter((kept) => kept !== id) }),
    onOpen: (place) => (place.is_point ? openPoint(app, place, null) : open(app, place.id)),
    onFind: () => findShop(app),
  });
  $("panel-business").append(plan.node, compare.node);
  return { plan, compare };
}

/** The businesses on this page, then the rest of the city's (from its index) for a section's search. */
const withCity = (premises, index) => {
  const here = new Set(premises.map((premise) => premise.id));
  return [...premises, ...index.filter((row) => !here.has(row.id))];
};

/** On a section's page the search, and the list's filter, reach the whole city once the city's index is in: asked for
 *  the first time a search box or the filter is used, and waited for by Enter. Gives back the function that starts it
 *  (null on other pages). A failed load is asked for again on the next search; until then the search covers this
 *  section, its city's sections and their names. */
function cityIndexLoader(app, finder, overview) {
  if (!app.start.section) return null;
  let loading = null;
  return () => {
    if (app.cityIndex) return null;
    loading ??= loadCityIndex(app.start).then((index) => {
      app.cityIndex = index;
      finder.current.setPlaces(withCity(app.start.premises, index));
      overview.widen(index);   // a search several businesses of the city match lists them all, from any section
    }, () => { loading = null; });
    return loading;
  };
}

/** The two search boxes, the header's and the Area overview's, and the overview's "Check any point in Malaysia" (shown
 *  only where points can be checked). A name that could mean several businesses, or none, shows the list of businesses,
 *  filtered by it, saying how many match or what to do next (overview.js). In a city they find its sections and its
 *  old areas' names too, and a business of another section opens on that section's page. */
function wireWaysIn(app, checkPoint, overview) {
  const { start } = app;
  const forms = [[$("finder"), $("finder-input")], [$("finder-hero"), $("finder-hero-input")]];
  const named = start.area.has_sections
    ? sectionFinder(start.sections, start.area.aliases, start.area.section_word, start.area.name) : { entries: [], synonyms: new Map() };
  const finder = { current: null };
  const ready = cityIndexLoader(app, finder, overview);
  finder.current = wireFinder({ datalist: $("business-names"), forms }, isCityView(start) ? start.index : start.premises,
    (target) => (typeof target === "string" ? open(app, target) : changeSection(app, target.section)), (text) => {
      overview.showMatches(text);
      goto(app, "overview");
      $("directory-filter").scrollIntoView({ block: "center" });
      $("directory-filter").focus({ preventScroll: true });   // where the typed name now is, and the list it filters
    }, { extra: named.entries, synonyms: named.synonyms, ready });
  if (ready) for (const input of [...forms.map(([, box]) => box), $("directory-filter")]) input.addEventListener("focus", ready);
  if (!checkPoint) return;
  $("hero-check").addEventListener("click", (event) => checkPoint(event.currentTarget));
  $("hero-point").hidden = false;
}

/** What the Area overview needs of a city split into sections (null for a plain area): see overview.js createOverview. */
function cityOf(app) {
  const { start } = app;
  if (!start.area.has_sections) return null;
  return {
    sections: start.sections, word: start.area.section_word, section: start.section, index: start.index,
    wholeCity: !start.area.default_section, onSection: (id) => changeSection(app, id), hrefOf: (id) => sectionLink(app, id),
    cityHref: () => sectionLink(app, null), cityName: start.area.name,
  };
}

function createViews(app) {
  const { start, store } = app;
  const pickRp = (rp) => store.update({ rp });
  const widget = createChatWidget({ button: $("chat-fab"), dialog: $("chat-dialog"), input: $("question"), onClose: realVoice.stopSpeaking });
  // the overview's "Check any point in Malaysia" and the map's own button: aim mode and the location go in pin.js
  const checkPoint = start.status.points_ready ? (opener) => pin.start({ opener }) : null;
  // the same from an empty My business or Flood cost, where the map is first brought on show
  const empty = { onFind: () => findShop(app), onCheckPoint: checkPoint && (() => { goto(app, "overview"); checkPoint($("hero-check")); }) };
  const city = cityOf(app);
  const overview = createOverview({
    area: start.page, areas: start.list.areas, premises: start.premises, town: start.town, onPick: pickRp,
    onSelect: (id) => select(app, id), onOpen: (id) => open(app, id),
    onArea: (areaId) => changeArea(app, areaId), onCheckPoint: checkPoint, city,
  });
  const pin = createPin({   // a point's squares are drawn unless the page's own squares cover it (none on a whole city's map)
    map: overview.map, anchor: $("map"), area: { ...start.page, view: mapFrame(start.page, city).ownedBox }, tabBar: document.querySelector(".tabs"),
    getCoverage: () => coverageOf(app),
    onChecked: (place, squares) => openPoint(app, place, squares),
  });
  const floodMode = createFloodMode();
  const business = createBusiness($("panel-business"), {
    onWarning: (opener) => floodMode.open(floodContext(app), opener),
    area: start.page, areas: start.list.areas, onPhoto: (file) => sendPhoto(app, file), onPick: pickRp, goto: (tab) => goto(app, tab),
    showOnMap: () => { goto(app, "overview"); overview.map.focus(store.state.placeKey); },
    onMovePin: () => movePin(app, pin), onAsk: (opener) => widget.open(opener), ...empty, isReady: start.status.ai_ready, hasMaps: start.status.maps_ready,
    // a point in another listed area, or in another section of this city (or in the whole city's view): that page, on My
    // business, the point only in the fragment and the query as any move to that page (otherPageLink)
    onOpenArea: (areaId) => location.assign(otherPageLink(app, { ...store.state, areaId })),
    onOpenSection: (sectionId) => location.assign(otherPageLink(app, store.state, { sectionId })),
  });
  const { plan, compare } = createExtras(app);
  const cost = createCost($("panel-cost"), {
    onEstimate: (figures) => sendEstimate(app, figures), onPick: pickRp, onStockPhoto: (file, floorCm) => sendStock(app, file, floorCm),
    onStockToggle: (key) => toggleStock(app, key), onStockClear: () => clearStock(app), ...empty,
    // as My business: the page's own area's example, for a business or a point in that area
    floodExample: (place) => (!place.is_point || place.area_id === start.page.id ? start.page.bigger_flood_example : null),
    isReady: start.status.ai_ready,
  });
  const insurance = createInsurance($("panel-insurance"), { goto: (tab) => goto(app, tab), ...empty });
  const showTab = wireTabs((tab) => store.update({ tab }));   // the tab bar keeps focus on the tab itself
  for (const link of document.querySelectorAll("[data-goto]")) link.addEventListener("click", () => goto(app, link.dataset.goto));
  wireWaysIn(app, checkPoint, overview);
  const chat = createChat({
    messages: $("messages"), chips: $("chips"), form: $("ask-form"), input: $("question"), news: $("news"),
    getPlaceRef: () => store.state.placeKey, areaId: start.area.id, sectionId: start.section?.id ?? null, areaName: start.page.name, areas: start.list.areas,
    isReady: start.status.ai_ready, hasMaps: start.status.maps_ready,
    voice: { ...realVoice, speak: (text, language) => widget.isOpen && realVoice.speak(text, language) },   // a late answer is not read to a closed chat
  });
  return { overview, business, cost, insurance, chat, widget, showTab, pin, plan, compare, floodMode };
}

/** What the chat's "About" line names: the place, or the area while none is picked. */
const askingAbout = (app, place) => (!place ? app.start.page.name : place.is_point ? t("ask.thisPoint") : place.name);

/** The flood plan and the compare card are about a place: with none picked they are off. */
function renderExtras(app, views, state, place) {
  views.plan.node.hidden = !place;
  views.compare.node.hidden = !place;
  views.plan.render(state.plans[state.placeKey], state.planLanguage);
  views.compare.render({ current: place, compared: state.compare.map((id) => placeOf(app, { ...state, placeKey: id })).filter(Boolean) });
}

/** The Reference tab's "On this page" buttons, each with the id of the heading it jumps to. */
const referenceLinks = () => [...document.querySelectorAll(".ref-nav [data-jump]")]
  .map((button) => ({ item: button.closest("li"), target: button.getAttribute("data-jump") }));

/** Draws every view for `state`. No place may be picked yet (placeKey null): My business and Flood cost then show how
 *  to pick one, and the rest leave it out. */
function render(app, views, state, previous) {
  const place = placeOf(app, state);
  const photo = state.photos[state.placeKey];
  views.showTab(state.tab);
  if (state.tab === "reference") syncReferenceNav(referenceLinks(), (id) => $(id)?.closest("section"));
  document.body.dataset.tab = state.tab;   // views.css: the header's search steps aside on the Area overview, which has its own
  views.overview.render({ rp: state.rp, selectedId: state.placeKey, rain: state.rain });
  views.business.render({ premise: place, rp: state.rp, photo, listing: state.listings[state.placeKey], dry: state.drySpots[state.placeKey] });
  if (place && !state.drySpots[state.placeKey]) queueMicrotask(() => loadDrySpot(app, state.placeKey));   // after this draw
  if (place) views.floodMode.refresh(floodContext(app));   // the car step, when its answer comes while the checklist is open
  views.cost.render(place, photo?.estimate?.is_shop_front ? photo.estimate.floor_height_cm : null, state.estimates[state.placeKey],
    state.stocks[state.placeKey], state.rp);
  views.insurance.render(place, state.estimates[state.placeKey]);
  renderExtras(app, views, state, place);
  views.chat.render(place);   // the chips, the question box and the flood news that fit the place
  $("chat-about").textContent = t("chat.about", { place: askingAbout(app, place) });
  views.pin.render({ tab: state.tab, place, squares: state.squares[state.placeKey] });   // ends aim mode off the Area overview; puts a point's pin and its squares on the map
  if (previous && previous.tab !== state.tab) {
    if (state.tab === "overview") views.overview.map.refresh();   // the map was measured while its tab was hidden
    window.scrollTo({ top: 0 });
  }
  history.replaceState(null, "", linkFor(app, state));
  estimateOnOpen(app, views, state, place);   // last: it updates the store, which draws again
}

/** The area's name in the header. It comes from the area's config: the page itself names no place. */
function showAreaName(area) {
  $("area-name").textContent = area.display_name;
  $("area-name").hidden = false;
}

function startApp(start, initial, url) {
  const app = { start, byId: new Map(start.premises.map((premise) => [premise.id, premise])), store: createStore(initial), cityIndex: null };
  showAreaName(start.page);
  const views = createViews(app);
  app.store.listen((state, previous) => render(app, views, state, previous));
  if (!start.status.ai_ready) {
    $("ai-status").textContent = t("main.aiOff");
    $("ai-status").hidden = false;
  }
  if (!start.status.maps_ready) $("ask-lead").textContent = t("ask.leadNoMaps");   // no Weather or Maps to read
  render(app, views, initial, null);   // also takes ?tab=ask out of the address
  if (url.chat) views.widget.open();   // the old Ask AI tab's link: the page's own tab, with the chat over it
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
    document.body.dataset.tab = url.tab ?? "overview";   // before the first await, so a deep link's header does not shift
    if (url.pointInQuery) history.replaceState(null, "", writeUrl(url));   // before any request can send it as Referer
    const start = await loadStart(url);
    const { linked, note, isFailed } = await openLink(url, start);
    const follow = startApp(start, initialState(url, start, linked), url);
    showNote(note, isFailed ? () => follow(url.place) : null);
  } catch (error) {
    showStartError(error);
  } finally {
    clearTimeout(slow);
    loading.textContent = "";
  }
}

applyStatic(document);   // index.html's own words in the page's language, and <html lang>, before anything is drawn
wireReferenceNav(document.querySelector(".ref-nav"));
wireLangSwitch(document);
main();
