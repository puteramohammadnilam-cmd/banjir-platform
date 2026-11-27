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
import { lang, t } from "./i18n.js";
import { layersCard, pointCard, sectionCard, shopCard, summaryCard } from "./map-gl-card.js";
import { STYLE_FILES, depthRamp, readMapLink, searchIndex, sectionFill, sectionsGeo, shopColour, shopsGeo, squareOutline,
  squaresGeo, underRoads, wetShops, wetTotals, withMapView } from "./map-gl-data.js";
import { glDrawer } from "./map-gl-eng.js";
import { createPinMode } from "./map-gl-pin.js";
import { rememberUi } from "./ui-choice.js";
import { isWithinView, parseRef, writeUrl } from "./place.js";
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

const st = {
  link: readMapLink(window.location.search, window.location.hash),
  area: null, sections: [], index: [], shelters: [], satellite: null, styles: {},
  shops: new Map(), cells: new Map(), cellDeg: 0, loaded: new Set(), picked: null, section: null, card: null, want: null,
  visible: { sections: true, squares: true, shops: true, shelters: true }, markers: [], map: null, returnFocus: null,
  point: null, pinMarker: null, pin: null, eng: null, canPin: false, isReady: false, resume: null, cardTurn: 0,
};
st.rp = st.link.rp;
st.base = st.link.base;
st.tilt = st.link.tilt;

const isDark = () => st.base !== "map";
const duration = () => (motionAllowed() ? FLY_MS : 0);
const langParam = (code = lang) => (code === "en" ? null : code);
const mainLink = (extra) => `./${writeUrl({ area: st.area?.id, section: st.section, rp: st.rp, lang: langParam(), ...extra })}`;
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
  map.addLayer({ id: "mg-section-fill", type: "fill", source: "mg-sections", paint: { "fill-color": sectionFill(st.rp), "fill-opacity": fade(0.42, 0.1) } }, before);
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
  map.setPaintProperty("mg-section-fill", "fill-color", sectionFill(st.rp));
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
  keep({ cells: data.town.cells, premises: data.premises, cellDeg: data.town.cell_deg });
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
    details: mainLink({ ...at, tab: "business" }), cost: mainLink({ ...at, tab: "cost" }),
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
  st.card = { kind: "section", id: sectionId };
  showCard(sectionCard(props, { rp: st.rp, link: mainLink({ section: sectionId }), onClose: closeCard }), { focus });
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
  return { details: mainLink({ ...at, tab: "business" }), cost: mainLink({ ...at, tab: "cost" }),
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
    loadSection(sectionId).then(() => st.point?.place === place && say(title), (error) => say(t("mg.failed", { why: error.message }), true));
  }
  showCard(pointCard(place, { rp: st.rp, title, subline, links: pointLinks(place), onClose: closeCard, onShare: share,
    onMove: () => startPin({ at: place }) }), { focus });
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
  if (entry.section && st.sections.some((section) => section.id === entry.section)) await openSection(entry.section, { fit: false });
  const shop = st.shops.get(entry.id);
  if (shop && st.want === entry.id) showShop(shop, { fly: true });
}

/* ---- this page's link, and the links that carry it ---- */

/** The query for what is on show: the main page's fields, then the base map and the tilt. */
const mapQuery = (extra = {}) =>
  withMapView(writeUrl({ area: st.area?.id, section: st.section, place: st.picked, rp: st.rp, lang: langParam(), ...extra }), st.base, st.tilt);

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
  $("mg-old").href = mainLink({ place: st.picked });
  const tab = (key) => h("a", { href: mainLink({ place: st.picked, tab: key === "overview" ? null : key }), "aria-current": key === "overview" ? "page" : null }, t(`tab.${key}`));
  $("mg-tabs").replaceChildren(...["overview", "business", "cost", "insurance", "reference"].map(tab));
}

/* ---- the bar, the cards and their controls ---- */

