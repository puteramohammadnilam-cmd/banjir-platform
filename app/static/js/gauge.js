import { ADULT_M, BANDS, COUNTER_M, DOOR_M, SCENARIOS, band, depthText, depthWords, s, scenarioLabel } from "./dom.js";
import { t } from "./i18n.js";

// The street scene (night water, 18 Oct 2026), in SVG units: a shophouse front with the shop's own signboard, a red and
// white flood post marked in metres, an adult, the shop's opening (the door) and its counter, all to scale, and the
// water rising to the model's depth. The first floor's slab is at about 3.6 m, so a 3.26 m flood is seen against it.
const WIDTH = 440;
const GROUND_Y = 290;
const PX_PER_M = 56;
export const TOP_M = 4;           // the scene's height of water: deeper water is cut off at the top, and the scene says so
const STOREY_M = 3;               // the small picture's: one storey
export const MAX_DRAWN_FLOOR_M = 0.75;   // a taller floor estimate would push the door too near the top
const POST_X = 10;
const PERSON_X = 52;
const FRONT = { x: 80, w: 272, top: 4.7 };   // the shophouse's front: from the post's side to the water's edge
const DOOR = { x: 100, w: 140 };             // the opening, shutter rolled up
const COUNTER = { x: 150, w: 76 };
const SIGN = { x: 100, w: 232, from: 2.68, to: 3.3 };
const SLAB_M = 3.62;
const SIGN_GAP_M = 0.2;           // at least this from the top of the opening to the board's foot
const SLAB_FOOT_M = SLAB_M - 8 / PX_PER_M;   // the slab is drawn 8 units deep, down from SLAB_M
const WINDOWS = [104, 168, 232, 296];
const LABEL_X = WIDTH - 4;
const WATER_W = FRONT.x + FRONT.w;   // water and the dashed levels stop here: the gutter to LABEL_X fits "1 dalam 50", so no label is under water
const LABEL_GAP = 14;
const SIGN_FIT = 22;              // past this many letters the name is squeezed to fit the board
// The water's colour is set by CSS (a lit gradient, #water-glass in index.html); this fill is what shows without it.
// It is one blue whatever the depth: the deeper bands' indigo and plum, painted over a street, do not read as water.
const WATER_FILL = BANDS[2].color;
let drawnWaterM = 0;   // where the water stood in the last drawing, so the next one rises or falls from there
let lastWater = null;

const yAt = (m) => GROUND_Y - m * PX_PER_M;

/** Where the water is on screen right now, which is mid-way if the last drawing is still animating. */
function paintedM() {
  const transform = lastWater?.isConnected ? getComputedStyle(lastWater).transform : "none";
  return transform === "none" ? drawnWaterM : new DOMMatrixReadOnly(transform).d * TOP_M;
}

/** The adult, the opening and the counter: the three things the depth is read against. */
function objects(floorM) {
  const y = (m) => yAt(floorM + m);
  return [
    floorM > 0 && s("rect", { class: "floor", x: FRONT.x - 56, y: y(0), width: FRONT.w + 56, height: floorM * PX_PER_M }),
    s("g", { class: "figure" },
      s("circle", { cx: PERSON_X, cy: y(1.53), r: 7 }),
      s("rect", { x: PERSON_X - 11, y: y(1.38), width: 22, height: (1.38 - 0.85) * PX_PER_M, rx: 6 }),
      s("rect", { x: PERSON_X - 10, y: y(0.88), width: 9, height: 0.88 * PX_PER_M, rx: 3 }),
      s("rect", { x: PERSON_X + 1, y: y(0.88), width: 9, height: 0.88 * PX_PER_M, rx: 3 })),
    s("rect", { class: "door", x: DOOR.x, y: y(DOOR_M), width: DOOR.w, height: DOOR_M * PX_PER_M }),
    s("rect", { class: "counter", x: COUNTER.x, y: y(COUNTER_M), width: COUNTER.w, height: COUNTER_M * PX_PER_M }),
  ];
}

/** The shophouse behind them: its front, pillars, the first floor's slab and windows, the rolled-up shutter, a shop
 *  window, and the signboard with the shop's name (none for a point). Background only: it carries no figure. */
