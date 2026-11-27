/* global maplibregl */
// The new map, a preview (map.html) of the Area overview: MapLibre on OpenFreeMap's vector base maps (copies in
// vendor/openfreemap, so a change there cannot move our water over the names), Esri's satellite photo through our key
// (app/satellite.py), floating cards, and a place card for a shop or a section. A city split into sections is shaded at
// once and a section's squares and shops load when it is opened (one GET each, as the main page does); an area with no
// sections shows all its squares and shops at once. "Check a point" (map-gl-pin.js) drops a pin anywhere in Malaysia,
// and engineer mode (engineer.js, drawn by map-gl-eng.js) is the main page's panel over this map. Look adapted from Arus
// by Farhan Syah (MIT, vendor/LICENSE-arus.txt). The words are in strings/*-map.js.
import * as api from "./api.js";
import { h, s } from "./dom.js";
import { createEngineer } from "./engineer.js";
import { createMapChat } from "./map-gl-chat.js";
import { createAreaPanel } from "./map-gl-area.js";
import { createReferencePanel } from "./map-gl-reference.js";
import { PLACE_TABS, SHEET_TABS, createPlaceSheet } from "./map-gl-sheet.js";
import { applyStatic, lang, t } from "./i18n.js";
import { layersCard, pointCard, sectionCard, shopCard, summaryCard } from "./map-gl-card.js";
import { STYLE_FILES, depthRamp, readMapLink, sectionFill, sectionsGeo, shopColour, shopsGeo, squareOutline,
  squaresGeo, underRoads, wetShops, wetTotals, withMapView } from "./map-gl-data.js";
import { glDrawer } from "./map-gl-eng.js";
import { createMapLayers, metricPaint } from "./map-gl-layers.js";
import { wireSearch } from "./map-gl-search.js";
import { createPinMode } from "./map-gl-pin.js";
import { businessPlace, isWithinView, parseRef, writeUrl } from "./place.js";
import { pageArea } from "./start.js";
import { pointHeader } from "./point.js";

const $ = (id) => document.getElementById(id);
const PHONE = window.matchMedia("(max-width: 700px)");
const motionAllowed = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const EMPTY = { type: "FeatureCollection", features: [] };
const FLY_MS = 900;
const SHOP_ZOOM = 16;
const HIT_PX = 6;   // a tap this close to a shop's dot picks the shop
const FIT_PAD = { top: 120, bottom: 60, left: 380, right: 280 };   // the cards over the map's edges (map-preview/map-gl.css)
const PHONE_PAD = { top: 80, bottom: 120, left: 20, right: 20 };
const NO_PAD = { top: 0, bottom: 0, left: 0, right: 0 };
const TILT = { pitch: 55, bearing: -18 };
const PIN_COLOUR = "#e11d48";
const SECTION_OPACITY = ["interpolate", ["linear"], ["zoom"], 12, 0.42, 16, 0.1];   // the river model's shading fades as you zoom in

const st = {
  link: readMapLink(window.location.search, window.location.hash),
  area: null, sections: [], index: [], shelters: [], satellite: null, styles: {},
  shops: new Map(), cells: new Map(), cellDeg: 0, loaded: new Set(), picked: null, section: null, card: null, want: null,
  visible: { sections: true, squares: true, shops: true, shelters: true }, markers: [], map: null, returnFocus: null, layers: null, pictures: null,
  point: null, pinMarker: null, pin: null, eng: null, canPin: false, isReady: false, resume: null, cardTurn: 0,
  status: null, pages: new Map(), sheet: null, chat: null, areasList: null,
};
st.rp = st.link.rp;
st.base = st.link.base;
st.tilt = st.link.tilt;

const isDark = () => st.base !== "map";
const duration = () => (motionAllowed() ? FLY_MS : 0);
const langParam = (code = lang) => (code === "en" ? null : code);
/** The old interface on the view on show. ui=old keeps the front door from sending it back here, also in a new tab or
 *  with storage blocked; front-door.js remembers the choice. */
function mainLink(extra) {
  const url = new URL(writeUrl({ area: st.area?.id, section: st.section, rp: st.rp, lang: langParam(), ...extra }), window.location.href);
  url.searchParams.set("ui", "old");
  return `./${url.search}${url.hash}`;
}
const hint = () => t(st.sections.length ? "mg.hint" : "mg.hintShops");
const sectionName = (id) => st.sections.find((section) => section.id === id)?.name ?? "";

/** The words at the foot of the map; a problem also shows on phones, where the strip is otherwise hidden. */
function say(words, isProblem = false) {
  $("mg-hint").textContent = words;
  $("mg-hint").closest(".mg-status").classList.toggle("mg-alert", isProblem);
}

/* ---- the base maps ---- */

async function baseStyle(base) {
  if (base === "sat") return satelliteStyle();
  st.styles[base] ??= await fetch(STYLE_FILES[base]).then((r) => {
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  });
  return st.styles[base];
}

function satelliteStyle() {
  const photo = { type: "raster", tiles: [st.satellite.tiles], tileSize: 256, maxzoom: 19, attribution: st.satellite.attribution };
  return { version: 8, sources: { photo }, layers: [{ id: "photo", type: "raster", source: "photo" }] };
}

