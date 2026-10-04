// Run from 11_Platform_Draft:  node --test tests/palette.test.mjs
// The five depth colours: the CSS tokens match the JS, neighbours are far enough apart to tell, and the text on
// the depth chips (views.css) stays readable. And the squares' ramp (cells.js): one hue, falling lightness, and each
// step, laid over the map's ground at its opacity, far enough from the next.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { SQUARE_RAMP } from "../app/static/js/cells.js";
import { BANDS, DRY_COLOR } from "../app/static/js/dom.js";

const css = (file) => readFileSync(new URL(`../app/static/styles/${file}`, import.meta.url), "utf8");
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const linear = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

function oklab(hex) {
  const [r, g, b] = rgb(hex).map(linear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
/** Distance between two colours in OKLab, times 100. Under about 10 two fills are hard to tell apart. */
const deltaE = (a, b) => 100 * Math.hypot(...oklab(a).map((v, i) => v - oklab(b)[i]));

function luminance(hex) {
  const [r, g, b] = rgb(hex).map(linear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05);

const INK = "#0d1b2a";
const colours = BANDS.map((b) => b.color);

test("tokens.css holds the same five colours as BANDS", () => {
  const tokens = css("tokens.css");
  colours.forEach((color, i) => assert.ok(tokens.includes(`--band-${i + 1}: ${color};`), `--band-${i + 1} should be ${color}`));
  assert.ok(tokens.includes(`--dry-dot: ${DRY_COLOR};`));
});

test("each depth colour is clearly different from the next, and the deepest two are no longer one navy", () => {
  colours.slice(1).forEach((color, i) => {
    const gap = deltaE(colours[i], color);
    assert.ok(gap >= 14, `band ${i + 1} and ${i + 2} are only ${gap.toFixed(1)} apart`);
  });
});

test("the shallowest colour is not mistaken for the no-water dot", () => {
  assert.ok(deltaE(colours[0], DRY_COLOR) >= 9);
});

test("depth chip text reaches 4.5:1: dark ink on the two palest bands, white on the three deepest", () => {
  const chips = css("views.css");
  colours.forEach((color, i) => {
    const text = i < 2 ? INK : "#ffffff";
    assert.ok(chips.includes(`.depth-chip.band-${i + 1} { background: var(--band-${i + 1}); color: ${i < 2 ? "var(--ink)" : "#fff"}; }`));
    assert.ok(contrast(color, text) >= 4.5, `band ${i + 1} text is ${contrast(color, text).toFixed(2)}:1`);
  });
});

// ---------- the squares' ramp ----------

const MAP_GROUND = "#f2efe9";   // --map-ground: the colour of the base map under the squares
const hex = (channels) => `#${channels.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
/** The colour a square shows once laid at its opacity over `ground`. */
const laid = ({ color, opacity }, ground = MAP_GROUND) => hex(rgb(color).map((c, i) => opacity * c + (1 - opacity) * rgb(ground)[i]));
const hueDegrees = (color) => {
  const [, a, b] = oklab(color);
  return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
};

test("tokens.css holds the squares' ramp: each colour at its opacity, on the map's ground", () => {
  const tokens = css("tokens.css");
  SQUARE_RAMP.forEach(({ color, opacity }, i) => {
    const token = new RegExp(`--square-${i + 1}: rgb\\((\\d+) (\\d+) (\\d+) / ([\\d.]+)\\);`).exec(tokens);
    assert.ok(token, `--square-${i + 1} is missing`);
    assert.deepEqual(token.slice(1, 4).map(Number), rgb(color), `--square-${i + 1} colour`);
    assert.equal(Number(token[4]), opacity, `--square-${i + 1} opacity`);
  });
  assert.ok(tokens.includes(`--map-ground: ${MAP_GROUND};`));
});

test("the squares are one hue (within 10 degrees), clearly blue, and darker with depth", () => {
  const hues = SQUARE_RAMP.map(({ color }) => hueDegrees(color));
  assert.ok(Math.max(...hues) - Math.min(...hues) <= 10, `hues run ${hues.map((x) => x.toFixed(0)).join(", ")}`);
  hues.forEach((hue) => assert.ok(hue > 230 && hue < 260, `hue ${hue.toFixed(0)} is blue`));
  SQUARE_RAMP.slice(1).forEach(({ color }, i) => assert.ok(oklab(color)[0] < oklab(SQUARE_RAMP[i].color)[0], `step ${i + 2} is darker than step ${i + 1}`));
});

test("each square step, laid on the map, is at least 8 apart from the next, and the shallowest shows against the ground", () => {
  SQUARE_RAMP.slice(1).forEach((step, i) => {
    const gap = deltaE(laid(SQUARE_RAMP[i]), laid(step));
    assert.ok(gap >= 8, `step ${i + 1} and ${i + 2} are only ${gap.toFixed(1)} apart`);
  });
  assert.ok(deltaE(laid(SQUARE_RAMP[0]), MAP_GROUND) >= 3.5, "the shallowest square can be seen on the map");
});

test("the squares do not reuse any of the dots' colours", () => {
  for (const { color } of SQUARE_RAMP) assert.ok(!colours.includes(color), color);
});
