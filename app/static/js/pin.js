// "Check any point": the flow behind the scope bar's button, the map's own button and "Move the pin". Aim mode puts a
// cross over the middle of the map, with a panel (a sheet over the tab bar on a phone). "Check this spot" snaps what is
// under the cross to its 90 m flood square here, sends only that square's centre (POST /api/point) and hands the Place
// back, with the flood squares around it that the same answer carries: that one request is all the flow sends, since a
// block asked for by its address would put the area in a URL. "Use my location" asks first, in a dialog, then moves the
// map to the fix; the fix itself never leaves the page.
import * as api from "./api.js";
import { squaresOf } from "./cells.js";
import { HELP_ID, createAimPanel, createGpsDialog, createSquaresStatus } from "./pin-panel.js";
import { WORDS, coverageWords, describe, fixCircle, gpsWords, isWideFix, pointRequest } from "./pin-words.js";
import { coverageAt, isPoint, isWithinView, parseRef } from "./place.js";

const AIM_ZOOM = 17;   // a 90 m square is about 75 px across here, so the cross sits on one square
const FIX_OPTIONS = { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 };   // a fresh fix, not one remembered
const IDLE = Object.freeze({ phase: "aiming", note: null, blocked: null, fix: null });
const TOP_CLEARANCE_PX = 56;     // the tab bar is sticky at the top of wide screens
const CROSS_CLEARANCE_PX = 24;   // room under the cross
const alertNote = (text) => ({ text, tone: "alert" });
const statusNote = (text) => ({ text, tone: "status" });

// What changes while the page runs is `ctx.state`, replaced whole (never edited) by setState:
//   aim      the model behind the panel (pin-words describe) while aiming, else null
//   opener   what had focus when aim mode began, for Cancel to give it back
//   turn     counts each check and each fix; one that is not the latest, or that comes after Cancel, is dropped
//   coverage GET /api/coverage once it is had
//   dropped  the id of the point on the map; squaresTurn counts the draws of its flood squares
//   refusals the words for each square the server has said it cannot check, by the square's id
const START = Object.freeze({
  aim: null, opener: null, turn: 0, coverage: null, dropped: null, squaresTurn: 0, refusals: Object.freeze({}),
});

const setState = (ctx, patch) => { ctx.state = { ...ctx.state, ...patch }; };

/** Change the model behind the panel and repaint it. Nothing to change when aim mode is over, as an answer may be late.
 *  A button that is turned off while it has focus loses it to the page, so the map, where the person goes on, takes it. */
function setAim(ctx, patch) {
  if (!ctx.state.aim) return;
  const aim = { ...ctx.state.aim, ...patch };
  const hadFocus = document.activeElement === ctx.panel.check;
  setState(ctx, { aim });
  ctx.panel.paint(describe(aim));
  if (hadFocus && ctx.panel.check.disabled) ctx.map.focusMap();
}

/** A live region says what changes once it is on show, so the first words of aim mode wait two frames, until the panel
 *  has been drawn. */
const whenShown = (callback) => requestAnimationFrame(() => requestAnimationFrame(callback));

const isCurrent = (ctx, turn) => ctx.state.aim !== null && ctx.state.turn === turn;

/** Starts a check or a fix: the panel waits (`phase`), and the number that tells this one's answer from an older one's. */
function begin(ctx, phase) {
  const turn = ctx.state.turn + 1;
  setState(ctx, { turn });
  setAim(ctx, { phase, note: null });
  return turn;
}

/** Back to waiting for the person, with `patch`, and say what can be said about the spot under the cross. */
function settle(ctx, patch) {
  setAim(ctx, { phase: "aiming", ...patch });
  refresh(ctx);
}

/** The flood model's coverage: the page's own copy once it has one, else asked for. Rejects when it cannot be had. */
async function ensureCoverage(ctx) {
  if (!ctx.state.coverage) setState(ctx, { coverage: await ctx.getCoverage() });
  return ctx.state.coverage;
}

/** Whether the spot under the cross can be checked, and if not why not, from the coverage the page holds. A square the
 *  server has already refused stays refused, so it is not asked again. */
