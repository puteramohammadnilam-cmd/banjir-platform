/* global maplibregl */
// The 3D flood mock-up (3d.html): the buildings around one shop and the flood model's water on a tilted map, the way a
// property site shows a condo in 3D. Any shop whose section has a bundle (tools/build_flood3d.py, has_3d in
// app/areas.py) opens from the "See in 3D" link on its card, ?area=&section=&place=&rp=; the shop's own words come from
// the section's data. Reading the link and the bundle is in flood3d-data.js.
// ponytail: new words in English only (the depth words are the app's own, so BM follows ?lang=).
import * as api from "./api.js";
import { SCENARIOS, band, depthText, depthWords, h, scenarioLabel } from "./dom.js";
import { findShop, isBundle, readLink, scene } from "./flood3d-data.js";
import { writeUrl } from "./place.js";

const NO_PICTURE = "There is no 3D picture for this shop yet.";
const NO_WEBGL = "This browser cannot draw the 3D map (it needs WebGL).";
const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const WATER = "#2b77a7";     // --band-3
const WET = "#b42318";       // --risk-danger: the shop's walls under water
const SHOP = "#0c447c";      // --brand: the shop's walls above it
const KNOWN = "#c3ccd7";     // --line-strong: a building with its height on the map
const GUESSED = "#f6f7f9";   // --canvas: a building whose height is guessed
const WALL_WET = "#5b84a8";  // any other building's walls under water: a flood mark, darker than the water over it
const WATER_OPACITY = 0.55;
const RISE_MS = 1100;
const FLY_MS = 2600;
const START = { zoom: 16.2, pitch: 0, bearing: 0 };
const VIEW = { zoom: 18, pitch: 62, bearing: 160 };   // from the road, facing the shop fronts

const PANEL_PX = 400;           // the panel over the map's right side on a wide screen (flood3d/flood3d.css)
const WIDE = "(min-width: 701px)";

const $ = (id) => document.getElementById(id);
/** The shop in the middle of the map's open part: left of the panel on a wide screen. */
const padding = () => (window.matchMedia(WIDE).matches ? { right: PANEL_PX } : {});
const motionAllowed = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A flood size's water depth on each square, or 0 before any water (rp null). */
const level = (rp) => (rp ? ["get", `d${rp}`] : 0);

/** Each square's water height a share k (0 to 1) of the way from one flood size to the next. */
export const waterHeight = (from, to, k) => ["+", ["*", level(from), 1 - k], ["*", level(to), k]];

/** The base map: the satellite photo when the server has an imagery key (the street map stays hidden under it, and
 *  loads no tiles until it is switched on), else the street map alone. */
function baseMap(satellite) {
  const raster = (tiles, attribution) => ({ type: "raster", tiles: [tiles], tileSize: 256, maxzoom: 19, attribution });
  const osm = raster(OSM_TILES, "© OpenStreetMap contributors");
  const streets = { id: "osm", type: "raster", source: "osm", layout: { visibility: satellite ? "none" : "visible" } };
  if (!satellite) return { sources: { osm }, layers: [streets] };
  return {
    sources: { osm, satellite: raster(satellite.tiles, satellite.attribution) },
    layers: [streets, { id: "satellite", type: "raster", source: "satellite" }],
  };
}

/** The map's style for a scene (flood3d-data.js): its buildings and water squares, as GeoJSON. */
function style(view, satellite) {
  const shopOnly = ["==", ["get", "shop"], true];
  const base = baseMap(satellite);
  return {
    version: 8,
    sources: {
      ...base.sources,
      buildings: { type: "geojson", data: view.buildings },
      water: { type: "geojson", data: view.water },   // its credit, with the buildings', is in the panel
    },
    layers: [
      ...base.layers,
      // each building twice: its walls under water, then the rest of it from the water line up (setLevel moves the line)
      { id: "walls-wet", type: "fill-extrusion", source: "buildings", filter: ["!", shopOnly], paint: {
        "fill-extrusion-color": WALL_WET, "fill-extrusion-height": 0,
      } },
      { id: "buildings", type: "fill-extrusion", source: "buildings", filter: ["!", shopOnly], paint: {
        "fill-extrusion-color": ["case", ["get", "guessed"], GUESSED, KNOWN],
        "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0,
      } },
      { id: "shop-wet", type: "fill-extrusion", source: "buildings", filter: shopOnly, paint: {
        "fill-extrusion-color": WET, "fill-extrusion-height": 0,
      } },
      { id: "shop-dry", type: "fill-extrusion", source: "buildings", filter: shopOnly, paint: {
        "fill-extrusion-color": SHOP, "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0,
      } },
      { id: "water", type: "fill-extrusion", source: "water", paint: {
        "fill-extrusion-color": WATER, "fill-extrusion-height": 0, "fill-extrusion-opacity": WATER_OPACITY,
      } },
    ],
  };
}

