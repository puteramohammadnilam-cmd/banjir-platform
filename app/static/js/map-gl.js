/* global maplibregl */
// The new map, a preview (map.html, ?map preview of the Area overview): MapLibre on OpenFreeMap's vector base maps
// (copies in vendor/openfreemap, so a change there cannot move our water over the names), Esri's satellite photo through
// our key (app/satellite.py), floating cards, and a place card for a shop or a section. The area's sections are shaded
// at once; a section's squares and shops load when it is opened (one GET each, as the main page does). No pin, no
// engineer tools yet: the main page keeps those, and Leaflet, until this map has them.
// Look adapted from Arus by Farhan Syah (MIT, vendor/LICENSE-arus.txt). The words are in strings/*-map.js.
import * as api from "./api.js";
import { h, s } from "./dom.js";
import { lang, t } from "./i18n.js";
import { layersCard, sectionCard, shopCard, summaryCard } from "./map-gl-card.js";
import { STYLE_FILES, depthRamp, readMapLink, searchIndex, sectionFill, sectionsGeo, shopColour, shopsGeo, squaresGeo,
  underRoads, wetTotals } from "./map-gl-data.js";
import { writeUrl } from "./place.js";

maplibregl.setWorkerUrl("vendor/maplibre-gl-csp-worker.js");   // the CSP build runs its worker from our own file
const $ = (id) => document.getElementById(id);
const PHONE = window.matchMedia("(max-width: 700px)");
const motionAllowed = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const EMPTY = { type: "FeatureCollection", features: [] };
const FLY_MS = 900;
const SHOP_ZOOM = 16;
const FIT_PAD = { top: 120, bottom: 60, left: 380, right: 280 };   // the cards over the map's edges (map-preview/map-gl.css)
const PHONE_PAD = { top: 80, bottom: 120, left: 20, right: 20 };
const TILT = { pitch: 55, bearing: -18 };

const st = {
  link: readMapLink(window.location.search, window.location.hash),
  area: null, sections: [], index: [], shelters: [], satellite: null, styles: {},
  shops: new Map(), cells: new Map(), cellDeg: 0, loaded: new Set(), picked: null, section: null,
  visible: { sections: true, squares: true, shops: true, shelters: true }, markers: [], map: null,
};
st.rp = st.link.rp;
st.base = st.link.base;
st.tilt = st.link.tilt;

const isDark = () => st.base !== "map";
const pageLink = (extra = {}) => writeUrl({ area: st.area?.id, section: st.section, rp: st.rp, lang: lang === "en" ? null : lang, ...extra });
const mainLink = (extra) => `./${pageLink(extra)}`;
const say = (words) => { $("mg-hint").textContent = words; };

/* ---- the base maps ---- */

async function baseStyle(base) {
  if (base === "sat") return satelliteStyle();
  st.styles[base] ??= await fetch(STYLE_FILES[base]).then((r) => r.json());
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

/* ---- our layers: sections, squares, shops ---- */

const squaresData = () => squaresGeo([...st.cells.values()], st.cellDeg);
const shopsData = () => shopsGeo([...st.shops.values()]);

function addSources(map) {
  map.addSource("mg-sections", { type: "geojson", data: sectionsGeo(st.sections) });
  map.addSource("mg-squares", { type: "geojson", data: st.cellDeg ? squaresData() : EMPTY });
  map.addSource("mg-shops", { type: "geojson", data: shopsData() });
}

function addOurLayers(map) {
  if (!st.area || map.getSource("mg-sections")) return;
  addSources(map);
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
  if (st.tilt) addBuildings(map);
  showLayers(map);
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
  if (!map.getLayer("mg-squares")) return;
  map.setPaintProperty("mg-squares", "fill-color", depthRamp(st.rp, isDark()));
  map.setPaintProperty("mg-shops", "circle-color", shopColour(st.rp));
  map.setPaintProperty("mg-section-fill", "fill-color", sectionFill(st.rp));
}

/* ---- a section's squares and shops ---- */

async function loadSection(sectionId) {
  if (st.loaded.has(sectionId)) return;
  const name = st.sections.find((section) => section.id === sectionId)?.name ?? sectionId;
  say(t("mg.sectionLoading", { name }));
  const data = await api.getSectionData(st.area.id, sectionId);
  st.loaded.add(sectionId);
  st.cellDeg = data.town.cell_deg;
  data.town.cells.forEach((cell) => st.cells.set(`${cell[0]},${cell[1]}`, cell));
  data.premises.forEach((premise) => st.shops.set(premise.id, premise));
  st.map.getSource("mg-squares")?.setData(squaresData());
  st.map.getSource("mg-shops")?.setData(shopsData());
  say(t("mg.hint"));
}

function fitSection(sectionId) {
  const bbox = st.sections.find((section) => section.id === sectionId)?.bbox;
  if (bbox) st.map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: PHONE.matches ? PHONE_PAD : FIT_PAD, duration: motionAllowed() ? FLY_MS : 0, maxZoom: 16 });
}