function refresh(ctx) {
  const { aim, coverage } = ctx.state;
  if (!aim || !coverage) return;
  const here = ctx.map.aimCentre();
  const verdict = coverageAt(here.lat, here.lon, coverage);
  const refused = verdict.square ? ctx.state.refusals[verdict.square.id] : null;
  setAim(ctx, { blocked: verdict.coverage === "covered" ? refused ?? null : coverageWords(verdict) });
}

/** The person moved the map: what was said about the spot it was on is old. */
function onMove(ctx) {
  if (ctx.state.aim?.phase !== "aiming") return;
  setAim(ctx, { note: null });
  refresh(ctx);
}

/** Brings the cross into view, with the panel's last button, and not under the panel when that sticks to the screen
 *  over the map (on a phone). The tab bar is sticky at the top of wide screens, so the map must clear it. A panel that
 *  floats over the map's corner (a wide screen's map-first layout, a phone on its side) never covers the cross, so
 *  then only the map itself has to be on the screen. */
function keepCrossInView(ctx) {
  const map = ctx.anchor.getBoundingClientRect();
  const panel = ctx.panel.node.getBoundingClientRect();
  const crossBottom = map.top + map.height / 2 + CROSS_CLEARANCE_PX;
  const floats = globalThis.getComputedStyle?.(ctx.panel.node).position === "absolute";
  const isPanelInTheWay = floats ? map.bottom > window.innerHeight : panel.bottom > window.innerHeight || crossBottom > panel.top;
  if (map.top < TOP_CLEARANCE_PX || isPanelInTheWay) ctx.anchor.scrollIntoView({ block: "start" });
}

/** Aim mode begins. `opener` is what to give focus back to on Cancel; `at` (a Place) is where to put the cross, for
 *  "Move the pin". Focus goes to the map, so the arrow keys work at once; the panel's words are the map's description. */
function start(ctx, { opener = null, at = null } = {}) {
  if (ctx.state.aim) return ctx.map.focusMap();
  setState(ctx, { aim: IDLE, opener });
  ctx.map.enterAim({ onMove: () => onMove(ctx), describedBy: HELP_ID });
  document.addEventListener("keydown", ctx.onKey);
  ctx.panel.show();
  ctx.panel.paint(describe(IDLE));
  if (at) ctx.map.aimAt(at.lat, at.lon, AIM_ZOOM);
  ensureCoverage(ctx).then(
    () => whenShown(() => refresh(ctx)),
    (error) => whenShown(() => setAim(ctx, { note: alertNote(failureOf(error).failure) })),
  );
  keepCrossInView(ctx);
  return ctx.map.focusMap();
}

/** Aim mode ends, leaving focus where it is: after a check, or when the person has gone to another tab. */
function close(ctx) {
  if (!ctx.state.aim) return;
  setState(ctx, { aim: null, turn: ctx.state.turn + 1 });   // an answer still on its way is for nobody now
  document.removeEventListener("keydown", ctx.onKey);
  ctx.map.exitAim();
  ctx.panel.hide();
}

/** Cancel, or Escape: aim mode ends and focus goes back to what opened it, or to the map if that is not on show. */
function cancel(ctx) {
  const { opener } = ctx.state;
  close(ctx);
  if (opener?.isConnected && !opener.closest("[hidden]")) opener.focus();
  else ctx.map.focusMap();
}

/** Escape cancels, unless the dialog has it or it is closing a list in a field. Enter on the map itself checks the spot. */
function onKey(ctx, event) {
  if (event.defaultPrevented || ctx.dialog.isOpen) return;
  const inField = event.target instanceof Element && event.target.matches("input, select, textarea");
  if (event.key === "Escape" && !inField) cancel(ctx);
  else if (event.key === "Enter" && event.target === ctx.anchor) check(ctx);
}

// ---------- the check ----------

/** A point's Place the page can show: its id in the server's form, the corners of its square and its depths. A
 *  business, or anything else, is not one. */
const isUsable = (place) => isPoint(place) && parseRef(place.id)?.kind === "point"
  && Number.isFinite(place.lat) && Number.isFinite(place.lon) && typeof place.depth_m === "object" && place.depth_m !== null
  && typeof place.cell?.grid === "string" && place.cell.bounds?.length === 4 && place.cell.bounds.every(Number.isFinite);

/** The answer for the spot under the cross: {place, squares}, the squares that came with it (cells.js squaresOf; null
 *  when the answer has none, which does not make the point any less checked); or why it cannot be checked, as POST
 *  /api/point says it ({coverage, region}), with the square when the server was asked. A spot no loaded grid holds is
 *  answered here, and nothing is sent. Throws for anything the server's answer should not be. */