/** Puts the water, and the water line on every building's walls, a share k of the way between two flood sizes. */
function setLevel(map, from, to, k) {
  const water = waterHeight(from, to, k);
  const line = ["min", water, ["get", "h"]];   // each building has its square's depths (tools/build_flood3d.py)
  map.setPaintProperty("water", "fill-extrusion-height", water);
  for (const wet of ["walls-wet", "shop-wet"]) map.setPaintProperty(wet, "fill-extrusion-height", line);
  for (const dry of ["buildings", "shop-dry"]) map.setPaintProperty(dry, "fill-extrusion-base", line);
}

/** Raises (or lowers) the water from one flood size to another; a jump when the person asks for less motion. */
function rise(map, from, to) {
  let frame = 0;
  const start = performance.now();
  const step = (now) => {
    const k = motionAllowed() ? Math.min(1, (now - start) / RISE_MS) : 1;
    setLevel(map, from, to, 1 - (1 - k) ** 3);
    if (k < 1) frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
  return () => cancelAnimationFrame(frame);
}

function showReading(place, rp, pinDepth) {
  const depth = place.depth_m[rp];
  const words = depthWords(depth);
  $("f3d-depth").textContent = depthText(depth);
  $("f3d-words").textContent = `${words.charAt(0).toUpperCase()}${words.slice(1)}, in a flood seen ${scenarioLabel(rp)}`;
  $("f3d-depth").dataset.band = band(depth);
  pinDepth.textContent = band(depth) ? `water ${depthText(depth)}` : depthText(depth);
}

function showProblem(words) {
  $("f3d-name").textContent = words;
  document.body.classList.add("f3d-failed");
}

function sizeButtons(onPick) {
  const buttons = SCENARIOS.map((rp) => h("button", { type: "button", class: "f3d-size", "data-rp": rp,
    onclick: () => onPick(rp) }, scenarioLabel(rp)));
  $("f3d-sizes").replaceChildren(...buttons);
  return (picked) => buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rp === picked)));
}

function openMap(view, shop, satellite) {
  maplibregl.setWorkerUrl("vendor/maplibre-gl-csp-worker.js");
  const map = new maplibregl.Map({ container: "f3d-map", style: style(view, satellite), center: [shop.lon, shop.lat],
    ...START, maxPitch: 75, attributionControl: false });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-left");
  map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");   // clear of the panel
  return map;
}

/** A section's bundle, or null when there is none (or it cannot be read). The ids are checked ones (flood3d-data.js). */
async function loadBundle(areaId, sectionId) {
  try {
    const response = await fetch(`flood3d/${areaId}/${sectionId}.json`);
    const bundle = response.ok ? await response.json() : null;
    return isBundle(bundle) ? bundle : null;
  } catch {
    return null;
  }
}

/** The link's shop and its section's bundle, {found, bundle} (found as findShop gives it), else {problem} in words to
 *  show. A link that names its area and section (the card's) has the bundle asked for beside the shop's data. */
async function loadShop(link) {
  const early = link.area && link.section ? loadBundle(link.area, link.section) : null;   // never rejects
  let found;
  try {
    found = await findShop(link, api);
  } catch (error) {
    return { problem: error.message };   // api.js words: the server's own, or that it could not be reached
  }
  if (!found) return { problem: NO_PICTURE };
  const isAsked = found.areaId === link.area && found.sectionId === link.section;
  const bundle = await (isAsked ? early : loadBundle(found.areaId, found.sectionId));
  return bundle ? { found, bundle } : { problem: NO_PICTURE };
}