function drawSummary() {
  const wet = st.sections.length ? wetTotals(st.sections, st.rp).wet : wetShops([...st.shops.values()], st.rp);
  const all = st.area.counts?.businesses ?? st.shops.size;
  $("mg-summary").replaceChildren(...summaryCard({ wet, all, rp: st.rp, onPick: pickFloodSize, onOld: (event) => {
    rememberUi("old");
    event.currentTarget.href = mainLink({ place: st.picked });   // the view now, as the click follows it
  } }));
}

function pickFloodSize(rp) {
  const hadFocus = $("mg-summary").contains(document.activeElement);
  st.rp = rp;
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
  $("mg-layers").replaceChildren(...layersCard(st.visible, (key, on) => {
    st.visible[key] = on;
    showLayers(st.map);
  }));
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
  Object.assign($("mg-old"), { textContent: t("mg.oldUi"), title: t("mg.oldUiNote"), onclick: () => rememberUi("old") });
  $("mg-bases").setAttribute("aria-label", t("mg.base.label"));
  $("mg-lang").setAttribute("aria-label", t("mg.lang"));
  $("mg-tabs").setAttribute("aria-label", t("mg.tabsLabel"));
  $("mg-status").textContent = t("mg.status");
  drawLinks();
}

function wireSearch() {
  const box = $("mg-results");
  const input = $("mg-q");
  const close = () => { box.hidden = true; };
  const pick = (entry) => () => { close(); input.value = entry.name; openShop(entry); };
  input.addEventListener("input", () => {
    const hits = searchIndex(st.index, input.value);
    box.replaceChildren(...(hits.length
      ? hits.map((entry) => h("button", { type: "button", onclick: pick(entry) }, entry.name, h("small", {}, sectionName(entry.section))))
      : [h("p", { class: "mg-muted mg-small" }, t("mg.noMatch"))]));
    box.hidden = input.value.trim().length < 2;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || box.hidden) return;
    event.stopPropagation();   // the first Escape closes the list, not the place card
    close();
  });
  input.closest(".mg-search").addEventListener("focusout", (event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) close();
  });
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
  st.eng = glDrawer({ getMap: () => st.map, beforeId: (map) => underRoads(map.getStyle().layers) ?? "mg-section-line",
    hasOurLayers: (map) => Boolean(map.getSource("mg-sections")), isAiming: () => st.pin.isOn(), onToolChange: () => syncCursor() });
  createEngineer({ section: $("mg-eng"), button: $("mg-eng-btn"), area: st.area, drawer: st.eng });
  st.map.getCanvas().addEventListener("keydown", (event) => {
    if (event.key === "Enter" && st.pin.isOn()) st.pin.checkCentre();
  });
}

/** Escape: pin mode ends first, then the card closes; the location dialog has its own. */
function onKey(event) {
  if (event.key !== "Escape" || event.defaultPrevented || st.pin?.isAsking()) return;
  if (st.pin?.isOn()) st.pin.cancel();
  else closeCard();
}

function showProblem(words) {
  $("mg-problem").replaceChildren(words, " ", h("a", { href: "./" }, t("mg.toMain")));
  $("mg-problem").hidden = false;
  say(words, true);
}

async function startFromLink() {
  const { section, place } = st.link;
  if (parseRef(place)?.kind === "point") return openLinkedPoint(place);
  if (section && st.sections.some((known) => known.id === section)) await openSection(section);
  const shop = place && st.shops.get(place);
  if (shop) showShop(shop);
  return undefined;
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
      canPin: (await status)?.points_ready === true });
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
  drawBar(); drawSummary(); drawLayers(); wireSearch();
  try {
    st.map = openMap(style);
  } catch {
    return showProblem(t("mg.noWebgl"));
  }
  addShelters(st.map);
  wireTools();
  document.addEventListener("keydown", onKey);
  say(hint());
  return startFromLink();
}

start();
