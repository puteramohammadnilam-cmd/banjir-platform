// One page's worth for the tests of "Check any point" (pin.js), shared by tests/pin_flow.test.mjs (aim mode, the check, the
// location) and tests/pin_squares.test.mjs (the pin, and the flood squares that come with a point): the fake map, a fake
// server behind `fetch` and the places they use. A helper, not a test file. The browser's parts are stand-ins: the DOM of
// pin_dom.mjs, a fake map, a fake server and a fake geolocation.
import { COVERAGE, E100, PanelElement, installPinDom } from "./pin_dom.mjs";
import { createPin } from "../app/static/js/pin.js";
import { parseRef, snapToGrid } from "../app/static/js/place.js";

export const SRI_MUDA_VIEW = [101.515, 3.008, 101.55, 3.042];
export const KL = [3.1478, 101.6953];          // central Kuala Lumpur: pt:3.14748,101.69500, outside every area's view
export const KUCHING = [1.5535, 110.3593];     // not in the E100 files: Borneo
export const KUAH = [6.33, 99.84];             // Langkawi
export const STRAIT = [3.0, 99.7];             // inside the Peninsula's box, west of the files
export const SRI_MUDA = [3.0297599, 101.5364982];   // inside Taman Sri Muda's view
export const NORTH_OF_KL = [3.2, 101.7];
export const FIX_OPTIONS = { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 };

/** Lets what is waiting settle: promises, and the two frames the first words of aim mode wait for. */
export const flush = async () => {
  for (let round = 0; round < 5; round += 1) await new Promise((resolve) => setImmediate(resolve));
};
export const deferred = () => {
  const gate = {};
  gate.promise = new Promise((resolve, reject) => Object.assign(gate, { resolve, reject }));
  return gate;
};

/** The Place the server gives for the square that holds (lat, lon): the shape of POST /api/point's `place`. */
export function placeAt(lat, lon) {
  const square = snapToGrid(lat, lon, [E100]);
  const centre = parseRef(square.id);
  const west = E100.x0 + square.col * E100.px;
  const north = E100.y0 - square.row * E100.py;
  const bounds = [west, north - E100.py, west + E100.px, north].map((edge) => Number(edge.toFixed(6)));
  return {
    id: square.id, is_point: true, name: null, sector: null, kind: null, is_chain: null, lat: centre.lat, lon: centre.lon,
    area_id: null, depth_m: { 10: null, 20: 0.5, 50: 1 }, road: null, shelter: null,
    cell: { grid: square.grid, row: square.row, col: square.col, bounds },
  };
}

/** A fake server behind `fetch`. The handler gets (path, body) and gives the answer's data; it may throw (the server
 *  cannot be reached) or give {failure: "words"} (the server answered with an error). Gives back what was asked. */
export function serve(handler) {
  const asked = [];
  globalThis.fetch = async (path, init) => {
    const body = init?.body ? JSON.parse(init.body) : null;
    asked.push({ path, body });
    const data = await handler(path, body);
    const answer = data?.failure ? { success: false, data: null, error: data.failure } : { success: true, data, error: null };
    return { json: async () => answer };
  };
  return asked;
}

// The squares that come with a point: the blocks around its square and their wet squares, as POST /api/point gives them.
export const BLOCKS = [{ grid: "N10_E100", bi: 348, bj: 77 }, { grid: "N10_E100", bi: 348, bj: 78 }];
export const CELLS = [[3.1, 101.6, null, 0.5, 1.0], [3.1, 101.7, 0.3, 0.8, 1.4]];
export const SQUARES = { blocks: BLOCKS, cells: CELLS };

export const covering = (path, body) => ({ coverage: "covered", region: "peninsula", place: placeAt(body.lat, body.lon), ...SQUARES });

export function fakeMap(anchor, start = { lat: 3.025, lon: 101.5325 }) {
  const calls = [];
  let centre = start;
  const map = {
    calls, offMap: false, wet: null,   // wet: how many squares the layer says are wet; null: all that were given
    enterAim(options) { calls.push(["enterAim", options.describedBy]); map.onMove = options.onMove; },
    exitAim() { calls.push(["exitAim"]); },
    aimCentre: () => centre,
    aimAt(lat, lon, zoom) {
      calls.push(["aimAt", lat, lon, zoom]);
      if (map.offMap) return false;
      centre = { lat, lon };
      return true;
    },
    showAccuracy(circle) { calls.push(["showAccuracy", circle]); },
    focusMap() {
      calls.push(["focusMap"]);
      globalThis.document.activeElement = anchor;   // the map's element is what takes focus
    },
    showPoint(place) { calls.push(["showPoint", place.id]); },
    /** Draws the squares that came with a point; says how many of them are wet. */
    showSquares(grid, blocks, cells) {
      calls.push(["showSquares", grid.name, blocks.length, cells.length]);
      return map.wet ?? cells.length;
    },
    /** The person moves the map: the cross is over (lat, lon) now. */
    moveTo(lat, lon) {
      centre = { lat, lon };
      map.onMove();
    },
    count: (name) => calls.filter(([called]) => called === name).length,
  };
  return map;
}

/** One page's worth: the pin, its panel and dialog in the fake DOM, a fake map, the places `onChecked` was given. */
export function setup({ geolocation = null, view = SRI_MUDA_VIEW, getCoverage = async () => COVERAGE, centre } = {}) {
  const document = installPinDom();
  delete globalThis.navigator.geolocation;
  if (geolocation) Object.defineProperty(globalThis.navigator, "geolocation", { configurable: true, value: { getCurrentPosition: geolocation } });
  const parent = new PanelElement("section");
  const anchor = new PanelElement("div");
  anchor.rect = { top: 100, bottom: 500, height: 400 };
  parent.append(anchor);
  const map = fakeMap(anchor, centre);
  const checked = [];
  const squared = [];   // the squares that came with each checked place
  const pin = createPin({ map, anchor, area: { view }, getCoverage, onChecked: (place, squares) => { checked.push(place); squared.push(squares); } });
  const panel = parent.querySelector(".aim-panel");
  panel.rect = { top: 520, bottom: 700, height: 180 };
  const button = (label) => panel.querySelectorAll("button").find((found) => found.textContent === label);
  return {
    pin, map, anchor, document, panel, checked, squared, button,
    check: button("Check this spot"), locate: button("Use my location"),
    status: () => panel.querySelector('[role="status"]').textContent,
    alert: () => panel.querySelector('[role="alert"]').textContent,
    dialog: document.body.querySelector("dialog"),
    squares: parent.querySelector(".squares-status"),
    squaresSay: () => parent.querySelector(".squares-status").textContent,
  };
}

/** Starts aim mode and lets the coverage arrive, so the verdict for the cross is known. */
export async function aim(page, options = {}) {
  page.pin.start({ opener: page.document.activeElement, ...options });
  await flush();
}

export const choose = (page, label) => page.dialog.querySelectorAll("button").find((found) => found.textContent === label).click();

/** A press of "Use my location" as a person makes it: the button has focus, and the click knows its button. */
export function pressLocate(page) {
  page.locate.focus();
  page.locate.dispatch("click", { currentTarget: page.locate });
}