/** The satellite tiles the server hands out ({tiles, attribution}), or null: no imagery key on the server, or any
 *  failure asking. The page then shows the street map, so a missing photo never stops the 3D picture. */
async function satelliteTiles() {
  try {
    const response = await fetch("/api/satellite");
    const satellite = response.ok ? (await response.json()).data?.satellite : null;
    return typeof satellite?.tiles === "string" && typeof satellite.attribution === "string" ? satellite : null;
  } catch {
    return null;
  }
}

/** The "Satellite photo" switch, shown only when there is a photo. A tile Esri refuses switches to the street map; the
 *  box can be ticked again. (On 11 Oct 2026 Esri sent imagery for a made-up token, so a bad key may not trip this.) */
function satelliteSwitch(map) {
  const box = $("f3d-satellite");
  const show = (photo) => {
    box.checked = photo;
    map.setLayoutProperty("satellite", "visibility", photo ? "visible" : "none");
    map.setLayoutProperty("osm", "visibility", photo ? "none" : "visible");
  };
  $("f3d-satellite-switch").hidden = false;
  box.addEventListener("change", () => show(box.checked));
  map.on("error", (event) => {
    if (event.sourceId === "satellite") show(false);
    else console.error(event.error ?? event);   // what MapLibre does itself when no one listens
  });
}

/** The panel's words for the shop, and the back link to its card (at the flood size on show: the returned function). */
function showShop({ shop, areaId, areaName, sectionId, sectionName }, bundle) {
  $("f3d-name").textContent = shop.name ?? "";
  $("f3d-section").textContent = sectionName ?? "";
  $("f3d-scope").textContent = areaName ? `The 3D view is ready for shops in ${areaName} only, for now.` : "";
  $("f3d-credit").textContent = `${bundle.credit} · buildings fetched ${bundle.fetched_on}`;
  const back = document.querySelector(".f3d-back");
  return (rp) => back.setAttribute("href", `./${writeUrl({ area: areaId, section: sectionId, place: shop.id, rp })}`);
}

/** The shop's name and depth on a stem over its roof (so it does not hide its walls); returns the depth's slot. */
function addPin(map, shop) {
  const pinDepth = h("span", { class: "f3d-pin-depth" });
  const pin = h("div", { class: "f3d-pin" }, h("p", { class: "f3d-pin-label" }, h("strong", {}, shop.name), pinDepth),
    h("span", { class: "f3d-pin-stem", "aria-hidden": "true" }));
  new maplibregl.Marker({ element: pin, anchor: "bottom" }).setLngLat([shop.lon, shop.lat]).addTo(map);
  return pinDepth;
}

/** Flies in from above to the view from the road, then floods to the first size (unless one was picked meanwhile). */
function flyIn(map, flood) {
  map.on("load", () => {
    if (!motionAllowed()) {
      map.jumpTo({ ...VIEW, padding: padding() });
      flood();
      return;
    }
    map.easeTo({ ...VIEW, padding: padding(), duration: FLY_MS });
    map.once("moveend", flood);
  });
}

async function start() {
  const link = readLink(window.location.search);
  const [loaded, satellite] = await Promise.all([loadShop(link), satelliteTiles()]);
  if (loaded.problem) {
    showProblem(loaded.problem);
    return;
  }
  const { shop } = loaded.found;
  const backTo = showShop(loaded.found, loaded.bundle);
  let map;
  try {
    map = openMap(scene(loaded.bundle, shop), shop, satellite);
  } catch {
    showProblem(NO_WEBGL);
    return;
  }
  const pinDepth = addPin(map, shop);

  let shown = null;
  let stop = () => {};
  const show = (rp) => {
    press(rp);
    showReading(shop, rp, pinDepth);
    backTo(rp);
  };
  const press = sizeButtons((rp) => {
    if (rp === shown) return;
    stop();
    stop = rise(map, shown, rp);
    shown = rp;
    show(rp);
  });
  const first = link.rp ?? SCENARIOS[0];
  show(first);
  if (satellite) satelliteSwitch(map);
  flyIn(map, () => {
    if (shown) return;   // a size was picked during the fly-in, and its water is already rising
    stop = rise(map, null, first);
    shown = first;
  });
}

start();
