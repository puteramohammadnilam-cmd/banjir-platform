// Run from 11_Platform_Draft:  node --test tests/pin.test.mjs
// The pure rules of "Check any point" (plan card A7, section UI-A): the words, what the page knows about a spot before it
// asks the server, the model behind the aim panel, the body of POST /api/point, and which flood squares stay on the map.
// The panel, the dialog and the map itself are checked in the browser (checklist 6A).
import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_NEIGHBOURHOODS, addNeighbourhood, neighbourhoodId } from "../app/static/js/cells.js";
import { WORDS, coverageWords, describe, fixCircle, gpsWords, isWideFix, pointRequest } from "../app/static/js/pin-words.js";
import { coverageAt, isWithinView, overlapsView, regionAt, snapToGrid } from "../app/static/js/place.js";

// GET /api/coverage, as the server sends it for the shipped files.
const E100 = { name: "N10_E100", x0: 99.97625154437965, y0: 10.00706666666666, px: 0.0008333333356347339, py: 0.0008333333333325754, rows: 11999, cols: 11999 };
const REGIONS = [
  { id: "langkawi", box: [99.55, 6.1, 99.97, 6.55] },
  { id: "peninsula", box: [99.5, 1.15, 104.7, 6.8] },
  { id: "borneo", box: [109.5, 0.8, 119.4, 7.5] },
];
const COVERAGE = { data_version: "a5486e860339", return_periods: [10, 20, 50], block_cells: 24, grids: [E100], regions: REGIONS };

// ---------- where a spot lies ----------

test("a spot lies in the first region box that holds it, edges included, as app/places.py region_at says", () => {
  assert.equal(regionAt(3.1478, 101.6953, REGIONS), "peninsula");
  assert.equal(regionAt(1.5535, 110.3593, REGIONS), "borneo");
  assert.equal(regionAt(6.33, 99.84, REGIONS), "langkawi", "Kuah is in the Langkawi box, which comes before the Peninsula's");
  assert.equal(regionAt(6.7, 99.84, REGIONS), "peninsula", "north of the Langkawi box, still in the Peninsula's");
  assert.equal(regionAt(1.15, 99.5, REGIONS), "peninsula", "a corner counts");
  assert.equal(regionAt(6.8, 104.7, REGIONS), "peninsula");
  assert.equal(regionAt(35.68, 139.69, REGIONS), null);
  assert.equal(regionAt(1.14999, 101, REGIONS), null);
});

test("a region lookup gives nothing for input that is not a number or boxes that are not there", () => {
  for (const [lat, lon] of [[NaN, 101], [3, NaN], ["3", "101"], [null, 101], [undefined, undefined]]) {
    assert.equal(regionAt(lat, lon, REGIONS), null, `${lat}, ${lon}`);
  }
  assert.equal(regionAt(3, 101, undefined), null);
  assert.equal(regionAt(3, 101, []), null);
  assert.equal(regionAt(3, 101, [{ id: "broken" }, { id: "short", box: [1, 2] }]), null);
});

// ---------- what the page knows before it asks ----------

test("a spot a loaded grid holds is checked: the page snaps it, and the server then has the last word", () => {
  const kl = coverageAt(3.1478, 101.6953, COVERAGE);
  assert.equal(kl.coverage, "covered");
  assert.equal(kl.square.id, "pt:3.14748,101.69500");
  assert.deepEqual(kl.square, snapToGrid(3.1478, 101.6953, [E100]));
  const sriMuda = coverageAt(3.0297599, 101.5364982, COVERAGE);
  assert.equal(sriMuda.square.id, "pt:3.02998,101.53667");
});

test("a spot no grid holds is named by its region, with no square, so nothing is sent for it", () => {
  const cases = [
    [1.5535, 110.3593, "not_loaded", "borneo"],     // Kuching: Sarawak is not in the E100 files
    [6.33, 99.84, "not_loaded", "langkawi"],        // Kuah: Langkawi needs the E090 tile
    [3.0, 99.7, "not_loaded", "peninsula"],         // inside the Peninsula's box, west of the files
    [35.68, 139.69, "outside", null],               // Tokyo
    [51.5, -0.12, "outside", null],
  ];
  for (const [lat, lon, coverage, region] of cases) {
    const verdict = coverageAt(lat, lon, COVERAGE);
    assert.deepEqual({ coverage: verdict.coverage, region: verdict.region }, { coverage, region }, `${lat}, ${lon}`);
    assert.equal("square" in verdict, false, `${lat}, ${lon} has no square`);
  }
});

