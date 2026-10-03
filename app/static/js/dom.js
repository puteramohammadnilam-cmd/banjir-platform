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
export const BAND_COLORS = ["#a9d6e5", "#4f9fc4", "#1f6a96", "#0b3b5c"];

/** 0 = dry, 1..4 = depth band, shallow to deep. */
export function band(depth) {
  if (depth == null || depth <= 0) return 0;
  if (depth < 0.5) return 1;
  if (depth < 1.5) return 2;
  return depth < 3 ? 3 : 4;
}

export const depthText = (depth) => (band(depth) ? `${depth.toFixed(2)} m` : "no water in the model");
