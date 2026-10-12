/* global L */
import { createCellLayer, squareStyle } from "./cells.js";
import { DRY_COLOR, SCENARIOS, band, bandColor, depthText, depthWords, h, icon, s, scenarioLabel } from "./dom.js";
import { t } from "./i18n.js";
import { overlapsView } from "./place.js";

const INK = "#0d1b2a";
const SELECTED = "#0d1b2a";   // --marker in tokens.css: an ink ring, apart from the water and risk colours
const BRAND = "#0c447c";      // --brand: a section's outline
const FOCUS_ZOOM = 17;
const MIN_ZOOM = 6;   // far enough out to see about all of Malaysia on a wide screen
const FIT_SNAP = 0.25;   // a city or a section fills the map more closely than whole zoom steps allow
const MALAYSIA_BOUNDS = [[0.5, 98.5], [8.0, 120.0]];   // [[south, west], [north, east]]: the country, with sea around it
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; OpenStreetMap contributors · flood depth: JRC v2.1 (CC BY 4.0)';

// Leaflet treats string tooltips as HTML. Names come from a public map, so pass a text node.
const label = (text) => document.createTextNode(text);

/** Whether the person asks the page not to move things about: then the map jumps instead of gliding. */
const motionAllowed = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// A touch screen: one finger scrolls the page past the map and two move it (Leaflet's pinch pans as it zooms), so a
// phone is never stuck on a map that fills its screen. Aim mode gives one finger back: the cross is aimed by dragging.
const IS_TOUCH = globalThis.matchMedia?.("(pointer: coarse)").matches ?? false;   // false in node, where the tests run
const HINT_MS = 1500;

/** On a touch screen a one-finger drag on the map scrolls the page, so it says for a moment how to move the map.
 *  Hidden from screen readers: it answers a gesture, and the map's keys work as before. */
function addTwoFingerHint(map) {
  const container = map.getContainer();
  const hint = h("p", { class: "map-hint", "aria-hidden": "true" }, t("map.twoFingers"));
  container.append(hint);
  let timer = 0;
  container.addEventListener("touchmove", (event) => {
    if (event.touches.length !== 1 || map.dragging.enabled()) return;
    hint.classList.add("is-shown");
    clearTimeout(timer);
    timer = setTimeout(() => hint.classList.remove("is-shown"), HINT_MS);
  }, { passive: true });
  container.addEventListener("touchstart", (event) => {
    if (event.touches.length > 1) hint.classList.remove("is-shown");   // two fingers down: they are doing it
  }, { passive: true });
}

/** The Leaflet map on the page's own view and zoom (the area's config, or a section's box), with the base tiles. It can be
 *  moved over all of Malaysia. */
function openMap(element, { view: [west, south, east, north], zoom, fit = false }) {
  const glide = motionAllowed();   // with reduced motion asked for, zooms and fades are jumps
  const map = L.map(element, {
    scrollWheelZoom: false, dragging: !IS_TOUCH, maxBounds: MALAYSIA_BOUNDS, minZoom: MIN_ZOOM, zoomSnap: fit ? FIT_SNAP : 1,
    zoomAnimation: glide, fadeAnimation: glide, markerZoomAnimation: glide,
  });
  if (IS_TOUCH) addTwoFingerHint(map);
  // a whole city fills the map, once the map has a size to measure (followResize shows the view again as that changes)
  const showView = () => (fit && element.clientHeight > 0
    ? map.fitBounds([[south, west], [north, east]], { animate: false })
    : map.setView([(south + north) / 2, (west + east) / 2], zoom, { animate: false }));
  showView();
  followResize(map, element, showView);
  L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
  return map;
}

/** Leaflet measures its box once. The box can change after the map opens: the size picker and the key are drawn into the
 *  card later, a wide screen's map fills the window's height, and a map on a tab that is not on show has no size. So
 *  Leaflet is told of each change, and until someone (or the page, going to a shop) moves the map, the area's view is
 *  shown again. Leaflet fires movestart at once for a move without animation, and none for invalidateSize. */
export function followResize(map, element, showView) {
  if (typeof ResizeObserver !== "function") return;
  let isUntouched = true;
  map.on("movestart", () => { isUntouched = false; });   // a drag, a zoom, a shop or point shown; resizing fires no movestart
  new ResizeObserver(() => {
    if (!element.clientHeight) return;
    map.invalidateSize({ pan: true });
    if (!isUntouched) return;
    showView();
    isUntouched = true;   // showing the view is not a move by anyone
  }).observe(element);
}

/** The flood model's squares, each kept with its depths for the flood sizes; paintSquares colours them (cells.js ramp).
 *  On the map's one canvas (`renderer`): a section can have thousands, and an element each would slow a phone. */