/* ---- the place card ---- */

function showCard(nodes) {
  const card = $("mg-place");
  card.replaceChildren(...nodes);
  card.hidden = false;
  card.querySelector("h2")?.focus({ preventScroll: true });
}

function closeCard() {
  st.picked = null;
  $("mg-place").hidden = true;
  st.map?.getLayer("mg-picked") && st.map.setFilter("mg-picked", ["==", ["get", "id"], ""]);
  writeLink();
  say(t("mg.hint"));
}

function shopLinks(shop) {
  const at = { section: shop.section, place: shop.id };
  return {
    details: mainLink({ ...at, tab: "business" }), cost: mainLink({ ...at, tab: "cost" }),
    see3d: st.area.has_3d ? `3d.html${writeUrl({ area: st.area.id, ...at, rp: st.rp })}` : null,
    directions: `https://www.google.com/maps/dir/?api=1&destination=${shop.lat},${shop.lon}`,
  };
}

async function share() {
  const url = window.location.href;
  if (navigator.share) return navigator.share({ url }).catch(() => {});
  await navigator.clipboard?.writeText(url).then(() => say(t("mg.shared")), () => {});
}

function showShop(shop, { fly = false } = {}) {
  st.picked = shop.id;
  st.section = shop.section ?? st.section;
  st.map.getLayer("mg-picked") && st.map.setFilter("mg-picked", ["==", ["get", "id"], shop.id]);
  const sectionName = st.sections.find((section) => section.id === shop.section)?.name ?? "";
  showCard(shopCard(shop, { rp: st.rp, sectionName, shelters: st.shelters, links: shopLinks(shop), onClose: closeCard, onShare: share }));
  // on a phone the card is a sheet over the map's lower part, so the shop goes in the part still showing
  const padding = PHONE.matches ? { bottom: $("mg-place").offsetHeight } : undefined;
  const duration = motionAllowed() ? FLY_MS : 0;
  if (fly) st.map.flyTo({ center: [shop.lon, shop.lat], zoom: Math.max(st.map.getZoom(), SHOP_ZOOM), padding, duration });
  else if (padding) st.map.easeTo({ center: [shop.lon, shop.lat], zoom: Math.max(st.map.getZoom(), SHOP_ZOOM - 1), padding, duration });
  writeLink();
  say(shop.name);
}

async function openSection(sectionId, { fit = true } = {}) {
  st.section = sectionId;
  st.picked = null;
  st.map.getLayer("mg-picked") && st.map.setFilter("mg-picked", ["==", ["get", "id"], ""]);
  const props = sectionsGeo(st.sections).features.find((f) => f.properties.id === sectionId)?.properties;
  if (props) showCard(sectionCard(props, { rp: st.rp, link: mainLink({ section: sectionId }), onClose: closeCard }));
  if (fit) fitSection(sectionId);
  writeLink();
  await loadSection(sectionId).catch((error) => say(t("mg.failed", { why: error.message })));
}