test("a spot that is not a number is outside, and a page with no coverage cannot say anything is covered", () => {
  assert.equal(coverageAt(NaN, 101.5, COVERAGE).coverage, "outside");
  assert.equal(coverageAt(3.0297599, 101.5364982, null).coverage, "outside");
  assert.equal(coverageAt(3.0297599, 101.5364982, { grids: [], regions: [] }).coverage, "outside");
});

// ---------- the words ----------

test("each coverage answer has the plan's one sentence", () => {
  assert.equal(coverageWords({ coverage: "outside", region: null }), "This spot is outside Malaysia. MyFlood covers Malaysia only.");
  assert.equal(coverageWords({ coverage: "not_loaded", region: "borneo" }), "Sabah and Sarawak are not in this build yet.");
  assert.equal(coverageWords({ coverage: "not_loaded", region: "langkawi" }), "Langkawi is not covered yet.");
  assert.equal(coverageWords({ coverage: "not_loaded", region: "peninsula" }), "This spot is outside the flood model files in this build.");
});

test("a region this build does not know, and an answer it does not know, fall back to the files sentence; covered says nothing", () => {
  assert.equal(coverageWords({ coverage: "not_loaded", region: "sumatra" }), "This spot is outside the flood model files in this build.");
  assert.equal(coverageWords({ coverage: "not_loaded", region: null }), "This spot is outside the flood model files in this build.");
  assert.equal(coverageWords({ coverage: "covered", region: "peninsula" }), "");
});

test("the copy is the plan's, word for word", () => {
  assert.deepEqual({ ...WORDS }, {
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
    dialogBody: "This page rounds it to the 90 m flood square you are in, and only that square is sent to our server. We do not keep it. The square appears in this page's link, after the #. The map then moves there, so OpenStreetMap's map servers see where you are to within about 300 m. The AI assistant gets the area's name, the flood depths and the nearest relief centre with its distance, never your coordinates. If you ask it about rain, Google Weather gets no more than your square rounded to about 1 km.",
    share: "Share my location",
    notNow: "Not now",
    squaresNone: "No flood squares near this point in the model",
    squaresFailed: "Flood squares could not load.",
    retry: "Retry",
  });

test("the dialog's 300 m is one map tile at the zoom a fix is shown at (17, tests/pin_flow.test.mjs), across Malaysia", () => {
  const EQUATOR_M = 40_075_016.686;   // OpenStreetMap's tiles split the equator into 2^zoom
  for (const lat of [0.8, 3.1, 7.5]) {
    const metres = (EQUATOR_M * Math.cos((lat * Math.PI) / 180)) / 2 ** 17;
    assert.ok(metres > 295 && metres < 310, `${lat}: ${metres}`);
  }
  assert.match(WORDS.dialogBody, /within about 300 m/);
});
});

test("a location that is blocked is told apart from one that could not be found", () => {
  assert.equal(gpsWords({ code: 1 }), "Location is blocked for this page. Move the map to your premises instead.");
  assert.equal(gpsWords({ code: 2 }), "Your location could not be found. Try again, or move the map to your premises.");
  assert.equal(gpsWords({ code: 3 }), "Your location could not be found. Try again, or move the map to your premises.");
  for (const odd of [undefined, null, {}, { code: 99 }, new Error("x")]) {
    assert.equal(gpsWords(odd), "Your location could not be found. Try again, or move the map to your premises.");
  }
});

test("a fix is too wide to trust when it is worse than one 90 m square", () => {
  assert.equal(isWideFix(5), false);
  assert.equal(isWideFix(90), false);
  assert.equal(isWideFix(90.01), true);
  assert.equal(isWideFix(1500), true);
  assert.equal(isWideFix(NaN), true, "an accuracy that is not a number is not a good one");
  assert.equal(isWideFix(undefined), true);
});

test("a circle is drawn only for a fix that is wide, and only when its accuracy is a number of metres", () => {
  assert.deepEqual(fixCircle(3.1, 101.7, 450), { lat: 3.1, lon: 101.7, metres: 450 });
  assert.equal(fixCircle(3.1, 101.7, 90), null, "a fix of one square needs no circle");
  assert.equal(fixCircle(3.1, 101.7, 12), null);
  for (const odd of [NaN, undefined, null, Infinity]) assert.equal(fixCircle(3.1, 101.7, odd), null, String(odd));
});

// ---------- what the panel shows ----------

const AIM = { phase: "aiming", note: null, blocked: null, fix: null };

test("an idle panel says nothing and lets both actions through", () => {
  assert.deepEqual(describe(AIM), { text: "", tone: "status", check: "ready", locate: "ready" });
});

test("over a spot that cannot be checked the button is off and the reason is shown, politely", () => {
  const view = describe({ ...AIM, blocked: "Sabah and Sarawak are not in this build yet." });
  assert.deepEqual(view, { text: "Sabah and Sarawak are not in this build yet.", tone: "status", check: "blocked", locate: "ready" });
});

