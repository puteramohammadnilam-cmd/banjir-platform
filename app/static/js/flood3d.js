/* global maplibregl */
// The 3D flood mock-up (3d.html): one shop's buildings and the flood model's water on a tilted map, the way a
// property site shows a condo in 3D. Data from tools/build_flood3d.py, one JSON per shop in flood3d/.
// ponytail: one shop baked, new words in English only (the depth words are the app's own, so BM follows ?lang=).
// Upgrade path: a "See in 3D" link on the shop card with ?place=, once more shops are baked or an API bakes them.
import { SCENARIOS, band, depthText, depthWords, h, scenarioLabel } from "./dom.js";

const DEFAULT_PLACE = "node-5565878632";   // a 7-Eleven, the one shop baked so far
const PLACE_ID = /^(node|way|relation)-\d{1,15}$/;
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

/** The shop the link asks for (?place=node-123), else the one baked for the mock-up. */
export function placeFromLink(search) {
  const asked = new URLSearchParams(search).get("place");
  return PLACE_ID.test(asked ?? "") ? asked : DEFAULT_PLACE;
}

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

function style(data, satellite) {
  const shopOnly = ["==", ["get", "shop"], true];
  const base = baseMap(satellite);
  return {
    version: 8,
    sources: {
      ...base.sources,
      buildings: { type: "geojson", data: data.buildings },
      water: { type: "geojson", data: data.water },   // its credit, with the buildings', is in the panel
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

function openMap(data, satellite) {
  maplibregl.setWorkerUrl("vendor/maplibre-gl-csp-worker.js");
  const { lon, lat } = data.place;
  const map = new maplibregl.Map({ container: "f3d-map", style: style(data, satellite), center: [lon, lat], ...START,
    maxPitch: 75, attributionControl: false });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-left");
  map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");   // clear of the panel
  return map;
}

/** The shop's baked 3D data, or null when there is none (or it cannot be read). */
async function loadShop(id) {
  try {
    const response = await fetch(`flood3d/${id}.json`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
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

async function start() {
  const id = placeFromLink(window.location.search);
  const [data, satellite] = await Promise.all([loadShop(id), satelliteTiles()]);
  if (!data) {
    showProblem("There is no 3D picture for this shop yet.");
    return;
  }
  const { place } = data;
  $("f3d-name").textContent = place.name;
  $("f3d-section").textContent = place.section_name;
  $("f3d-credit").textContent = `${data.credit} · buildings fetched ${data.fetched_on}`;

  let map;
  try {
    map = openMap(data, satellite);
  } catch {
    showProblem("This browser cannot draw the 3D map (it needs WebGL).");
    return;
  }

  const pinDepth = h("span", { class: "f3d-pin-depth" });
  // the label stands on a stem, so it floats over the shop's roof instead of hiding its walls
  const pin = h("div", { class: "f3d-pin" }, h("p", { class: "f3d-pin-label" }, h("strong", {}, place.name), pinDepth),
    h("span", { class: "f3d-pin-stem", "aria-hidden": "true" }));
  new maplibregl.Marker({ element: pin, anchor: "bottom" })
    .setLngLat([place.lon, place.lat]).addTo(map);

  let shown = null;
  let stop = () => {};
  const press = sizeButtons((rp) => {
    if (rp === shown) return;
    stop();
    stop = rise(map, shown, rp);
    shown = rp;
    press(rp);
    showReading(place, rp, pinDepth);
  });
  const first = SCENARIOS[0];
  press(first);
  showReading(place, first, pinDepth);

  if (satellite) satelliteSwitch(map);

  map.on("load", () => {
    const flood = () => {
      if (shown) return;   // a size was picked during the fly-in, and its water is already rising
      stop = rise(map, null, first);
      shown = first;
    };
    if (!motionAllowed()) {
      map.jumpTo({ ...VIEW, padding: padding() });
      flood();
      return;
    }
    map.easeTo({ ...VIEW, padding: padding(), duration: FLY_MS });
    map.once("moveend", flood);
  });
}

start();