async function openShop(entry) {
  await openSection(entry.section, { fit: false });
  const shop = st.shops.get(entry.id);
  if (shop) showShop(shop, { fly: true });
}

/** This page's own address for what is on show, so a shared link opens the same view. */
function writeLink() {
  const query = writeUrl({ area: st.area?.id, section: st.section, place: st.picked, rp: st.rp, lang: lang === "en" ? null : lang });
  const base = st.base === "map" ? "" : `${query.length > 1 ? "&" : ""}base=${st.base}`;
  window.history.replaceState(null, "", `map.html${query}${base}`);
}

/* ---- the bar, the cards and their controls ---- */

function drawSummary() {
  const { wet } = wetTotals(st.sections, st.rp);
  const all = st.area.counts?.businesses ?? wetTotals(st.sections, st.rp).all;
  $("mg-summary").replaceChildren(...summaryCard({ wet, all, rp: st.rp, onPick: pickFloodSize }));
}

function pickFloodSize(rp) {
  st.rp = rp;
  paintFloodSize(st.map);
  drawSummary();
  const shop = st.picked && st.shops.get(st.picked);
  if (shop) showShop(shop);
  writeLink();
}

function drawLayers() {
  $("mg-layers").replaceChildren(...layersCard(st.visible, (key, on) => {
    st.visible[key] = on;
    showLayers(st.map);
  }));
}