function shophouse(floorM, name) {
  const y = (m) => yAt(floorM + m);
  const fits = name.length <= SIGN_FIT;
  const signFrom = Math.max(SIGN.from, floorM + DOOR_M + SIGN_GAP_M);   // a raised floor lifts the door, and the board over it
  const signTo = Math.min(SLAB_FOOT_M - 0.03, Math.max(SIGN.to, signFrom + 0.36));   // and stays under the slab
  return s("g", { class: "shophouse" },
    s("rect", { class: "wall", x: FRONT.x, y: yAt(FRONT.top), width: FRONT.w, height: FRONT.top * PX_PER_M }),
    s("rect", { class: "slab", x: FRONT.x, y: yAt(SLAB_M), width: FRONT.w, height: 8 }),
    WINDOWS.map((x, i) => s("rect", { class: i === 2 ? "window is-lit" : "window", x, y: yAt(4.5), width: 40, height: 42 })),   // someone upstairs
    s("rect", { class: "pillar", x: FRONT.x, y: yAt(3.5), width: 9, height: 3.5 * PX_PER_M }),
    s("rect", { class: "pillar", x: FRONT.x + FRONT.w - 9, y: yAt(3.5), width: 9, height: 3.5 * PX_PER_M }),
    s("rect", { class: "sign", x: SIGN.x, y: yAt(signTo), width: SIGN.w, height: (signTo - signFrom) * PX_PER_M }),
    name && s("text", { class: "sign-text", x: SIGN.x + SIGN.w / 2, y: yAt((signFrom + signTo) / 2) + 4.5, "text-anchor": "middle",
      ...(fits ? {} : { textLength: SIGN.w - 16, lengthAdjust: "spacingAndGlyphs" }) }, name),
    s("rect", { class: "shutter", x: DOOR.x, y: y(DOOR_M) - 7, width: DOOR.w, height: 7 }),
    s("rect", { class: "glass", x: DOOR.x + DOOR.w + 12, y: y(DOOR_M), width: FRONT.w - DOOR.w - 52, height: (DOOR_M - 0.45) * PX_PER_M }));
}

/** The flood post: red and white bands of half a metre, and the metres beside it. */
function floodPost() {
  const bands = Array.from({ length: TOP_M * 2 + 1 }, (_, i) =>
    s("rect", { class: i % 2 ? "post-white" : "post-red", x: POST_X, y: yAt((i + 1) / 2), width: 10, height: PX_PER_M / 2 }));
  const marks = Array.from({ length: TOP_M }, (_, i) =>
    s("text", { class: "post-label", x: POST_X + 14, y: yAt(i + 1) + 4 }, t("common.metres", { m: i + 1 })));
  return s("g", { class: "post" }, bands, marks);
}

/** Drawn after the water, so they stay readable when it covers the objects. */
function objectLabels(floorM) {
  const y = (m) => yAt(floorM + m) - 6;
  return [
    s("text", { class: "object-label", x: PERSON_X, y: y(ADULT_M), "text-anchor": "middle" }, t("gauge.adult", { m: ADULT_M })),
    s("text", { class: "object-label", x: DOOR.x + DOOR.w / 2, y: y(DOOR_M) + 22, "text-anchor": "middle" }, t("gauge.door", { m: DOOR_M })),   // just inside the opening's top, clear of the sign over it
    s("text", { class: "object-label", x: COUNTER.x + COUNTER.w / 2, y: y(COUNTER_M), "text-anchor": "middle" }, t("gauge.counter", { m: COUNTER_M })),
  ];
}

/** One label per flood size at its water line, pushed apart where two lines sit close together. */
function levelLabels(premise, rp) {
  const labels = SCENARIOS.filter((key) => band(premise.depth_m[key]))
    .map((key) => ({ key, y: yAt(Math.min(premise.depth_m[key], TOP_M)) - 4 }))   // just above the line, not struck through
    .sort((a, b) => a.y - b.y);
  labels.forEach((label, i) => { if (i && label.y - labels[i - 1].y < LABEL_GAP) label.y = labels[i - 1].y + LABEL_GAP; });
  return labels.map(({ key, y }) => s("text", { class: key === rp ? "level is-active" : "level", x: LABEL_X, y, "text-anchor": "end" }, t("common.rpShort", { rp: key })));
}

