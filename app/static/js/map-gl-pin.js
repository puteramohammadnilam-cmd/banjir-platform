// "Check a point" on the new map (map.html): the pin button, or "Move the pin" on a point's card, puts the map in pin
// mode, with a cross over the map and the main page's aim panel (pin-panel.js) in the place card. A tap on the map checks
// that spot; "Check this spot", or Enter on the map, checks the spot under the cross, which the arrow keys move. As on
// the main page (pin.js), only the centre of the 90 m flood square holding the spot is sent (POST /api/point, never in a
// URL), and "Use my location" asks first in a dialog; the fix itself never leaves the page.
import * as api from "./api.js";
import { squaresOf } from "./cells.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { createAimPanel, createGpsDialog } from "./pin-panel.js";
import { WORDS, coverageWords, describe, gpsWords, isWideFix, pointRequest } from "./pin-words.js";
import { coverageAt, isPoint, parseRef, snapToGrid } from "./place.js";

const AIM_ZOOM = 17;   // a 90 m square is about 75 px across here, so the cross sits on one square
const FIX_OPTIONS = { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 };   // a fresh fix, not one remembered
const IDLE = Object.freeze({ phase: "aiming", note: null, blocked: null });
const alertNote = (text) => ({ text, tone: "alert" });
const statusNote = (text) => ({ text, tone: "status" });
const failureNote = (error) => alertNote(error instanceof api.ApiError ? error.message : WORDS.readFailed);

/** A point's Place the map can show: its id in the server's form, its centre, its depths and its square's corners. */
export const isUsablePoint = (place) => isPoint(place) && parseRef(place.id)?.kind === "point"
  && Number.isFinite(place.lat) && Number.isFinite(place.lon) && typeof place.depth_m === "object" && place.depth_m !== null
  && place.cell?.bounds?.length === 4 && place.cell.bounds.every(Number.isFinite);

/** `map()` gives the map, `cross` the element drawn over its centre. show(node) puts the aim panel in the place card and
 *  hide() ends it (Cancel, Escape); onPlace(place, squares) gets a point the server has checked, with the squares that
 *  came with it (cells.js squaresOf); onModeChange() is told when pin mode starts or stops (the map's cursor). */