async function ask(ctx) {
  const here = ctx.map.aimCentre();   // where the cross is as the person asks, whatever it does while the coverage is awaited
  const coverage = await ensureCoverage(ctx);
  const verdict = coverageAt(here.lat, here.lon, coverage);
  if (verdict.coverage !== "covered") return verdict;
  const answer = await api.checkPoint(pointRequest(verdict.square, ctx.state.aim?.fix ?? null));
  if (answer === null || typeof answer !== "object") throw new Error("The flood model's answer was not an answer.");
  if (answer.coverage !== "covered") return { coverage: answer.coverage, region: answer.region, square: verdict.square };
  if (!isUsable(answer.place)) throw new Error("The flood model's answer was not a point.");
  return { place: answer.place, squares: squaresOf(answer) };
}

/** What to say after a check that gave no place: the failure, or the sentence for the answer. */
const noteFor = (outcome) => (outcome.failure ? alertNote(outcome.failure) : statusNote(coverageWords(outcome)));

/** The words for a check that failed: the server's own (too many checks, say) or that it could not be reached, as
 *  api.js has them; an answer the page cannot use is a failure to read the model. */
const failureOf = (error) => ({ failure: error instanceof api.ApiError ? error.message : WORDS.readFailed });

/** A square the server has refused stays refused, so it is not asked again: it would give the same answer. */
function rememberRefusal(ctx, { square, ...answer }) {
  setState(ctx, { refusals: { ...ctx.state.refusals, [square.id]: coverageWords(answer) } });
}

async function check(ctx) {
  if (ctx.state.aim?.phase !== "aiming" || ctx.panel.check.disabled) return;
  const turn = begin(ctx, "checking");
  const outcome = await ask(ctx).catch(failureOf);
  if (!isCurrent(ctx, turn)) return;
  if (outcome?.place) {
    close(ctx);              // the cross and the panel go; the pin takes over
    ctx.onChecked(outcome.place, outcome.squares);
  } else {
    if (outcome?.square) rememberRefusal(ctx, outcome);
    settle(ctx, { note: noteFor(outcome) });
  }
}

// ---------- the location ----------

/** After a fix focus goes to what comes next, unless the person has gone elsewhere: the button to check, or the map. */
function focusAfterFix(ctx) {
  const active = document.activeElement;
  if (active !== document.body && !ctx.panel.contains(active)) return;
  if (ctx.panel.check.disabled) ctx.map.focusMap();
  else ctx.panel.check.focus();
}

/** The note for a fix: it is not on the map at all (outside Malaysia), or too wide to say which square, or fine. The
 *  first is about somewhere the cross is not, so it turns the check off until the map is moved. */
function fixNote(isOnMap, isWide) {
  if (!isOnMap) return { ...statusNote(coverageWords({ coverage: "outside", region: null })), blocks: true };
  return isWide ? statusNote(WORDS.wideFix) : null;
}

/** A fix: the cross goes to it at street level. Its accuracy shows as a circle when it is worse than a square. */
function onFix(ctx, { coords }) {
  const { latitude: lat, longitude: lon, accuracy } = coords;
  const isOnMap = ctx.map.aimAt(lat, lon, AIM_ZOOM);
  ctx.map.showAccuracy(isOnMap ? fixCircle(lat, lon, accuracy) : null);   // the last fix's circle goes, whatever this one is
  const { coverage } = ctx.state;
  const fix = isOnMap && coverage ? coverageAt(lat, lon, coverage).square?.id ?? null : null;
  settle(ctx, { fix, note: fixNote(isOnMap, isWideFix(accuracy)) });
  focusAfterFix(ctx);
}

function locate(ctx) {
  const turn = begin(ctx, "locating");
  const unlessStale = (handle) => (arg) => { if (isCurrent(ctx, turn)) handle(arg); };
  const failed = unlessStale((error) => settle(ctx, { note: alertNote(gpsWords(error)) }));
  if (!navigator.geolocation) return failed({});
  return navigator.geolocation.getCurrentPosition(unlessStale((position) => onFix(ctx, position)), failed, FIX_OPTIONS);
}

