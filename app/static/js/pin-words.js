// "Check any point", section UI-A of the plan: its words, and the pure rules that choose between them, with no DOM so
// node can test them (tests/pin.test.mjs). The panel and the dialog that show them are in pin-panel.js, the flow in pin.js.

/** Every sentence of the flow, as the plan has it. */
export const WORDS = Object.freeze({
  heading: "Check a point",
  help: "Move the map until the cross sits on your premises. With a keyboard, select the map and use the arrow keys.",
  check: "Check this spot",
  locate: "Use my location",
  cancel: "Cancel",
  busy: "Reading the flood model…",
  finding: "Finding your location…",
  readFailed: "Could not read the flood model just now. Try again.",
  wideFix: "Move the cross to your premises before you check.",
  gpsBlocked: "Location is blocked for this page. Move the map to your premises instead.",
  gpsLost: "Your location could not be found. Try again, or move the map to your premises.",
  dialogTitle: "Use your location once?",
  // each claim is held by a test: tests/test_place_ai.py (Gemini and Google Weather), tests/pin.test.mjs (300 m)
  dialogBody: "This page rounds it to the 90 m flood square you are in, and only that square is sent to our server. We do not keep it. The square appears in this page's link, after the #. The map then moves there, so OpenStreetMap's map servers see where you are to within about 300 m. The AI assistant gets the area's name, the flood depths and the nearest relief centre with its distance, never your coordinates. If you ask it about rain, Google Weather gets no more than your square rounded to about 1 km.",
  share: "Share my location",
  notNow: "Not now",
  squaresNone: "No flood squares near this point in the model",
  squaresFailed: "Flood squares could not load.",
  retry: "Retry",
});

const OUTSIDE_WORDS = "This spot is outside Malaysia. Banjir Check covers Malaysia only.";
const NOT_LOADED_WORDS = {   // by region id, as GET /api/coverage names them
  borneo: "Sabah and Sarawak are not in this build yet.",
  langkawi: "Langkawi is not covered yet.",
  peninsula: "This spot is outside the flood model files in this build.",
};
const FILES_WORDS = NOT_LOADED_WORDS.peninsula;   // for a region this build has no sentence for
const PERMISSION_DENIED = 1;   // GeolocationPositionError.code: the page is not allowed to ask. 2 and 3 are "no fix".
const SQUARE_M = 90;           // a fix wider than one flood square cannot tell which square the person is in

/** The sentence for an answer of POST /api/point (or the page's own coverageAt): why a spot cannot be checked, or ""
 *  for a spot that can. */
export function coverageWords({ coverage, region }) {
  if (coverage === "covered") return "";
  if (coverage === "outside") return OUTSIDE_WORDS;
  return NOT_LOADED_WORDS[region] ?? FILES_WORDS;
}

/** The sentence for a failed location request: blocked for the page, or no fix (not found, timed out, or no GPS). */
export const gpsWords = (error) => (error?.code === PERMISSION_DENIED ? WORDS.gpsBlocked : WORDS.gpsLost);

/** A fix is wide when its accuracy is worse than one square, or is not a number at all. */
export const isWideFix = (accuracy) => !(accuracy <= SQUARE_M);

/** The circle to show for a fix: its place and accuracy in metres when it is wide, else null (nothing to show, or no
 *  radius to draw it with). */
export const fixCircle = (lat, lon, accuracy) => (isWideFix(accuracy) && Number.isFinite(accuracy) ? { lat, lon, metres: accuracy } : null);

/** What the aim panel shows for its model {phase: "aiming" | "checking" | "locating", note, blocked, fix}:
 *   text, tone  the one message: "alert" for an error, "status" for a result or a wait; "" when there is none;
 *   check       "ready", "blocked" (this spot cannot be checked: the button is off and the reason is the message) or "busy";
 *   locate      "ready" or "busy".
 *  A wait is always what is said. Otherwise a note (an error, a server answer, the fix hint) comes before the
 *  reason a spot is blocked, which comes back as soon as the note is cleared by a move of the map. A note with
 *  `blocks` turns the check off as well, until that move: it is about somewhere the cross is not. */
export function describe({ phase, note, blocked }) {
  if (phase === "checking") return { text: WORDS.busy, tone: "status", check: "busy", locate: "busy" };
  if (phase === "locating") return { text: WORDS.finding, tone: "status", check: "busy", locate: "busy" };
  const shown = note ?? (blocked ? { text: blocked, tone: "status" } : null);
  const isOff = Boolean(blocked) || note?.blocks === true;
  return { text: shown?.text ?? "", tone: shown?.tone ?? "status", check: isOff ? "blocked" : "ready", locate: "ready" };
}

/** The body of POST /api/point: the centre of the snapped square and where it came from, nothing else. The point a
 *  person gave (a pin under the cross, or a GPS fix) never leaves the page: only the 90 m square holding it does. A
 *  square is a GPS point only while it is the one the fix fell in (fixId); once the cross has moved it is a pin. */
export const pointRequest = (square, fixId) => ({ lat: square.lat, lon: square.lon, source: square.id === fixId ? "gps" : "pin" });