test("while the server is asked the button is busy and the wait is said", () => {
  assert.deepEqual(describe({ ...AIM, phase: "checking" }), { text: "Reading the flood model…", tone: "status", check: "busy", locate: "busy" });
});

test("while the location is found the buttons are busy and the wait is said", () => {
  assert.deepEqual(describe({ ...AIM, phase: "locating" }), { text: "Finding your location…", tone: "status", check: "busy", locate: "busy" });
});

test("an error is an alert and a result is a status, and a note comes before the reason for a blocked button", () => {
  const failed = { text: WORDS.readFailed, tone: "alert" };
  assert.deepEqual(describe({ ...AIM, note: failed }), { text: WORDS.readFailed, tone: "alert", check: "ready", locate: "ready" });
  const hint = { text: WORDS.wideFix, tone: "status" };
  assert.deepEqual(describe({ ...AIM, note: hint, blocked: "Langkawi is not covered yet." }),
    { text: WORDS.wideFix, tone: "status", check: "blocked", locate: "ready" });
});

test("a note that blocks turns the check off, in its own words, until the note is cleared", () => {
  const blocking = { text: "This spot is outside Malaysia. MyFlood covers Malaysia only.", tone: "status", blocks: true };
  assert.deepEqual(describe({ ...AIM, note: blocking }), { text: blocking.text, tone: "status", check: "blocked", locate: "ready" });
  assert.deepEqual(describe({ ...AIM, note: { ...blocking, blocks: false } }).check, "ready");
  assert.deepEqual(describe({ ...AIM, note: null }).check, "ready");
});

test("busy beats a note and a blocked reason, so the wait is always what is said", () => {
  const busy = describe({ phase: "checking", note: { text: "old", tone: "alert" }, blocked: "why", fix: null });
  assert.equal(busy.text, WORDS.busy);
  assert.equal(busy.tone, "status");
});

// ---------- what is sent ----------

test("only the snapped square's centre is sent, with where it came from, and never the point that was given", () => {
  const raw = [3.0297599, 101.5364982];
  const square = snapToGrid(...raw, [E100]);
  const body = pointRequest(square, null);
  assert.deepEqual(Object.keys(body).sort(), ["lat", "lon", "source"]);
  assert.deepEqual(body, { lat: square.lat, lon: square.lon, source: "pin" });
  assert.notEqual(body.lat, raw[0]);
  assert.notEqual(body.lon, raw[1]);
  assert.ok(Math.abs(body.lat - raw[0]) < 0.0005 && Math.abs(body.lon - raw[1]) < 0.0005, "the centre is within the same 90 m square");
});

test("a square is a GPS point only while it is the square the fix fell in", () => {
  const fix = snapToGrid(3.1478, 101.6953, [E100]);
  const moved = snapToGrid(3.2, 101.7, [E100]);
  assert.equal(pointRequest(fix, fix.id).source, "gps");
  assert.equal(pointRequest(moved, fix.id).source, "pin");
  assert.equal(pointRequest(fix, null).source, "pin");
});

test("no spot anywhere puts a coordinate that is not a square centre into the body", () => {
  for (let i = 0; i < 400; i += 1) {
    const lat = 1.2 + ((i * 7919) % 5500) / 1000;
    const lon = 100 + ((i * 104729) % 9500) / 1000;
    const verdict = coverageAt(lat, lon, COVERAGE);
    if (verdict.coverage !== "covered") continue;
    const body = pointRequest(verdict.square, null);
    assert.deepEqual(snapToGrid(body.lat, body.lon, [E100]).id, verdict.square.id, "the body snaps back to the same square");
    assert.equal(body.lat, verdict.square.lat);
    assert.equal(body.lon, verdict.square.lon);
  }
});

// ---------- the area's own view ----------

test("a point inside an area's view needs no squares of its own: the area's are drawn already", () => {
  const view = [101.515, 3.008, 101.55, 3.042];   // Taman Sri Muda
  assert.equal(isWithinView(3.02998, 101.53667, view), true);
  assert.equal(isWithinView(3.008, 101.515, view), true, "the edge counts");
  assert.equal(isWithinView(3.14748, 101.695, view), false);
  assert.equal(isWithinView(3.02998, 101.5501, view), false);
  assert.equal(isWithinView(3.02998, 101.53667, null), false);
  assert.equal(isWithinView(NaN, 101.53667, view), false);
});