export function createPinMode({ map, cross, show, hide, onPlace, onModeChange = () => {} }) {
  const st = { aim: null, turn: 0, fix: null, coverage: null, panel: null, wasCooperative: false };
  const dialog = createGpsDialog();
  document.body.append(dialog.node);
  const coverage = () => {
    st.coverage ??= api.getCoverage().catch((error) => {
      st.coverage = null;   // asked again next time
      throw error;
    });
    return st.coverage;
  };
  const paint = (patch) => {
    if (!st.aim) return;
    st.aim = { ...st.aim, ...patch };
    st.panel.paint(describe(st.aim));
  };
  const centre = () => {
    const { lat, lng } = map().getCenter();
    return { lat, lon: lng };
  };
  const placeCross = () => {
    const { x, y } = map().project(map().getCenter());
    cross.style.transform = `translate(${x}px, ${y}px)`;
  };
  /** Whether the spot under the cross can be checked, said before the button is pressed. */
  const refresh = async () => {
    try {
      const verdict = coverageAt(centre().lat, centre().lon, await coverage());
      if (st.aim?.phase === "aiming") paint({ blocked: verdict.coverage === "covered" ? null : coverageWords(verdict) });
    } catch (error) {
      if (st.aim?.phase === "aiming") paint({ note: failureNote(error) });
    }
  };
  const onMoveEnd = () => {
    if (st.aim?.phase !== "aiming") return;
    paint({ note: null });
    refresh();
  };

  /** Checks the square holding `at`; `isFix` says `at` is the person's own location, so the server is told it was GPS. */
  async function check(at, { isFix = false } = {}) {
    if (st.aim?.phase !== "aiming") return;
    const turn = ++st.turn;
    const isLatest = () => st.aim !== null && st.turn === turn;
    paint({ phase: "checking", note: null });
    try {
      const verdict = coverageAt(at.lat, at.lon, await coverage());
      if (isFix) st.fix = verdict.square?.id ?? null;
      const answer = verdict.coverage === "covered" ? await api.checkPoint(pointRequest(verdict.square, st.fix)) : verdict;
      if (!isLatest()) return;
      if (answer === null || typeof answer !== "object") throw new Error(WORDS.readFailed);
      if (answer.coverage !== "covered") return paint({ phase: "aiming", note: statusNote(coverageWords(answer)) });
      if (!isUsablePoint(answer.place)) throw new Error(WORDS.readFailed);
      stop();
      onPlace(answer.place, squaresOf(answer));
    } catch (error) {
      if (isLatest()) paint({ phase: "aiming", note: failureNote(error) });
    }
  }

  /** A fix: the map goes to it at street level and checks it, unless it is too wide to say which square. */
  function onFix(turn, { coords }) {
    if (!st.aim || st.turn !== turn) return;
    const { latitude: lat, longitude: lon, accuracy } = coords;
    map().jumpTo({ center: [lon, lat], zoom: Math.max(map().getZoom(), AIM_ZOOM) });   // at once, so its moveend comes first
    paint({ phase: "aiming" });
    if (!isWideFix(accuracy)) return check({ lat, lon }, { isFix: true });
    coverage().then((found) => { st.fix = coverageAt(lat, lon, found).square?.id ?? null; }, () => {});
    paint({ note: statusNote(WORDS.wideFix) });
    return refresh();   // the jump came while locating, so its moveend said nothing about the new spot
  }

  /** "Use my location": the dialog first; the browser's own permission prompt comes only after "Share my location". */
  async function locate(opener) {
    if (st.aim?.phase !== "aiming" || !(await dialog.open(opener)) || st.aim?.phase !== "aiming") return;
    const turn = ++st.turn;
    paint({ phase: "locating", note: null });
    const failed = (error) => {
      if (st.aim && st.turn === turn) paint({ phase: "aiming", note: alertNote(gpsWords(error)) });
    };
    if (!navigator.geolocation) return failed({});
    return navigator.geolocation.getCurrentPosition((position) => onFix(turn, position), failed, FIX_OPTIONS);
  }

  /** Pin mode ends; the card is the caller's to close. */
  function stop() {
    if (!st.aim) return;
    st.aim = null;
    st.turn += 1;   // an answer still on its way is for nobody now
    cross.hidden = true;
    map().off("move", placeCross);
    map().off("moveend", onMoveEnd);
    if (st.wasCooperative) map().cooperativeGestures.enable();
    onModeChange();
  }

  function cancel() {
    stop();
    hide();
  }

  /** Pin mode begins, at `at` ({lat, lon}) for "Move the pin". The map takes focus, so the arrow keys work at once. */
  function start({ at = null } = {}) {
    if (st.aim) return;
    st.aim = IDLE;
    st.fix = null;
    st.panel = createAimPanel({ onCheck: () => check(centre()), onCancel: cancel, onLocate: locate, canLocate: "geolocation" in navigator });
    st.panel.node.querySelector(".aim-help")?.after(h("p", { class: "aim-help" }, t("mg.pinTap")));
    st.panel.show();   // on show before show(): a phone measures the sheet to lift the cross clear of it
    st.panel.paint(describe(st.aim));
    if (at) map().jumpTo({ center: [at.lon, at.lat], zoom: Math.max(map().getZoom(), AIM_ZOOM) });
    show(st.panel.node);
    // one finger moves the map while aiming, as on the main page; two again afterwards
    st.wasCooperative = map().cooperativeGestures?.isEnabled() ?? false;
    if (st.wasCooperative) map().cooperativeGestures.disable();
    cross.hidden = false;
    placeCross();
    map().on("move", placeCross);
    map().on("moveend", onMoveEnd);
    onModeChange();
    refresh();
    map().getCanvas().focus({ preventScroll: true });
  }

  /** The point a link names, checked again (POST /api/point, snapped here first): {place, squares}, or null. */
  async function linked(ref) {
    const parsed = parseRef(ref);
    if (parsed?.kind !== "point") return null;
    const square = snapToGrid(parsed.lat, parsed.lon, (await coverage()).grids);
    if (!square) return null;
    const answer = await api.checkPoint({ lat: square.lat, lon: square.lon, source: "pin" });
    return answer?.coverage === "covered" && isUsablePoint(answer.place) ? { place: answer.place, squares: squaresOf(answer) } : null;
  }

  return {
    start, stop, cancel, linked,
    isOn: () => st.aim !== null,
    isAsking: () => dialog.isOpen,
    tap: ({ lat, lng }) => check({ lat, lon: lng }),
    checkCentre: () => check(centre()),
  };
}