/** The satellite tiles the server hands out ({tiles, attribution}), or null without an imagery key: then no switch. */
async function satelliteTiles() {
  try {
    const response = await fetch("/api/satellite");
    const found = response.ok ? (await response.json()).data?.satellite : null;
    return typeof found?.tiles === "string" && typeof found.attribution === "string" ? found : null;
  } catch {
    return null;
  }
}

/** The cards follow the base map: light over the street map, dark over the dark map and the photo. */
function applyTheme() {
  document.documentElement.dataset.theme = isDark() ? "dark" : "light";
  document.querySelectorAll("[data-base]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.base === st.base)));
}

/* ---- our layers: sections, squares, shops ---- */

const squaresData = () => (st.cellDeg ? squaresGeo([...st.cells.values()], st.cellDeg) : EMPTY);
const shopsData = () => shopsGeo([...st.shops.values()]);

function addOurLayers(map) {
  if (!st.area || map.getSource("mg-sections")) return;
  map.addSource("mg-sections", { type: "geojson", data: sectionsGeo(st.sections) });
  map.addSource("mg-squares", { type: "geojson", data: squaresData() });
  map.addSource("mg-shops", { type: "geojson", data: shopsData() });
  const before = underRoads(map.getStyle().layers);
  const fade = (from, to) => ["interpolate", ["linear"], ["zoom"], 12, from, 16, to];
  map.addLayer({ id: "mg-section-fill", type: "fill", source: "mg-sections", paint: { "fill-color": sectionFill(st.rp), "fill-opacity": SECTION_OPACITY } }, before);
  map.addLayer({ id: "mg-squares", type: "fill", source: "mg-squares", paint: { "fill-color": depthRamp(st.rp, isDark()), "fill-opacity": fade(0.85, 0.5) } }, before);
  map.addLayer({ id: "mg-section-line", type: "line", source: "mg-sections",
    paint: { "line-color": isDark() ? "#46d3ff" : "#1e40af", "line-opacity": 0.55, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 0.6, 15, 1.6] } });
  map.addLayer({ id: "mg-section-hit", type: "fill", source: "mg-sections", paint: { "fill-color": "#000", "fill-opacity": 0 } });
  map.addLayer({ id: "mg-shops", type: "circle", source: "mg-shops", paint: { "circle-color": shopColour(st.rp),
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 14, 5, 17, 9], "circle-opacity": 0.95,
    "circle-stroke-color": isDark() ? "#0b1520" : "#ffffff", "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 11, 0.8, 15, 2] } });
  map.addLayer({ id: "mg-picked", type: "circle", source: "mg-shops", filter: ["==", ["get", "id"], st.picked ?? ""],
    paint: { "circle-radius": 13, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#ffb14a", "circle-stroke-width": 3 } });
  addPointLayers(map, before);
  if (st.tilt) addBuildings(map);
  showLayers(map);
  st.eng?.redraw(map);
  st.pictures?.redraw(map);   // the flash flood and low ground pictures
  paintSections(map);
}

/** A checked point's square outlined, and the squares that came with it where the area has none of its own. */
function addPointLayers(map, before) {
  map.addSource("mg-point-squares", { type: "geojson", data: pointSquaresData() });
  map.addSource("mg-point-square", { type: "geojson", data: st.point ? squareOutline(st.point.place.cell.bounds) : EMPTY });
  map.addLayer({ id: "mg-point-squares", type: "fill", source: "mg-point-squares",
    paint: { "fill-color": depthRamp(st.rp, isDark()), "fill-opacity": 0.6 } }, before);
  map.addLayer({ id: "mg-point-square", type: "line", source: "mg-point-square", paint: { "line-color": PIN_COLOUR, "line-width": 2.5 } });
}

/** Buildings standing up, for the tilted view, where the base map has them (not on the satellite photo). */
function addBuildings(map) {
  if (map.getLayer("mg-buildings") || !map.getSource("openmaptiles")) return;
  map.addLayer({ id: "mg-buildings", type: "fill-extrusion", source: "openmaptiles", "source-layer": "building", minzoom: 14,
    paint: { "fill-extrusion-color": isDark() ? "#1f2f3f" : "#dfe4ea", "fill-extrusion-opacity": 0.85,
      "fill-extrusion-height": ["coalesce", ["get", "render_height"], 6], "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0] } },
  "mg-section-line");
}

function showLayers(map) {
  const show = (id, on) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  show("mg-section-fill", st.visible.sections);
  show("mg-section-line", st.visible.sections);
  show("mg-squares", st.visible.squares);
  show("mg-shops", st.visible.shops);
  show("mg-picked", st.visible.shops);
  st.markers.forEach((marker) => { marker.getElement().hidden = !st.visible.shelters; });
}

function paintFloodSize(map) {
  if (!map?.getLayer("mg-squares")) return;
  map.setPaintProperty("mg-squares", "fill-color", depthRamp(st.rp, isDark()));
  map.setPaintProperty("mg-point-squares", "fill-color", depthRamp(st.rp, isDark()));
  map.setPaintProperty("mg-shops", "circle-color", shopColour(st.rp));
  paintSections(map);
}

/** The sections' shading: the river model's share of wet squares at the flood size on show, or what the layers card
 *  chose instead (map-gl-layers.js: flash flood potential, or our score). */
function paintSections(map = st.map) {
  if (!map?.getLayer("mg-section-fill")) return;
  const metric = st.layers?.metric() ?? "depth";
  const paint = metric === "depth" ? { color: sectionFill(st.rp), opacity: SECTION_OPACITY } : metricPaint(st.sections, metric);
  map.setPaintProperty("mg-section-fill", "fill-color", paint.color);
  map.setPaintProperty("mg-section-fill", "fill-opacity", paint.opacity);
}

const markPicked = (id) => st.map?.getLayer("mg-picked") && st.map.setFilter("mg-picked", ["==", ["get", "id"], id ?? ""]);

/* ---- squares and shops: a section's, or a whole area's ---- */

function keep({ cells = [], premises = [], cellDeg }) {
  if (cellDeg) st.cellDeg = cellDeg;
  cells.forEach((cell) => st.cells.set(`${cell[0]},${cell[1]}`, cell));
  premises.forEach((premise) => st.shops.set(premise.id, premise));
  st.map?.getSource("mg-squares")?.setData(squaresData());
  st.map?.getSource("mg-shops")?.setData(shopsData());
}

async function loadSection(sectionId) {
  if (st.loaded.has(sectionId)) return;
  say(t("mg.sectionLoading", { name: sectionName(sectionId) || sectionId }));
  const data = await api.getSectionData(st.area.id, sectionId);
  st.loaded.add(sectionId);
  st.pages.set(sectionId, pageArea(data.area, data.section));   // My business needs the section's record and example
  keep({ cells: data.town.cells, premises: data.premises, cellDeg: data.town.cell_deg });
  if (st.sheet?.isOpen() && !PLACE_TABS.includes(st.sheet.tab())) st.sheet.refresh();   // the Area overview, on this section, has its businesses now
  say(hint());
}

function fitSection(sectionId) {
  const bbox = st.sections.find((section) => section.id === sectionId)?.bbox;
  if (bbox) st.map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: PHONE.matches ? PHONE_PAD : FIT_PAD, duration: duration(), maxZoom: 16 });
}

/* ---- the place card ---- */

function showCard(nodes, { focus = true } = {}) {
  const card = $("mg-place");
  st.cardTurn += 1;
  if (card.hidden && !card.contains(document.activeElement)) st.returnFocus = document.activeElement;
  card.replaceChildren(...nodes);
  card.setAttribute("aria-live", "polite");
  card.hidden = false;
  if (focus) card.querySelector("h2")?.focus({ preventScroll: true });
}

function closeCard() {
  const wasOpen = !$("mg-place").hidden;
  closePlaceTab();   // the place's tabs are the card's: they go with it
  st.chat?.render(null);
  st.cardTurn += 1;
  st.pin?.stop();
  clearPoint();
  st.picked = null;
  st.card = null;
  $("mg-place").hidden = true;
  markPicked(null);
  writeLink();
  say(hint());
  if (!wasOpen) return;
  if (PHONE.matches) st.map?.easeTo({ padding: NO_PAD, duration: duration() });
  const back = st.returnFocus?.isConnected && st.returnFocus !== document.body ? st.returnFocus : st.map?.getCanvas();
  back?.focus({ preventScroll: true });
}

function shopLinks(shop) {
  const at = { section: shop.section, place: shop.id };
  return {
    details: `map.html${mapQuery({ ...at, tab: "business" })}`, onDetails: () => openSheet("business"),
    cost: `map.html${mapQuery({ ...at, tab: "cost" })}`, onCost: () => openSheet("cost"),
    see3d: st.area.has_3d && shop.has_3d !== false ? `3d.html${writeUrl({ area: st.area.id, ...at, rp: st.rp })}` : null,
    directions: `https://www.google.com/maps/dir/?api=1&destination=${shop.lat},${shop.lon}`,
  };
}

async function share() {
  const url = window.location.href;
  if (navigator.share) return navigator.share({ url }).catch(() => {});
  await navigator.clipboard?.writeText(url).then(() => say(t("mg.shared")), () => {});
}

function showShop(shop, { fly = false, focus = true, move = true } = {}) {
  st.pin?.stop();
  clearPoint();
  st.picked = shop.id;
  st.card = { kind: "shop", id: shop.id };
  st.section = shop.section ?? st.section;
  markPicked(shop.id);
  showCard(shopCard(shop, { rp: st.rp, sectionName: sectionName(shop.section), shelters: st.shelters, links: shopLinks(shop),
    onClose: closeCard, onShare: share }), { focus });
  followCard();
  st.chat?.render(cardPlace());
  writeLink();
  say(shop.name);
  if (!move) return;
  // on a phone the card is a sheet over the map's lower part, so the shop goes in the part still showing
  const padding = PHONE.matches ? { ...NO_PAD, bottom: $("mg-place").offsetHeight } : undefined;
  if (fly) st.map.flyTo({ center: [shop.lon, shop.lat], zoom: Math.max(st.map.getZoom(), SHOP_ZOOM), ...(padding && { padding }), duration: duration() });
  else if (padding) st.map.easeTo({ center: [shop.lon, shop.lat], zoom: Math.max(st.map.getZoom(), SHOP_ZOOM - 1), padding, duration: duration() });
}

function showSection(sectionId, { focus = true } = {}) {
  const props = sectionsGeo(st.sections).features.find((f) => f.properties.id === sectionId)?.properties;
  if (!props) return;
  st.pin?.stop();
  clearPoint();
  closePlaceTab();   // a section has no business card; the Area overview and Reference follow it
  st.sheet?.refresh();
  st.chat?.render(null);   // and the chat is about the area again
  st.card = { kind: "section", id: sectionId };
  showCard(sectionCard(props, { rp: st.rp, onOpen: () => openSheet("overview"), onClose: closeCard }), { focus });
}

/* ---- a checked point ---- */

function pointSquaresData() {
  const { place, squares } = st.point ?? {};
  if (!place || !squares?.cells?.length || isWithinView(place.lat, place.lon, st.area.view)) return EMPTY;   // the area's own
  const [west, south, east, north] = place.cell.bounds;
  return squaresGeo(squares.cells, east - west, north - south);
}

/** The pin, its square and the squares that came with it, for the point on show (none when st.point is null). */
function drawPoint() {
  const place = st.point?.place;
  st.pinMarker?.remove();
  st.pinMarker = place ? new maplibregl.Marker({ color: PIN_COLOUR }).setLngLat([place.lon, place.lat]).addTo(st.map) : null;
  st.map?.getSource("mg-point-square")?.setData(place ? squareOutline(place.cell.bounds) : EMPTY);
  st.map?.getSource("mg-point-squares")?.setData(pointSquaresData());
}

function clearPoint() {
  if (!st.point) return;
  st.point = null;
  drawPoint();
}

function pointLinks(place) {
  const at = { section: place.section?.id ?? null, place: place.id };   // writeUrl puts a point in the fragment, never the query
  return { details: `map.html${mapQuery({ ...at, tab: "business" })}`, onDetails: () => openSheet("business"),
    cost: `map.html${mapQuery({ ...at, tab: "cost" })}`, onCost: () => openSheet("cost"),
    directions: `https://www.google.com/maps/dir/?api=1&destination=${place.lat},${place.lon}` };
}

/** A point the server has checked: its pin and card. Its section's squares and shops load, as when a shop is opened. */
function showPoint(place, squares, { focus = true, move = true } = {}) {
  st.point = { place, squares };
  st.picked = place.id;
  st.card = { kind: "point" };
  markPicked(null);
  drawPoint();
  const { title, subline } = pointHeader(place, st.area, null);
  const sectionId = place.section?.id;
  if (sectionId && st.sections.some((section) => section.id === sectionId)) {
    st.section = sectionId;
    loadSection(sectionId).then(() => {
      if (st.point?.place !== place) return;
      say(title);
      if (st.sheet?.isOpen() && PLACE_TABS.includes(st.sheet.tab())) openSheet();   // the section's own record and example, now in
    }, (error) => say(t("mg.failed", { why: error.message }), true));
  }
  showCard(pointCard(place, { rp: st.rp, title, subline, links: pointLinks(place), onClose: closeCard, onShare: share,
    onMove: () => startPin({ at: place }) }), { focus });
  followCard();
  st.chat?.render(place);
  writeLink();
  say(title);
  if (!move) return;
  const padding = PHONE.matches ? { padding: { ...NO_PAD, bottom: $("mg-place").offsetHeight } } : {};   // easeTo throws on padding: undefined
  const go = () => st.map.easeTo({ center: [place.lon, place.lat], zoom: Math.max(st.map.getZoom(), SHOP_ZOOM), ...padding, duration: duration() });
  if (st.isReady) go();
  else st.map.once("load", go);   // a linked point: a move before the first load is lost to the map's opening view
}

/** Pin mode, from the pin button or a point's "Move the pin": any card goes, and the aim panel takes its place. */
function startPin(options = {}) {
  if (st.pin.isOn()) return st.map.getCanvas().focus({ preventScroll: true });   // already aiming: keep what Cancel brings back
  st.sheet?.close();   // the aim panel takes the place card, which a sheet would cover
  const resume = st.point;   // kept for Cancel, which shows it again
  closeCard();
  st.resume = resume;
  return st.pin.start(options);
}

/** Pin mode's Cancel or Escape: the point that was on show before, if any, comes back. */
function endPin() {
  const back = st.resume;
  st.resume = null;
  closeCard();
  if (back) showPoint(back.place, back.squares, { move: false });
}

function onPinned(place, squares) {
  st.resume = null;
  showPoint(place, squares);
}

/** The aim panel in the place card; on a phone the map's centre, and so the cross, moves up clear of that sheet. The
 *  card is not a live region meanwhile: the panel has its own status and alert, which would otherwise be read twice. */
function showAim(node) {
  showCard([h("div", { class: "mg-handle", "aria-hidden": "true" }), node], { focus: false });
  $("mg-place").setAttribute("aria-live", "off");
  if (PHONE.matches) st.map.easeTo({ padding: { ...NO_PAD, bottom: $("mg-place").offsetHeight }, duration: duration() });
}

/** The map's cursor: a crosshair while the pin or an engineer tool has the clicks, else a hand over a shop. */
function syncCursor(isOverShop = false) {
  const canvas = st.map?.getCanvas();
  if (!canvas) return;
  if (st.pin?.isOn() || st.eng?.isToolOn()) canvas.style.cursor = "crosshair";
  else canvas.style.cursor = isOverShop ? "pointer" : "";
}

async function openSection(sectionId, { fit = true } = {}) {
  st.section = sectionId;
  st.picked = null;
  markPicked(null);
  showSection(sectionId);
  if (fit) fitSection(sectionId);
  writeLink();
  await loadSection(sectionId).catch((error) => say(t("mg.failed", { why: error.message }), true));
}

/** A shop picked in the search: its section loads first; a later pick or click wins over a slow load. */
async function openShop(entry) {
  st.want = entry.id;
  const openTab = st.sheet?.isOpen() ? st.sheet.tab() : null;   // opening its section closes a place tab: a search made in it opens it again
  if (openTab && !PLACE_TABS.includes(openTab)) st.sheet.close();   // an area tab goes first, so the section asks Weather for nothing
  if (entry.section && st.sections.some((section) => section.id === entry.section)) await openSection(entry.section, { fit: false });
  const shop = st.shops.get(entry.id);
  if (!shop || st.want !== entry.id) return;
  showShop(shop, { fly: true });
  if (PLACE_TABS.includes(openTab)) openSheet(openTab);
}

/* ---- this page's link, and the links that carry it ---- */

/** The query for what is on show: the main page's fields, then the base map and the tilt. */
const sheetTab = () => (st.sheet?.isOpen() ? st.sheet.tab() : null);
const mapQuery = (extra = {}) => withMapView(writeUrl({ area: st.area?.id, section: st.section, tab: sheetTab(), place: st.picked,
  rp: st.rp, lang: langParam(), ...extra }), st.base, st.tilt);

/** This page's own address for what is on show, so a shared link opens the same view; the language, home and tab
 *  links follow it. */
function writeLink() {
  window.history.replaceState(null, "", `map.html${mapQuery()}`);
  drawLinks();
}

function drawLinks() {
  if (!st.area) return;
  const langLink = (code, label) => h("a", { href: `map.html${mapQuery({ lang: code })}`, "aria-current": code === lang ? "true" : null }, label);
  $("mg-lang").replaceChildren(langLink("ms", "BM"), langLink("en", "EN"));
  $("mg-home").href = `map.html${writeUrl({ area: st.area.id, lang: langParam() })}`;   // this map's home: the whole area
  document.querySelectorAll("#mg-old, .mg-old-link").forEach((link) => { link.href = mainLink({ place: st.picked }); });
  // every tab opens in the sheet over this map; the Area overview chip stands for the map itself while none is open
  const onMap = Object.fromEntries(SHEET_TABS.map((key) => [key, () => openSheet(key)]));
  const href = (key) => `map.html${mapQuery({ tab: key })}`;
  const tab = (key) => h("a", { href: href(key), "aria-current": key === (sheetTab() ?? "overview") ? "page" : null,
    onclick: onMap[key] && plainClick(onMap[key]) }, t(`tab.${key}`));
  $("mg-tabs").replaceChildren(...["overview", "business", "cost", "insurance", "reference"].map(tab));
}

/** A click handler that keeps a link's own job (a new tab, a download) for a click with a key held or another button. */
const plainClick = (act) => (event) => {
  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  act();
};

/* ---- the place's tabs, a sheet over the map (map-gl-sheet.js) ---- */

const sectionIdOf = (place) => (typeof place?.section === "string" ? place.section : place?.section?.id ?? null);
/** The page a place is on, as the old interface makes it (start.js pageArea): its section's once loaded, else the area. */
const pageOf = (place) => st.pages.get(sectionIdOf(place)) ?? st.area;

/** The place on the card: a shop in the Place shape (place.js businessPlace), a checked point, or none. */
function cardPlace() {
  if (st.card?.kind === "point") return st.point?.place ?? null;
  const shop = st.card?.kind === "shop" && st.shops.get(st.card.id);
  return shop ? businessPlace(shop, st.area.id) : null;
}

/** A shop or point now on the card: a place tab shows it; an area tab steps aside, so the card it would cover shows. */
function followCard() {
  if (!st.sheet?.isOpen()) return;
  if (PLACE_TABS.includes(st.sheet.tab())) openSheet();
  else st.sheet.close();
}

/** Closes the sheet when it shows one of the place's tabs (the card has changed or gone). */
function closePlaceTab() {
  if (st.sheet?.isOpen() && PLACE_TABS.includes(st.sheet.tab())) st.sheet.close();
}

/** What the Area overview and Reference are about: the section on show once loaded, else the whole area. */
function areaScope() {
  const sectionId = st.section && st.loaded.has(st.section) ? st.section : null;
  const shops = [...st.shops.values()];
  return { areaId: st.area.id, sectionId, page: (sectionId && st.pages.get(sectionId)) || st.area, sections: st.sections,
    word: st.area.section_word ?? null,
    premises: sectionId ? shops.filter((shop) => shop.section === sectionId) : st.sections.length ? st.index : shops };
}

/** Opens the sheet on `tab` (the one on show, when it is open) for the card's place. */
function openSheet(tab = st.sheet.isOpen() ? st.sheet.tab() : "business", place = cardPlace(), options = {}) {
  st.sheet.open(tab, place, pageOf(place), st.rp, options);
}

/** A place in Compare places: on this map (its section loads first; the sheet, open, follows it), or another area's. */
function openCompared(place) {
  const { areaId, sectionId } = place.page ?? {};
  if (areaId && areaId !== st.area.id) {
    const tab = place.is_point ? null : "business";   // no tab with a point, as place.js pageLink
    window.location.assign(`map.html${withMapView(writeUrl({ area: areaId, section: sectionId, tab, place: place.id, rp: st.rp, lang: langParam() }), st.base, st.tilt)}`);
  } else if (place.is_point) showPoint(place, null);
  else openShop({ id: place.id, section: sectionId ?? sectionIdOf(place) });
}

/** The sheet opened or closed: the link follows it, and focus that was in a closed sheet goes back to the card. */
function onSheetChanged() {
  writeLink();
  const isOpen = st.sheet.isOpen();
  // what the sheet covers is out of reach by keyboard and screen reader: the cards beside the map, and on a phone, where
  // the sheet fills the screen, the bar, the tabs, the tools and the map too
  for (const selector of [".mg-side", ".mg-top", ".mg-tabs", ".mg-right", "#mg-map"]) {
    document.querySelector(selector).inert = isOpen && (selector === ".mg-side" || PHONE.matches);
  }
  if (isOpen || !(document.activeElement === document.body || $("mg-sheet").contains(document.activeElement))) return;
  ($("mg-place").hidden ? st.map.getCanvas() : $("mg-place").querySelector("h2"))?.focus({ preventScroll: true });
}

/** The sheet, and the chat it and the cards ask: both built once the area's data and the status are in. */
function wireSheet() {
  PHONE.addEventListener("change", () => st.sheet.isOpen() && onSheetChanged());   // a turn or a resize: what it covers changes
  st.areasList = api.getAreas().then((list) => list.areas ?? []).catch(() => []);
  st.areasList.then((areas) => {
    st.chat = createMapChat({ area: st.area, areas, status: st.status, getPlaceRef: () => cardPlace()?.id ?? null });
    st.chat.render(cardPlace());
    if (st.link.chat) st.chat.open();   // the old Ask AI tab's link (?tab=ask): the chat over the map
  });
  st.sheet = createPlaceSheet({
    sheet: $("mg-sheet"), back: $("mg-sheet-back"), label: $("mg-sheet-label"), status: st.status, areas: () => st.areasList,
    panels: Object.fromEntries(SHEET_TABS.map((tab) => [tab, $(tab === "overview" ? "panel-area" : `panel-${tab}`)])),
    about: {
      overview: createAreaPanel({ panel: $("panel-area"), scope: areaScope, status: st.status, areas: () => st.areasList, on: {
        section: (id) => { st.sheet.close(); openSection(id); },
        wholeArea: () => { closeCard(); st.section = null; writeLink(); st.sheet.refresh(); },
        sectionHref: (id) => `map.html${mapQuery({ section: id, place: null, tab: null })}`,
        areaHref: (id) => `map.html${withMapView(writeUrl({ area: id, tab: "overview", lang: langParam() }), st.base, st.tilt)}`,
        pickRp: pickFloodSize,
        // a business from the list: its section loads first (the index knows it), the sheet steps aside for its card
        openShop: (id) => { st.sheet.close(); openShop(st.index.find((entry) => entry.id === id) ?? { id, section: st.shops.get(id)?.section }); },
        redraw: () => st.sheet.refresh(),
      } }),
      reference: createReferencePanel({ panel: $("panel-reference"), scope: areaScope }),
    },
    on: {
      pickRp: pickFloodSize,
      showOnMap: (place) => st.map.flyTo({ center: [place.lon, place.lat], zoom: Math.max(st.map.getZoom(), SHOP_ZOOM), duration: duration() }),
      movePin: (place) => startPin({ at: place }),
      goto: (tab, place) => window.location.assign(mainLink({ place: place?.id ?? null, section: sectionIdOf(place), tab })),
      ask: (opener) => st.chat?.open(opener),
      openCompared,
      // no tab, as place.js pageLink: the query of a move that carries a point is the same as any other move's
      openArea: (areaId, place) => window.location.assign(`map.html${withMapView(writeUrl({ area: areaId, place: place.id, rp: st.rp, lang: langParam() }), st.base, st.tilt)}`),
      find: () => $("mg-q").focus(),
      checkPoint: st.canPin ? () => startPin() : null,
      changed: onSheetChanged,
    },
  });
  $("mg-sheet-back").textContent = t("mg.backToMap");
}

/* ---- the bar, the cards and their controls ---- */

function drawSummary() {
  const wet = st.sections.length ? wetTotals(st.sections, st.rp).wet : wetShops([...st.shops.values()], st.rp);
  const all = st.area.counts?.businesses ?? st.shops.size;
  $("mg-summary").replaceChildren(...summaryCard({ wet, all, rp: st.rp, onPick: pickFloodSize,
    oldHref: mainLink({ place: st.picked }) }));
}

function pickFloodSize(rp) {
  const hadFocus = $("mg-summary").contains(document.activeElement);
  st.rp = rp;
  st.sheet?.setRp(rp);
  paintFloodSize(st.map);
  drawSummary();
  if (hadFocus) $("mg-summary").querySelector(`[data-rp="${rp}"]`)?.focus();
  const shop = st.card?.kind === "shop" && st.shops.get(st.card.id);
  if (shop) showShop(shop, { focus: false, move: false });
  else if (st.card?.kind === "section") showSection(st.card.id, { focus: false });
  else if (st.card?.kind === "point" && st.point) showPoint(st.point.place, st.point.squares, { focus: false, move: false });
  writeLink();
}

function drawLayers() {
  st.pictures ??= glDrawer({ getMap: () => st.map, hasOurLayers: (map) => Boolean(map.getSource("mg-sections")), prefix: "mg-layer",
    beforeId: (map, key) => (key === "low" && map.getLayer("mg-layer-flash") ? "mg-layer-flash" : "mg-section-fill"),   // low ground under flash
    onError: (key) => st.layers?.failed(key) });
  st.layers ??= createMapLayers({ area: st.area, sections: st.sections, drawer: st.pictures, onMetric: () => {
    if (!st.visible.sections) $("mg-layers").querySelector('input[value="sections"]')?.click();   // a shading shows on the sections
    paintSections();
  } });
  $("mg-layers").replaceChildren(...layersCard(st.visible, (key, on) => {
    st.visible[key] = on;
    showLayers(st.map);
  }), ...st.layers.nodes);
}

/** Another base map: the style is fetched first, and a later pick wins; on a failure the old map and its look stay. */
async function pickBase(base) {
  if (base === st.base) return;
  const before = st.base;
  st.base = base;
  applyTheme();
  try {
    const style = await baseStyle(base);
    if (st.base !== base) return;
    st.map.setStyle(style, { diff: false });   // a diffed swap fires no style.load, so ours would not come back
    writeLink();
  } catch (error) {
    if (st.base !== base) return;
    st.base = before;
    applyTheme();
    say(t("mg.failed", { why: error.message }), true);
  }
}

function toggleTilt() {
  st.tilt = !st.tilt;
  $("mg-tilt").setAttribute("aria-pressed", String(st.tilt));
  if (st.tilt) addBuildings(st.map);
  else if (st.map.getLayer("mg-buildings")) st.map.removeLayer("mg-buildings");
  st.map.easeTo({ ...(st.tilt ? TILT : { pitch: 0, bearing: 0 }), duration: duration() });
  writeLink();
}

function drawBar() {
  const base = (key) => h("button", { type: "button", "data-base": key, "aria-pressed": String(key === st.base), onclick: () => pickBase(key) }, t(`mg.base.${key}`));
  $("mg-bases").replaceChildren(...["map", ...(st.satellite ? ["sat"] : []), "dark"].map(base));
  Object.assign($("mg-tilt"), { textContent: t("mg.tilt"), title: t("mg.tiltLabel"), onclick: toggleTilt });
  $("mg-tilt").setAttribute("aria-pressed", String(st.tilt));
  $("mg-area").textContent = st.area.display_name ?? st.area.name;
  $("mg-home").setAttribute("aria-label", t("mg.back"));
  $("mg-q").placeholder = t("mg.search");
  $("mg-q").setAttribute("aria-label", t("mg.searchLabel"));
  Object.assign($("mg-old"), { textContent: t("mg.oldUi"), title: t("mg.oldUiNote") });
  $("mg-bases").setAttribute("aria-label", t("mg.base.label"));
  $("mg-lang").setAttribute("aria-label", t("mg.lang"));
  $("mg-tabs").setAttribute("aria-label", t("mg.tabsLabel"));
  $("mg-status").textContent = t("mg.status");
  drawLinks();
}


function addShelters(map) {
  st.markers = st.shelters.map((shelter) => {
    const words = `${t("mg.shelterTitle")}: ${shelter.name}`;
    const mark = h("div", { class: "mg-shelter", title: words, role: "img", "aria-label": words },
      s("svg", { width: "18", height: "16", viewBox: "0 0 18 16", "aria-hidden": "true" },
        s("path", { d: "M9 1 17 15H1z", fill: "#16a34a", stroke: "#fff", "stroke-width": "1.6", "stroke-linejoin": "round" })));
    return new maplibregl.Marker({ element: mark }).setLngLat([shelter.lon, shelter.lat]).addTo(map);
  });
}

/* ---- the map ---- */

function onMapClick(event) {
  const map = st.map;
  $("mg-results").hidden = true;
  st.want = null;
  if (st.pin?.isOn()) return st.pin.tap(event.lngLat);
  if (st.eng?.click(event.lngLat)) return undefined;
  const { x, y } = event.point;
  const shop = map.queryRenderedFeatures([[x - HIT_PX, y - HIT_PX], [x + HIT_PX, y + HIT_PX]], { layers: ["mg-shops"] })[0];
  const found = shop && st.shops.get(shop.properties.id);
  if (found) return showShop(found);
  const section = map.queryRenderedFeatures(event.point, { layers: ["mg-section-hit"] })[0];
  if (section) return openSection(section.properties.id, { fit: section.properties.id !== st.section });
  return closeCard();
}

function openMap(style) {
  const [west, south, east, north] = st.area.view;
  const map = new maplibregl.Map({
    container: "mg-map", style, bounds: [[west, south], [east, north]], fitBoundsOptions: { padding: PHONE.matches ? PHONE_PAD : FIT_PAD },
    maxPitch: 65, cooperativeGestures: PHONE.matches, attributionControl: { compact: true, customAttribution: t("mg.credit") },
    locale: { "CooperativeGesturesHandler.MobileHelpText": t("map.twoFingers") },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
  map.on("style.load", () => addOurLayers(map));
  map.once("load", () => { st.isReady = true; });
  map.on("click", onMapClick);
  map.on("mouseenter", "mg-shops", () => syncCursor(true));
  map.on("mouseleave", "mg-shops", () => syncCursor(false));
  if (st.tilt) map.once("load", () => map.easeTo({ ...TILT, duration: 0 }));
  return map;
}

/** The pin and engineer mode: their buttons, and engineer mode's panel in the right column (a sheet on a phone). */
function wireTools() {
  st.pin = createPinMode({ map: () => st.map, cross: $("mg-cross"), show: showAim, hide: endPin, onPlace: onPinned, onModeChange: () => syncCursor() });
  const pinButton = $("mg-pin");
  pinButton.hidden = !st.canPin;
  pinButton.querySelector("span").textContent = t("pin.heading");
  pinButton.addEventListener("click", () => startPin());
  $("mg-eng-btn").querySelector("span").textContent = t("eng.switch");
  const layersButton = $("mg-layers-btn");   // phones: the layers card opens as a sheet (map-gl.css)
  layersButton.querySelector("span").textContent = t("mg.layers");
  layersButton.onclick = () => layersButton.setAttribute("aria-expanded", String(layersButton.getAttribute("aria-expanded") !== "true"));
  st.eng = glDrawer({ getMap: () => st.map, beforeId: (map) => underRoads(map.getStyle().layers) ?? "mg-section-line",
    hasOurLayers: (map) => Boolean(map.getSource("mg-sections")), isAiming: () => st.pin.isOn(), onToolChange: () => syncCursor() });
  createEngineer({ section: $("mg-eng"), button: $("mg-eng-btn"), area: st.area, drawer: st.eng });
  st.map.getCanvas().addEventListener("keydown", (event) => {
    if (event.key === "Enter" && st.pin.isOn()) st.pin.checkCentre();
  });
}

/** Escape: pin mode ends first, then the card closes; the location dialog has its own. */
function onKey(event) {
  if (event.key !== "Escape" || event.defaultPrevented || st.pin?.isAsking() || document.querySelector("dialog[open]")) return;
  if (st.pin?.isOn()) st.pin.cancel();
  else if (st.sheet?.isOpen()) st.sheet.close();
  else closeCard();
}

function showProblem(words) {
  $("mg-problem").replaceChildren(words, " ", h("a", { href: mainLink() }, t("mg.toMain")));
  $("mg-problem").hidden = false;
  say(words, true);
}

async function startFromLink() {
  const { section, place, tab } = st.link;
  if (parseRef(place)?.kind === "point") await openLinkedPoint(place);
  else {
    if (section && st.sections.some((known) => known.id === section)) await openSection(section);
    const entry = place && !st.shops.has(place) && st.index.find((known) => known.id === place);
    if (entry) await openShop(entry);   // a link with no section (an old one): the index has the shop's section
    else if (st.shops.get(place)) showShop(st.shops.get(place));
  }
  if (SHEET_TABS.includes(tab)) openSheet(tab, cardPlace(), { push: false });   // a link to the sheet opens it, with no step to go back to
}

/** A point the link names, checked again; a failure is said, and the map stays as it is. */
async function openLinkedPoint(ref) {
  if (!st.canPin) return say(t("mg.pointMissed"), true);
  say(t("mg.pointLoading"));
  const turn = st.cardTurn;
  const isStale = () => st.cardTurn !== turn || st.pin.isOn();   // the person has opened something else meanwhile
  try {
    const found = await st.pin.linked(ref);
    if (isStale()) return undefined;
    if (found) return showPoint(found.place, found.squares);
  } catch {
    if (isStale()) return undefined;
  }
  return say(t("mg.pointMissed"), true);
}

/** The area's data and its base map; false, with the problem shown, when either cannot be had. */
async function load() {
  try {
    const status = api.getStatus().catch(() => null);   // the pin needs the points' files (points_ready)
    const [data, satellite] = await Promise.all([st.link.area ? api.getAreaData(st.link.area) : api.getDefaultData(), satelliteTiles()]);
    Object.assign(st, { area: data.area, sections: data.sections ?? [], index: data.index ?? [], shelters: data.town?.shelters ?? [], satellite,
      status: await status });
    st.canPin = st.status?.points_ready === true;
    if (!st.sections.length) keep({ cells: data.town?.cells, premises: data.premises, cellDeg: data.town?.cell_deg });
    if (st.base === "sat" && !satellite) st.base = "map";
    return await baseStyle(st.base);
  } catch (error) {
    showProblem(t("mg.failed", { why: error.message }));
    return null;
  }
}

async function start() {
  document.title = t("mg.title");
  document.documentElement.lang = lang;
  $("mg-map").setAttribute("aria-label", t("mg.mapLabel"));
  say(t("mg.loading"));
  if (!window.maplibregl) return showProblem(t("mg.noWebgl"));
  maplibregl.setWorkerUrl("vendor/maplibre-gl-csp-worker.js");   // the CSP build runs its worker from our own file
  const style = await load();
  if (!style) return undefined;
  applyTheme();
  drawBar(); drawSummary(); drawLayers();
  wireSearch({ input: $("mg-q"), box: $("mg-results"), area: st.area, sections: st.sections, index: st.index, sectionName,
    onShop: openShop, onSection: (id) => { st.sheet?.close(); openSection(id); } });
  try {
    st.map = openMap(style);
  } catch {
    return showProblem(t("mg.noWebgl"));
  }
  addShelters(st.map);
  wireTools();
  applyStatic(document);   // the chat's own words in map.html (data-i18n), as the old page fills them
  wireSheet();
  document.addEventListener("keydown", onKey);
  say(hint());
  return startFromLink();
}

start();