function addSquares(map, town, renderer) {
  const size = town.cell_deg;
  return town.cells.map(([cellSouth, cellWest, ...depths]) => ({
    depths,
    layer: L.rectangle([[cellSouth, cellWest], [cellSouth + size, cellWest + size]], { stroke: false, interactive: false, renderer }).addTo(map),
  }));
}

/** A section's outline (GeoJSON), over its squares; it takes no clicks. */
function addOutline(map, outline, renderer) {
  if (!outline) return;
  L.geoJSON(outline, { renderer, interactive: false, style: { color: BRAND, weight: 2.5, opacity: 0.85, fill: false, dashArray: "7 5" } }).addTo(map);
}

function addShelters(map, shelters) {
  for (const shelter of shelters) {
    L.marker([shelter.lat, shelter.lon], { icon: L.divIcon({ className: "shelter-pin", iconSize: [16, 14] }), keyboard: false })
      .bindTooltip(label(shelter.name), { permanent: true, direction: "right", className: "shelter-label", offset: [8, 0] })
      .addTo(map);
  }
}

/** A business's popup for one flood size. */
function popupBody(map, p, rp, onOpen) {
  const depth = p.depth_m[rp];
  return h("div", {},
    h("p", { class: "pop-name" }, p.name),
    h("p", { class: "pop-depth" }, band(depth) ? h("strong", {}, `${depthText(depth)}, ${depthWords(depth)}`) : t("overview.legendDry"),
      t("map.inFlood", { label: scenarioLabel(rp) })),
    h("button", { type: "button", class: "btn btn-primary", onclick: () => { map.closePopup(); onOpen(p.id); } }, t("map.openDetails")));
}

/** One dot per business, with its name on hover and a popup for the flood size on show (getRp gives it). */
function addMarkers(map, premises, getRp, { onSelect, onOpen }) {
  return new Map(premises.map((p) => [p.id, {
    p,
    marker: L.circleMarker([p.lat, p.lon], { fillOpacity: 1, className: "biz-dot" })
      .bindTooltip(label(p.name))
      .bindPopup(() => popupBody(map, p, getRp(), onOpen))
      .on("click", () => onSelect(p.id))
      .addTo(map),
  }]));
}

const paintSquares = (squares, index) => { for (const { depths, layer } of squares) layer.setStyle(squareStyle(depths, index)); };

/** How one shop dot looks: a thick ink ring and bigger when selected, small and pale when the model has no water there. */
function dotStyle(depth, selected) {
  if (selected) return { radius: 12, color: SELECTED, weight: 5, fillColor: bandColor(depth) };   // bigger and thicker than any other dot
  if (!band(depth)) return { radius: 4, color: INK, weight: 1.5, fillColor: DRY_COLOR };   // "no water" differs in size, not just in tint
  return { radius: 7, color: INK, weight: 1.5, fillColor: bandColor(depth) };   // an ink ring: pale dots stand out on pale squares
}

/** The shop dots for one flood size, the selected one ringed. */
function paintMarkers(markers, rp, selectedId) {
  for (const { p, marker } of markers.values()) {
    const selected = p.id === selectedId;
    marker.setStyle(dotStyle(p.depth_m[rp], selected));
    if (selected) marker.bringToFront();
  }
}

function focusMarker(map, entry) {
  if (!entry) return;
  map.setView(entry.marker.getLatLng(), FOCUS_ZOOM);
  entry.marker.openPopup();
}

// ---------- a picture on the map (flash flood potential, low ground), over the tiles, under the squares and dots ----------

// Leaflet's panes: tiles at 200, the overlay pane (squares, outlines, dots) at 400. Each picture goes between them in a
// pane of its own; a pane with a smaller zIndex lies under one with a larger.
const PICTURE_PANE = "picture";
const PICTURE_Z = 350;
/** [[south, west], [north, east]] for [west, south, east, north], or corners as given. */
const corners = (bounds) => (Array.isArray(bounds[0]) ? bounds : [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]);

/** `layer` {url, bounds} as an image overlay in `pane` (made at `zIndex` when new), made (so fetched) on the first
 *  show(true). A load error takes it off and calls onError(); the next show(true) tries again. */
export function createPictureLayer(map, { url, bounds }, { opacity, className, pane = PICTURE_PANE, zIndex = PICTURE_Z, onError = () => {} }) {
  let picture = null;
  const make = () => {
    if (!map.getPane(pane)) Object.assign(map.createPane(pane).style, { zIndex: String(zIndex), pointerEvents: "none" });
    const made = L.imageOverlay(url, corners(bounds), { pane, opacity, className, interactive: false });
    return made.on("error", () => {
      made.remove();
      if (picture === made) picture = null;
      onError();
    });
  };
  return {
    show(isOn) {
      if (!isOn) {
        picture?.remove();
        return;
      }
      picture ??= make();
      picture.addTo(map);
    },
  };
}