test("a square the area's own squares already draw is one that overlaps the area's view, and no other", () => {
  const view = [101.515, 3.008, 101.55, 3.042];   // Taman Sri Muda: [west, south, east, north]
  const size = { px: 0.0008333333356347339, py: 0.0008333333333325754 };
  assert.equal(overlapsView(view, 3.02, 101.53, size), true, "inside");
  assert.equal(overlapsView(view, 3.0415, 101.549, size), true, "straddling the north-east corner: the area draws it");
  assert.equal(overlapsView(view, 3.0079, 101.514585, size), true, "the south-west corner square, as town.json holds it");
  assert.equal(overlapsView(view, 3.0425, 101.53, size), false, "just north of the view");
  assert.equal(overlapsView(view, 3.02, 101.5505, size), false, "just east of it");
  assert.equal(overlapsView(view, 3.008 - size.py, 101.53, size), false, "touching the south edge from outside is not overlapping");
  assert.equal(overlapsView(view, 3.02, 101.515 - size.px, size), false, "touching the west edge from outside");
  assert.equal(overlapsView(view, 3.14748, 101.695, size), false, "Kuala Lumpur");
  assert.equal(overlapsView(null, 3.02, 101.53, size), false, "an area with no view owns nothing");
  assert.equal(overlapsView(view, NaN, 101.53, size), false);
});

// ---------- the flood squares kept on the map ----------

const keys = (...names) => names.map((name) => `g:${name}`);

test("at most four neighbourhoods stay, and the oldest goes first", () => {
  assert.equal(MAX_NEIGHBOURHOODS, 4);
  let ledger = [];
  const dropped = [];
  for (const id of ["a", "b", "c", "d", "e", "f"]) {
    const step = addNeighbourhood(ledger, id, keys(`${id}1`, `${id}2`));
    ledger = step.ledger;
    dropped.push(step.stale);
  }
  assert.deepEqual(ledger.map((n) => n.id), ["c", "d", "e", "f"]);
  assert.deepEqual(dropped, [[], [], [], [], keys("a1", "a2"), keys("b1", "b2")]);
});

test("a square two neighbourhoods share is drawn once and kept until both are gone", () => {
  const first = addNeighbourhood([], "a", keys("s1", "s2", "s3"));
  assert.deepEqual(first.fresh, keys("s1", "s2", "s3"));
  const second = addNeighbourhood(first.ledger, "b", keys("s3", "s4"));
  assert.deepEqual(second.fresh, keys("s4"), "s3 is on the map already");
  const third = addNeighbourhood(second.ledger, "c", keys("s5"), 2);
  assert.deepEqual(third.stale, keys("s1", "s2"), "s3 stays: b still holds it");
  const fourth = addNeighbourhood(third.ledger, "d", keys("s6"), 2);
  assert.deepEqual(fourth.stale, keys("s3", "s4"), "now b is gone, and so are its squares");
});

test("loading a neighbourhood again changes nothing on the map and makes it the newest", () => {
  let ledger = addNeighbourhood([], "a", keys("a1")).ledger;
  ledger = addNeighbourhood(ledger, "b", keys("b1")).ledger;
  const again = addNeighbourhood(ledger, "a", keys("a1"));
  assert.deepEqual([again.fresh, again.stale], [[], []]);
  assert.deepEqual(again.ledger.map((n) => n.id), ["b", "a"]);
});

test("a neighbourhood with no wet squares still takes its place, and a repeated key is counted once", () => {
  const empty = addNeighbourhood([], "none", []);
  assert.deepEqual(empty.ledger, [{ id: "none", keys: [] }]);
  assert.deepEqual(addNeighbourhood([], "a", keys("x", "x", "y")).fresh, keys("x", "y"));
});

test("the ledger is never changed in place", () => {
  const ledger = Object.freeze([Object.freeze({ id: "a", keys: Object.freeze(keys("a1")) })]);
  const step = addNeighbourhood(ledger, "b", keys("b1"));
  assert.equal(ledger.length, 1);
  assert.equal(step.ledger.length, 2);
  assert.notEqual(step.ledger, ledger);
});

test("a neighbourhood is named by its blocks, whatever order they come in", () => {
  const grid = { name: "N10_E100" };
  const one = neighbourhoodId(grid, [{ bi: 348, bj: 77 }, { bi: 349, bj: 78 }, { bi: 348, bj: 78 }, { bi: 349, bj: 77 }]);
  const two = neighbourhoodId(grid, [{ bi: 349, bj: 77 }, { bi: 348, bj: 78 }, { bi: 349, bj: 78 }, { bi: 348, bj: 77 }]);
  assert.equal(one, two);
  assert.notEqual(one, neighbourhoodId(grid, [{ bi: 348, bj: 77 }]));
  assert.notEqual(one, neighbourhoodId({ name: "N10_E110" }, [{ bi: 348, bj: 77 }, { bi: 349, bj: 78 }, { bi: 348, bj: 78 }, { bi: 349, bj: 77 }]));
});