/** "Use my location": the dialog first; the browser's own permission prompt comes only after "Share my location". */
async function askToLocate(ctx, opener) {
  if (ctx.state.aim?.phase !== "aiming") return;
  const shared = await ctx.dialog.open(opener);
  if (shared && ctx.state.aim?.phase === "aiming") locate(ctx);
}

// ---------- the pin and the squares around it ----------

/** Draws the flood squares that came with a point, unless the area's own squares are already on the map there, and says
 *  how it went under the map: none near, or failed. The squares are in hand, so all that can fail here is the grid's
 *  square size, which the coverage gives (with Retry); the server may have said it could not read them (squares
 *  SQUARES_FAILED: no Retry, as asking again reads the same file). A point that came with no squares draws none and
 *  says nothing. */
async function drawSquares(ctx, place, squares) {
  const turn = ctx.state.squaresTurn + 1;
  setState(ctx, { squaresTurn: turn });
  const isLatest = () => ctx.state.squaresTurn === turn;   // a later point has its own squares to say about
  if (!squares || isWithinView(place.lat, place.lon, ctx.area.view)) {
    ctx.squares.clear();
    return;
  }
  if (squares.failed) {
    ctx.squares.fail(WORDS.squaresFailed);
    return;
  }
  try {
    const coverage = await ensureCoverage(ctx);
    const grid = coverage.grids.find((entry) => entry.name === place.cell.grid);
    if (!grid) throw new Error("That grid is not loaded.");
    if (!isLatest()) return;
    const wet = ctx.map.showSquares(grid, squares.blocks, squares.cells);
    if (wet > 0) ctx.squares.clear();
    else ctx.squares.say(WORDS.squaresNone);
  } catch {
    if (isLatest()) ctx.squares.fail(WORDS.squaresFailed, () => drawSquares(ctx, place, squares));
  }
}

/** The pin goes on a point's square, once, with the squares that came with it. */
function drop(ctx, place, squares) {
  if (ctx.state.dropped === place.id) return;
  setState(ctx, { dropped: place.id });
  ctx.map.showPoint(place);
  drawSquares(ctx, place, squares);
}

/** Called with every state of the page: aim mode ends when the Area overview does, and a point that is the selected
 *  place, however it came (a check, a link, "Move the pin"), gets its pin, with `squares` (the ones that came with it,
 *  or none) around it. */
function render(ctx, { tab, place, squares = null }) {
  if (tab !== "overview") close(ctx);
  if (isUsable(place)) drop(ctx, place, squares);
}

/** On a phone the panel is a sheet over the page, above the tab bar. That bar is taller when its labels wrap on a
 *  narrow screen, so its height is measured, not assumed: views.css has 64 px and the safe area for when it cannot be. */
function sitAboveTabBar(panel, tabBar) {
  if (!tabBar || !window.ResizeObserver) return;
  new ResizeObserver(() => panel.node.style.setProperty("--tab-bar-h", `${tabBar.offsetHeight}px`)).observe(tabBar);
}

/** `map` is the map handle (map.js), `anchor` its element, `area` the page's area config (its `view`), `tabBar` the
 *  bar of tabs, getCoverage() resolves GET /api/coverage (asking again if the first try failed, and rejecting if it
 *  fails again), and onChecked(place, squares) is for a Place the server has checked, with the flood squares that came
 *  in the same answer ({blocks, cells}, or null): the page shows the place on My business, and hands both back to
 *  render() with every state, so the pin and the squares follow the selected place. */
export function createPin({ map, anchor, area, tabBar = null, getCoverage, onChecked }) {
  const ctx = { map, anchor, area, getCoverage, onChecked, state: START };
  ctx.panel = createAimPanel({
    onCheck: () => check(ctx), onCancel: () => cancel(ctx), onLocate: (opener) => askToLocate(ctx, opener),
    canLocate: "geolocation" in navigator,
  });
  ctx.dialog = createGpsDialog();
  ctx.squares = createSquaresStatus();
  ctx.onKey = (event) => onKey(ctx, event);
  anchor.after(ctx.panel.node, ctx.squares.node);
  document.body.append(ctx.dialog.node);
  sitAboveTabBar(ctx.panel, tabBar);
  return {
    start: (options) => start(ctx, options),
    close: () => close(ctx),
    render: (view) => render(ctx, view),
  };
}