// ---------- a point someone checked: a pin, and the 90 m square it stands for ----------

const pinIcon = () => L.divIcon({
  className: "point-pin", iconSize: [30, 40], iconAnchor: [15, 40],
  html: s("svg", { viewBox: "0 0 30 40", width: 30, height: 40, "aria-hidden": "true" },
    s("path", { d: "M15 39S2 25.5 2 14.5a13 13 0 0 1 26 0C28 25.5 15 39 15 39z" }), s("circle", { cx: 15, cy: 14.5, r: 5 })),
});

/** One pin at a time, with the outline of its flood square (the Place's `cell.bounds`: [west, south, east, north]). It
 *  only marks the place: it takes no clicks and no focus. The outline goes on the map's canvas, so that no layer of
 *  another kind lies over the canvas and takes the pointer from the whole city's sections. */
function createPointLayer(map, renderer) {
  let shown = null;   // {id, marker, outline}
  return {
    show(place) {
      shown?.marker.remove();
      shown?.outline.remove();
      const [west, south, east, north] = place.cell.bounds;
      shown = {
        id: place.id,
        marker: L.marker([place.lat, place.lon], { icon: pinIcon(), interactive: false, keyboard: false }).addTo(map),
        outline: L.rectangle([[south, west], [north, east]], { color: SELECTED, weight: 3, fill: false, interactive: false, renderer }).addTo(map),
      };
    },
    /** Moves the map to the pin when `id` is the point on show; false when it is not. */
    focus(id) {
      if (shown?.id !== id) return false;
      map.setView(shown.marker.getLatLng(), FOCUS_ZOOM);
      return true;
    },
  };
}

// ---------- aim mode: a cross over the middle of the map, which is what gets checked ----------

/** Two strokes for each arm of the cross, so it reads on light and on dark ground: a wide halo, then the line. */
function crossIcon() {
  const arms = [[2, 26, 19, 26], [33, 26, 50, 26], [26, 2, 26, 19], [26, 33, 26, 50]];
  const line = (kind) => ([x1, y1, x2, y2]) => s("line", { class: kind, x1, y1, x2, y2 });
  return s("svg", { viewBox: "0 0 52 52", width: 52, height: 52 },
    arms.map(line("halo")), arms.map(line("core")), s("circle", { class: "dot", cx: 26, cy: 26, r: 3.5 }));
}

/** Puts the cross over the middle of the map, and the panel's words as the map's description; gives back the cross
 *  and the description the map had before (the whole city's map is described by its table), to put back after. */
function showCross(map, describedBy) {
  const cross = h("div", { class: "aim-cross", "aria-hidden": "true" }, crossIcon());
  const container = map.getContainer();
  const before = container.getAttribute("aria-describedby");
  container.append(cross);
  container.setAttribute("aria-describedby", describedBy);
  return { cross, before };
}

function hideCross(map, { cross, before }) {
  cross.remove();
  if (before) map.getContainer().setAttribute("aria-describedby", before);
  else map.getContainer().removeAttribute("aria-describedby");
}

/** In Chrome a shape in an SVG that has a focus listener can be tabbed to, and every shop's dot has one (its tooltip
 *  opens on focus). Aim mode is about the cross, and a keyboard user should not have to tab past each shop to reach its
 *  buttons, so the dots are left out of the tab order while it lasts. Clicks and hovers are not affected. */
function setDotsTabbable(map, isTabbable) {
  for (const dot of map.getContainer().querySelectorAll("path.leaflet-interactive")) {
    if (isTabbable) dot.removeAttribute("tabindex");
    else dot.setAttribute("tabindex", "-1");
  }
}

/** A button on the map that starts aim mode, beside the zoom buttons. Gives back what hides or shows it. */
function addAimButton(map, onCheckPoint) {
  const button = h("button", { type: "button", class: "map-aim-button", onclick: (event) => onCheckPoint(event.currentTarget) },
    icon("pin"), t("map.checkPoint"));
  const box = h("div", {}, button);
  L.DomEvent.disableClickPropagation(box);
  const control = L.control({ position: "topright" });
  control.onAdd = () => box;
  control.addTo(map);
  return (isHidden) => { box.hidden = isHidden; };
}

/** Aim mode takes a tap to move the map's middle to where it fell. The page moves the map with moveTo, which does not
 *  count as the person moving it: enter()'s onMove is only for them (a drag, the arrow keys, a tap, the zoom buttons). */