async function pickBase(base) {
  if (base === st.base) return;
  st.base = base;
  document.documentElement.dataset.theme = isDark() ? "dark" : "light";
  document.querySelectorAll("[data-base]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.base === base)));
  st.map.setStyle(await baseStyle(base), { diff: false });   // a diffed swap fires no style.load, so ours would not come back
  writeLink();
}

function toggleTilt() {
  st.tilt = !st.tilt;
  $("mg-tilt").setAttribute("aria-pressed", String(st.tilt));
  if (st.tilt) addBuildings(st.map);
  else if (st.map.getLayer("mg-buildings")) st.map.removeLayer("mg-buildings");
  st.map.easeTo({ ...(st.tilt ? TILT : { pitch: 0, bearing: 0 }), duration: motionAllowed() ? FLY_MS : 0 });
}

function drawBar() {
  const base = (key) => h("button", { type: "button", "data-base": key, "aria-pressed": String(key === st.base), onclick: () => pickBase(key) }, t(`mg.base.${key}`));
  const bases = ["map", ...(st.satellite ? ["sat"] : []), "dark"];
  $("mg-bases").replaceChildren(...bases.map(base));
  $("mg-tilt").textContent = t("mg.tilt");
  $("mg-tilt").setAttribute("aria-pressed", String(st.tilt));
  $("mg-tilt").onclick = toggleTilt;
  const langLink = (code, label) => h("a", { href: `map.html${writeUrl({ area: st.area.id, section: st.section, place: st.picked, rp: st.rp, lang: code })}`,
    "aria-current": code === lang ? "true" : null }, label);
  $("mg-lang").replaceChildren(langLink("ms", "BM"), langLink("en", "EN"));
  $("mg-area").textContent = st.area.display_name ?? st.area.name;
  $("mg-home").href = mainLink({});
  $("mg-home").setAttribute("aria-label", t("mg.back"));
  Object.assign($("mg-q"), { placeholder: t("mg.search") });
  $("mg-q").setAttribute("aria-label", t("mg.searchLabel"));
  $("mg-tag").textContent = t("mg.preview");
  $("mg-tag").title = t("mg.previewNote");
  $("mg-tilt").title = t("mg.tiltLabel");
  $("mg-bases").setAttribute("aria-label", t("mg.base.label"));
  $("mg-lang").setAttribute("aria-label", t("mg.lang"));
  $("mg-tabs").setAttribute("aria-label", t("mg.tabsLabel"));
  $("mg-status").textContent = t("mg.status");
  const tab = (key) => h("a", { href: key === "overview" ? mainLink({}) : mainLink({ tab: key }), "aria-current": key === "overview" ? "page" : null }, t(`tab.${key}`));
  $("mg-tabs").replaceChildren(...["overview", "business", "cost", "insurance", "reference"].map(tab));
}

function wireSearch() {
  const box = $("mg-results");
  const pick = (entry) => () => { box.hidden = true; $("mg-q").value = entry.name; openShop(entry); };
  $("mg-q").addEventListener("input", (event) => {
    const hits = searchIndex(st.index, event.target.value);
    const sectionName = (id) => st.sections.find((section) => section.id === id)?.name ?? "";
    box.replaceChildren(...(hits.length
      ? hits.map((entry) => h("button", { type: "button", onclick: pick(entry) }, entry.name, h("small", {}, sectionName(entry.section))))
      : [h("p", { class: "mg-muted mg-small" }, t("mg.noMatch"))]));
    box.hidden = event.target.value.trim().length < 2;
  });
}

function addShelters(map) {
  st.markers = st.shelters.map((shelter) => {
    const mark = h("div", { class: "mg-shelter", title: `${t("mg.shelterTitle")}: ${shelter.name}`, role: "img", "aria-label": `${t("mg.shelterTitle")}: ${shelter.name}` },
      s("svg", { width: "18", height: "16", viewBox: "0 0 18 16", "aria-hidden": "true" },
        s("path", { d: "M9 1 17 15H1z", fill: "#16a34a", stroke: "#fff", "stroke-width": "1.6", "stroke-linejoin": "round" })));
    return new maplibregl.Marker({ element: mark }).setLngLat([shelter.lon, shelter.lat]).addTo(map);
  });
}

/* ---- the map ---- */

function onMapClick(event) {
  const map = st.map;
  const shop = map.queryRenderedFeatures(event.point, { layers: ["mg-shops"] })[0];
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
  map.on("click", onMapClick);
  map.on("mouseenter", "mg-shops", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "mg-shops", () => { map.getCanvas().style.cursor = ""; });
  if (st.tilt) map.once("load", () => map.easeTo({ ...TILT, duration: 0 }));
  return map;
}

function showProblem(words, withLink = false) {
  $("mg-problem").replaceChildren(words, withLink ? h("a", { href: "./" }, ` ${t("mg.toMain")}`) : null);
  $("mg-problem").hidden = false;
}

async function startFromLink() {
  const { section, place } = st.link;
  if (!section || !st.sections.some((known) => known.id === section)) return;
  await openSection(section);
  const shop = place && st.shops.get(place);
  if (shop) showShop(shop);
}

async function start() {
  document.title = t("mg.title");
  document.documentElement.lang = lang;
  document.documentElement.dataset.theme = isDark() ? "dark" : "light";
  $("mg-map").setAttribute("aria-label", t("mg.mapLabel"));
  say(t("mg.loading"));
  let data;
  try {
    [data, st.satellite] = await Promise.all([st.link.area ? api.getAreaData(st.link.area) : api.getDefaultData(), satelliteTiles()]);
  } catch (error) {
    return showProblem(t("mg.failed", { why: error.message }), true);
  }
  Object.assign(st, { area: data.area, sections: data.sections ?? [], index: data.index ?? [], shelters: data.town?.shelters ?? [] });
  if (st.base === "sat" && !st.satellite) st.base = "map";
  drawBar(); drawSummary(); drawLayers(); wireSearch();
  try {
    st.map = openMap(await baseStyle(st.base));
  } catch {
    return showProblem(t("mg.noWebgl"), true);
  }
  addShelters(st.map);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeCard(); });
  say(t("mg.hint"));
  await startFromLink();
}

start();
