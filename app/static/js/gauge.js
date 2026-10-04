import { ADULT_M, BANDS, COUNTER_M, DOOR_M, SCENARIOS, band, depthText, depthWords, s, scenarioLabel } from "./dom.js";
import { t } from "./i18n.js";

// The shop-front drawing, in SVG units: a street, an adult, a door and a counter, to scale.
const WIDTH = 360;
const GROUND_Y = 208;
const PX_PER_M = 62;
const TOP_M = 3;                  // one storey: deeper water is cut off at the top, and the drawing says so
export const MAX_DRAWN_FLOOR_M = 0.75;   // a taller floor estimate would push the door past one storey
const PERSON_X = 58;
const DOOR = { x: 104, w: 54 };
const COUNTER = { x: 180, w: 82 };
const LABEL_X = WIDTH - 4;
const WATER_W = 280;              // water and the dashed levels stop here: the gutter to LABEL_X fits "1 dalam 50", so no label is under water
const LABEL_GAP = 14;
// The water is always the same blue, whatever the depth: the deeper bands' indigo and plum, painted over a street, do not
// read as water. How deep it is stays in the words and on the map, and the depth is the height of the blue.
const WATER_FILL = BANDS[2].color;
let drawnWaterM = 0;   // where the water stood in the last drawing, so the next one rises or falls from there
let lastWater = null;

const yAt = (m) => GROUND_Y - m * PX_PER_M;

/** Where the water is on screen right now, which is mid-way if the last drawing is still animating. */
function paintedM() {
  const transform = lastWater?.isConnected ? getComputedStyle(lastWater).transform : "none";
  return transform === "none" ? drawnWaterM : new DOMMatrixReadOnly(transform).d * TOP_M;
}

function objects(floorM) {
  const y = (m) => yAt(floorM + m);
  return [
    floorM > 0 && s("rect", { class: "floor", x: 24, y: y(0), width: 244, height: floorM * PX_PER_M }),
    s("g", { class: "figure" },
      s("circle", { cx: PERSON_X, cy: y(1.53), r: 7 }),
      s("rect", { x: PERSON_X - 11, y: y(1.38), width: 22, height: (1.38 - 0.85) * PX_PER_M, rx: 6 }),
      s("rect", { x: PERSON_X - 10, y: y(0.88), width: 9, height: 0.88 * PX_PER_M, rx: 3 }),
      s("rect", { x: PERSON_X + 1, y: y(0.88), width: 9, height: 0.88 * PX_PER_M, rx: 3 })),
    s("rect", { class: "door", x: DOOR.x, y: y(DOOR_M), width: DOOR.w, height: DOOR_M * PX_PER_M }),
    s("circle", { class: "knob", cx: DOOR.x + DOOR.w - 8, cy: y(1), r: 2 }),
    s("rect", { class: "counter", x: COUNTER.x, y: y(COUNTER_M), width: COUNTER.w, height: COUNTER_M * PX_PER_M }),
  ];
}

/** Drawn after the water, so they stay readable when it covers the objects. */
function objectLabels(floorM) {
  const y = (m) => yAt(floorM + m) - 6;
  return [
    s("text", { class: "object-label", x: PERSON_X, y: y(ADULT_M), "text-anchor": "middle" }, t("gauge.adult", { m: ADULT_M })),
    s("text", { class: "object-label", x: DOOR.x + DOOR.w / 2, y: y(DOOR_M), "text-anchor": "middle" }, t("gauge.door", { m: DOOR_M })),
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

export function gauge(premise, rp, floorM) {
  const depth = premise.depth_m[rp];
  const shownM = band(depth) ? Math.min(depth, TOP_M) : 0;
  const water = s("rect", { class: "water", x: 0, y: yAt(TOP_M), width: WATER_W, height: TOP_M * PX_PER_M, fill: WATER_FILL });
  const waterline = s("line", { class: "waterline", x1: 0, x2: WATER_W, y1: GROUND_Y, y2: GROUND_Y });
  const fromM = paintedM();
  water.style.transform = `scaleY(${fromM / TOP_M})`;
  waterline.style.transform = `translateY(${-fromM * PX_PER_M}px)`;
  drawnWaterM = shownM;
  lastWater = water;
  requestAnimationFrame(() => {   // the card is in the page by now, so the change animates
    water.getBoundingClientRect();
    water.style.transform = `scaleY(${shownM / TOP_M})`;
    waterline.style.transform = `translateY(${-shownM * PX_PER_M}px)`;
  });
  const others = SCENARIOS.filter((key) => key !== rp && band(premise.depth_m[key]))
    .map((key) => s("line", { class: "other-level", x1: 0, x2: WATER_W, y1: yAt(Math.min(premise.depth_m[key], TOP_M)), y2: yAt(Math.min(premise.depth_m[key], TOP_M)) }));
  return s("svg", { class: "gauge", viewBox: `0 0 ${WIDTH} ${GROUND_Y + 24}`, role: "img", "aria-label": gaugeSummary(premise, rp) },
    objects(floorM), water, waterline, others, objectLabels(floorM), levelLabels(premise, rp),
    s("line", { class: "storey", x1: 0, x2: WATER_W, y1: yAt(TOP_M), y2: yAt(TOP_M) }),
    depth > TOP_M && s("text", { class: "object-label", x: 6, y: yAt(TOP_M) + 28 }, t("gauge.deeper", { m: depth.toFixed(2) })),
    s("line", { class: "street", x1: 0, x2: WIDTH, y1: GROUND_Y, y2: GROUND_Y }),
    s("text", { x: 6, y: GROUND_Y + 17 }, t("gauge.street")));
}

/** A small, still picture of the same scene at one depth: no labels, no animation, no shared state. The text beside it
 *  says the figure, so it is hidden from screen readers. Water is cut off at one storey, as in the full drawing. */
export function miniGauge(depthM) {
  const shownM = band(depthM) ? Math.min(depthM, TOP_M) : 0;
  const top = yAt(TOP_M);
  return s("svg", { class: "gauge gauge-mini", viewBox: `0 ${top} ${WATER_W} ${GROUND_Y - top + 3}`, "aria-hidden": "true" },
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