function createAim(map, setButtonHidden, renderer) {
  let active = null;   // {cross, onMoved, ring} while aiming
  let isQuiet = false;
  const recentre = (event) => map.panTo(event.latlng, { animate: motionAllowed() });
  return {
    enter({ onMove, describedBy }) {
      if (active) return;
      const onMoved = () => { if (!isQuiet) onMove(); };
      map.doubleClickZoom.disable();   // a tap moves the map, so a double tap is two moves, not a zoom
      map.dragging.enable();   // on a touch screen too: the help says to move the map under the cross
      map.on("click", recentre).on("moveend", onMoved);
      active = { cross: showCross(map, describedBy), onMoved, ring: null };
      setDotsTabbable(map, false);
      setButtonHidden(true);
    },
    exit() {
      if (!active) return;
      map.off("click", recentre).off("moveend", active.onMoved);
      map.doubleClickZoom.enable();
      if (IS_TOUCH) map.dragging.disable();   // one finger scrolls the page again
      hideCross(map, active.cross);
      active.ring?.remove();
      active = null;
      setDotsTabbable(map, true);
      setButtonHidden(false);
    },
    centre: () => ({ lat: map.getCenter().lat, lon: map.getCenter().lng }),
    /** Puts (lat, lon) under the cross at `zoom`, with no glide. False, moving nothing, when it is beyond what the map can show. */
    moveTo(lat, lon, zoom) {
      if (!L.latLngBounds(MALAYSIA_BOUNDS).contains([lat, lon])) return false;
      isQuiet = true;
      try {
        map.setView([lat, lon], zoom, { animate: false });
      } finally {
        isQuiet = false;
      }
      return true;
    },
    /** A circle {lat, lon, metres} for how far off a location fix may be, until aim mode ends or the next fix; null
     *  takes the last one off, for a fix that needs none. */
    showAccuracy(circle) {
      if (!active) return;
      active.ring?.remove();
      const ring = circle && L.circle([circle.lat, circle.lon], { radius: circle.metres, color: SELECTED, weight: 2, fillOpacity: 0.08, interactive: false, renderer }).addTo(map);
      active = { ...active, ring: ring || null };
    },
    focus: () => map.getContainer().focus({ preventScroll: true }),
    isActive: () => active !== null,
  };
}

/** `frame` is what the map opens on ({view, zoom}; fit: fill the map with the view, as for a whole city), `ownedBox` the box whose squares are the page's own (town.json has
 *  every wet square that overlaps it; null when the page draws none of its own, as on a whole city's map) and `outline`
 *  a section's outline to draw, or null. Squares, outlines and the whole city's sections share one canvas; the shop dots
 *  stay SVG, over it. `onCheckPoint(button)` is for the pin and GPS flow (pin.js); with none, the page offers no way to
 *  check a point. */
export function createMap(element, { view, zoom, ownedBox = view, outline = null, fit = false }, town, premises, { onSelect, onOpen, onCheckPoint = null }) {
  const map = openMap(element, { view, zoom, fit });
  const renderer = L.canvas({ padding: 0.5 });
  const squares = addSquares(map, town, renderer);
  addOutline(map, outline, renderer);
  addShelters(map, town.shelters);
  let shownRp = null;
  const markers = addMarkers(map, premises, () => shownRp, { onSelect, onOpen });
  const isOwned = ownedBox ? (grid, south, west) => overlapsView(ownedBox, south, west, grid) : () => false;
  const cells = createCellLayer(map, () => SCENARIOS.indexOf(shownRp), isOwned, renderer);
  const point = createPointLayer(map, renderer);
  const aim = createAim(map, onCheckPoint ? addAimButton(map, onCheckPoint) : () => {}, renderer);

  return {
    /** Colour the squares and the shop dots for one flood size, and ring the selected shop. */
    show(rp, selectedId) {
      if (rp !== shownRp) {
        paintSquares(squares, SCENARIOS.indexOf(rp));
        shownRp = rp;
        cells.restyle();
      }
      paintMarkers(markers, rp, selectedId);
    },
    /** Leaflet measures its box once; call this after the map's tab becomes visible. */
    refresh() {
      map.invalidateSize();
    },
    /** Move to a shop and open its popup, or to the point on show. */
    focus(id) {
      if (!point.focus(id)) focusMarker(map, markers.get(id));
    },
    /** Draw the flood squares that came with a point (its blocks and cells, from POST /api/point) on a grid; see cells.js. */
    showSquares: cells.show,
    /** Drop the pin on a checked point's square, and outline the square. */
    showPoint: point.show,
    enterAim: aim.enter,
    exitAim: aim.exit,
    aimCentre: aim.centre,
    aimAt: aim.moveTo,
    showAccuracy: aim.showAccuracy,
    focusMap: aim.focus,
    /** Puts more on the map: build({map, renderer, isAiming}) gets the Leaflet map, its canvas and whether a point is
     *  being aimed at (a tap then moves the map, so it must open nothing), and gives back what it made. */
    addOverlay: (build) => build({ map, renderer, isAiming: aim.isActive }),
  };
}