/** The water, its lit line and the depth riding on it, each moved from where the water stood to where it stands now. */
function rising(depth, shownM) {
  const water = s("rect", { class: "water", x: 0, y: yAt(TOP_M), width: WATER_W, height: TOP_M * PX_PER_M, fill: WATER_FILL });
  const waterline = s("line", { class: "waterline", x1: 0, x2: WATER_W, y1: GROUND_Y, y2: GROUND_Y });
  const readout = shownM > 0 && s("g", { class: "readout" }, s("text", { x: WATER_W - 10, y: GROUND_Y - 10, "text-anchor": "end" }, depthText(depth)));
  const riders = [waterline, readout].filter(Boolean);
  const fromM = paintedM();
  const place = (m) => {
    water.style.transform = `scaleY(${m / TOP_M})`;
    for (const rider of riders) rider.style.transform = `translateY(${-m * PX_PER_M}px)`;
  };
  place(fromM);
  drawnWaterM = shownM;
  lastWater = water;
  requestAnimationFrame(() => {   // the card is in the page by now, so the change animates
    water.getBoundingClientRect();
    place(shownM);
  });
  return { water, waterline, readout };
}

export function gauge(premise, rp, floorM) {
  const depth = premise.depth_m[rp];
  const shownM = band(depth) ? Math.min(depth, TOP_M) : 0;
  const { water, waterline, readout } = rising(depth, shownM);
  const others = SCENARIOS.filter((key) => key !== rp && band(premise.depth_m[key]))
    .map((key) => s("line", { class: "other-level", x1: 0, x2: WATER_W, y1: yAt(Math.min(premise.depth_m[key], TOP_M)), y2: yAt(Math.min(premise.depth_m[key], TOP_M)) }));
  return s("svg", { class: "gauge", viewBox: `0 0 ${WIDTH} ${GROUND_Y + 30}`, role: "img", "aria-label": gaugeSummary(premise, rp) },
    shophouse(floorM, premise.is_point ? "" : premise.name ?? ""), floodPost(), objects(floorM), water, waterline, others,
    objectLabels(floorM), levelLabels(premise, rp), readout,
    s("line", { class: "storey", x1: 0, x2: WATER_W, y1: yAt(TOP_M), y2: yAt(TOP_M) }),
    depth > TOP_M && s("text", { class: "object-label", x: 30, y: yAt(TOP_M) + 28 }, t("gauge.deeper", { m: depth.toFixed(2) })),
    s("line", { class: "street", x1: 0, x2: WIDTH, y1: GROUND_Y, y2: GROUND_Y }),
    s("text", { x: 6, y: GROUND_Y + 19 }, t("gauge.street")));
}

/** A small, still picture of the same scene at one depth: no labels, no animation, no shared state. The text beside it
 *  says the figure, so it is hidden from screen readers. Water is cut off at one storey. */
export function miniGauge(depthM) {
  const shownM = band(depthM) ? Math.min(depthM, STOREY_M) : 0;
  const top = yAt(STOREY_M);
  return s("svg", { class: "gauge gauge-mini", viewBox: `${PERSON_X - 20} ${top} ${WATER_W - PERSON_X + 20} ${GROUND_Y - top + 3}`, "aria-hidden": "true" },
    objects(0),
    shownM > 0 && s("rect", { class: "water", x: 0, y: yAt(shownM), width: WATER_W, height: shownM * PX_PER_M, fill: WATER_FILL }),
    s("line", { class: "street", x1: 0, x2: WATER_W, y1: GROUND_Y, y2: GROUND_Y }));
}

function gaugeSummary(premise, rp) {
  const depth = premise.depth_m[rp];
  const others = SCENARIOS.filter((key) => key !== rp).map((key) => t("gauge.other", { rp: key, depth: depthText(premise.depth_m[key]) })).join(", ");
  const here = band(depth) ? `${depthText(depth)}, ${depthWords(depth)}` : depthText(depth);
  return t("gauge.summary", { label: scenarioLabel(rp), here, others });
}
