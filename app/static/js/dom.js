// Small DOM helpers. Everything goes through textContent, never innerHTML.
const SVG_NS = "http://www.w3.org/2000/svg";

function fill(node, attrs, children) {
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child != null && child !== false) node.append(child);
  }
  return node;
}

export const h = (tag, attrs = {}, ...children) => fill(document.createElement(tag), attrs, children);
export const s = (tag, attrs = {}, ...children) => fill(document.createElementNS(SVG_NS, tag), attrs, children);

export const SCENARIOS = ["10", "100", "500"];
export const SCENARIO_LABEL = { 10: "once in 10 years", 100: "once in 100 years", 500: "once in 500 years" };

// Things a shop owner can picture, at typical heights: a counter, an adult, a door, a storey. Same colours as tokens.css.
export const ADULT_M = 1.65;
export const COUNTER_M = 0.9;
export const DOOR_M = 2.1;
export const BANDS = [
  { below: COUNTER_M, color: "#c6e4ef", words: "Up to counter height", range: "under 0.9 m" },
  { below: ADULT_M, color: "#86c0db", words: "Over the counter", range: "0.9 to 1.65 m" },
  { below: DOOR_M, color: "#2b77a7", words: "Over an adult's head", range: "1.65 to 2.1 m" },
  { below: 3, color: "#1a5482", words: "Over the door", range: "2.1 to 3 m" },
  { below: Infinity, color: "#0b2f4c", words: "A storey or more", range: "3 m or more" },
];
export const DRY_COLOR = "#fbf8f1";

/** 0 = dry, 1..5 = depth band, shallow to deep. */
export function band(depth) {
  if (depth == null || depth <= 0) return 0;
  return BANDS.findIndex((b) => depth < b.below) + 1;
}

export const bandColor = (depth) => BANDS[band(depth) - 1]?.color ?? DRY_COLOR;

const WORDS = [[0.15, "ankle-deep"], [0.5, "up to the knee"], [COUNTER_M, "up to the waist"], [1.3, "up to the chest"],
  [ADULT_M, "up to the neck"], [DOOR_M, "over an adult's head"], [3, "over the top of a door"], [Infinity, "a storey or more"]];

/** Plain words for a depth, for an adult about 1.65 m tall. */
export function depthWords(depth) {
  if (!band(depth)) return "no water in the model";
  return WORDS.find(([below]) => depth < below)[1];
}

/** Chance of at least one flood this size within `years`, for a flood expected once in `returnPeriod` years. */
export const chanceWithin = (returnPeriod, years) => 1 - (1 - 1 / returnPeriod) ** years;

export const depthText = (depth) => (band(depth) ? `${depth.toFixed(2)} m` : "no water in the model");

/** An icon from the sprite in index.html. Decorative, so screen readers skip it. */
export const icon = (name) => s("svg", { class: "icon", "aria-hidden": "true" }, s("use", { href: `#i-${name}` }));

export const CHANCE_YEARS = 10;   // about one shop lease

/** The three flood sizes as one control, each with its chance of happening at least once in CHANCE_YEARS. */
export function scenarioPicker(rp, onPick) {
  return h("div", { class: "scenario", role: "group", "aria-label": "Size of flood" },
    SCENARIOS.map((key) => {
      const chance = `${Math.round(chanceWithin(Number(key), CHANCE_YEARS) * 100)}% chance in ${CHANCE_YEARS} years`;
      return h("button", { type: "button", "aria-pressed": String(key === rp), "aria-label": `1 in ${key} years, ${chance}`, onclick: () => onPick(key) },
        `1 in ${key} years`, h("span", { class: "chance" }, chance));
    }));
}

/** Put a fresh picker in `slot`, keeping keyboard focus on the chosen size if the old picker had it. */
export function renderPicker(slot, rp, onPick) {
  const hadFocus = slot.contains(document.activeElement);
  slot.replaceChildren(scenarioPicker(rp, onPick));
  if (hadFocus) slot.querySelector('[aria-pressed="true"]')?.focus();
}

const RINGGIT = new Intl.NumberFormat("en-MY", { style: "currency", currency: "MYR", maximumFractionDigits: 0 });
export const ringgit = (value) => RINGGIT.format(value);

export const kindText = (premise) => `${premise.sector === "eatery" ? "Eatery" : "Shop"}${premise.kind ? ` · ${premise.kind.replaceAll("_", " ")}` : ""}`;
