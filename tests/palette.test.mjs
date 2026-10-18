// Run from 11_Platform_Draft:  node --test tests/palette.test.mjs
// The five depth colours: the CSS tokens match the JS, neighbours are far enough apart to tell, and the text on
// the depth chips (views.css) stays readable. And the squares' ramp (cells.js): one hue, falling lightness, and each
// step, laid over the map's ground at its opacity, far enough from the next.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { SQUARE_RAMP } from "../app/static/js/cells.js";
import { BANDS, DRY_COLOR } from "../app/static/js/dom.js";
import { FLASH_RAMP, LAYER_OPACITY, SCORE_RAMP } from "../app/static/js/susceptibility.js";
import { LOW_OPACITY, LOW_RAMP } from "../app/static/js/lowground.js";

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
  assert.ok(css("tokens.css").includes(`--ink-on-light: ${INK};`));
  colours.forEach((color, i) => {
    const text = i < 2 ? INK : "#ffffff";
    assert.ok(chips.includes(`.depth-chip.band-${i + 1} { background: var(--band-${i + 1}); color: ${i < 2 ? "var(--ink-on-light)" : "#fff"}; }`));
    assert.ok(contrast(color, text) >= 4.5, `band ${i + 1} text is ${contrast(color, text).toFixed(2)}:1`);
  });
});

// ---------- the squares' ramp ----------

const MAP_GROUND = "#f2efe9";   // --map-ground: the day map, under the flash flood, score and low ground pictures
const NIGHT_GROUND = "#2f363c"; // --map-night: the night map's land, under the squares
const hex = (channels) => `#${channels.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
/** The colour a square shows once laid at its opacity over `ground`. */
const laid = ({ color, opacity }, ground = MAP_GROUND) => hex(rgb(color).map((c, i) => opacity * c + (1 - opacity) * rgb(ground)[i]));
const hueDegrees = (color) => {
  const [, a, b] = oklab(color);
  return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
};

test("tokens.css holds the squares' ramp: each colour at its opacity, on the night map's ground", () => {
  const tokens = css("tokens.css");
  SQUARE_RAMP.forEach(({ color, opacity }, i) => {
    const token = new RegExp(`--square-${i + 1}: rgb\\((\\d+) (\\d+) (\\d+) / ([\\d.]+)\\);`).exec(tokens);
    assert.ok(token, `--square-${i + 1} is missing`);
    assert.deepEqual(token.slice(1, 4).map(Number), rgb(color), `--square-${i + 1} colour`);
    assert.equal(Number(token[4]), opacity, `--square-${i + 1} opacity`);
  });
  assert.ok(tokens.includes(`--map-ground: ${MAP_GROUND};`));
  assert.ok(tokens.includes(`--map-night: ${NIGHT_GROUND};`));
});

test("the squares are one hue (within 10 degrees), clearly blue, and brighter with depth, so the deepest glows on the night map", () => {
  const hues = SQUARE_RAMP.map(({ color }) => hueDegrees(color));
  assert.ok(Math.max(...hues) - Math.min(...hues) <= 10, `hues run ${hues.map((x) => x.toFixed(0)).join(", ")}`);
  hues.forEach((hue) => assert.ok(hue > 230 && hue < 260, `hue ${hue.toFixed(0)} is blue`));
  SQUARE_RAMP.slice(1).forEach(({ color }, i) => assert.ok(oklab(color)[0] > oklab(SQUARE_RAMP[i].color)[0], `step ${i + 2} is brighter than step ${i + 1}`));
});

test("each square step, laid on the night map, is at least 8 apart from the next, and the shallowest shows against the ground", () => {
  SQUARE_RAMP.slice(1).forEach((step, i) => {
    const gap = deltaE(laid(SQUARE_RAMP[i], NIGHT_GROUND), laid(step, NIGHT_GROUND));
    assert.ok(gap >= 8, `step ${i + 1} and ${i + 2} are only ${gap.toFixed(1)} apart`);
  });
  assert.ok(deltaE(laid(SQUARE_RAMP[0], NIGHT_GROUND), NIGHT_GROUND) >= 3.5, "the shallowest square can be seen on the map");
});

test("the squares do not reuse any of the dots' colours", () => {
  for (const { color } of SQUARE_RAMP) assert.ok(!colours.includes(color), color);
});

// ---------- flash flood potential and our score: ramps of their own ----------

const hueGap = (a, b) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b));
const NEW_RAMPS = { flash: FLASH_RAMP, score: SCORE_RAMP };

test("the flash ramp is warm (OKLCH hue about 50) and the layer and its key share one opacity", () => {
  FLASH_RAMP.forEach(({ color, opacity }) => {
    const hue = hueDegrees(color);
    assert.ok(hue >= 30 && hue <= 70, `${color} hue ${hue.toFixed(0)}`);
    assert.equal(opacity, LAYER_OPACITY);
  });
});

test("each new ramp sits at least 60 degrees of hue from the squares, and from each other", () => {
  const squares = SQUARE_RAMP.map(({ color }) => hueDegrees(color));
  for (const [name, ramp] of Object.entries(NEW_RAMPS)) {
    for (const { color } of ramp) {
      for (const square of squares) assert.ok(hueGap(hueDegrees(color), square) >= 60, `${name} ${color} is too near the squares' blue`);
    }
  }
  for (const flash of FLASH_RAMP) {
    for (const score of SCORE_RAMP) assert.ok(hueGap(hueDegrees(flash.color), hueDegrees(score.color)) >= 60, `${flash.color} ${score.color}`);
  }
});

test("each new ramp darkens step by step, and each step, laid on the map, is at least 8 apart from the next", () => {
  for (const [name, ramp] of Object.entries(NEW_RAMPS)) {
    ramp.slice(1).forEach((step, i) => {
      assert.ok(oklab(step.color)[0] < oklab(ramp[i].color)[0], `${name} step ${i + 2} is darker than step ${i + 1}`);
      const gap = deltaE(laid(ramp[i]), laid(step));
      assert.ok(gap >= 8, `${name} steps ${i + 1} and ${i + 2} are only ${gap.toFixed(1)} apart`);
    });
    assert.ok(deltaE(laid(ramp[0]), MAP_GROUND) >= 3.5, `${name}'s palest step can be seen on the map`);
  }
});

test("the warm ramp is apart from the five dot colours, so a dot (ringed in white) on the layer still reads", () => {
  for (const step of FLASH_RAMP) {
    for (const dot of colours) assert.ok(deltaE(laid(step), dot) >= 7.5, `${step.color} against dot ${dot}`);   // a dot also wears a white ring and a dark hairline
  }
});

// ---------- low ground: a teal-grey of its own, darker where the ground sits lower ----------

/** The ramp palest first, as the other ramps are tested: the highest ground's tone first. */
const LOW_PALEST_FIRST = [...LOW_RAMP].reverse();

test("the low ground ramp is one teal-grey hue, at one opacity, darker for lower ground", () => {
  const hues = LOW_RAMP.map(({ color }) => hueDegrees(color));
  assert.ok(Math.max(...hues) - Math.min(...hues) <= 10, `hues run ${hues.map((x) => x.toFixed(0)).join(", ")}`);
  hues.forEach((hue) => assert.ok(hue >= 150 && hue <= 185, `hue ${hue.toFixed(0)} is teal-grey`));
  LOW_RAMP.forEach(({ opacity }) => assert.equal(opacity, LOW_OPACITY));
  LOW_RAMP.slice(1).forEach(({ color }, i) => assert.ok(oklab(color)[0] > oklab(LOW_RAMP[i].color)[0], `the tone up to ${LOW_RAMP[i + 1].upTo} m is paler`));
});

test("the low ground ramp sits at least 60 degrees of hue from the squares, flash potential and the score", () => {
  const others = { squares: SQUARE_RAMP, flash: FLASH_RAMP, score: SCORE_RAMP };
  for (const { color } of LOW_RAMP) {
    for (const [name, ramp] of Object.entries(others)) {
      for (const step of ramp) assert.ok(hueGap(hueDegrees(color), hueDegrees(step.color)) >= 60, `${color} is too near ${name} ${step.color}`);
    }
  }
});

test("each low ground step, laid on the map, is at least 8 apart from the next, and the palest shows", () => {
  LOW_PALEST_FIRST.slice(1).forEach((step, i) => {
    const gap = deltaE(laid(LOW_PALEST_FIRST[i]), laid(step));
    assert.ok(gap >= 8, `low ground steps ${i + 1} and ${i + 2} are only ${gap.toFixed(1)} apart`);
  });
  assert.ok(deltaE(laid(LOW_PALEST_FIRST[0]), MAP_GROUND) >= 3.5, "the palest step can be seen on the map");
});

test("the low ground PNGs' palette is the page's ramp, lowest ground first", () => {
  const doc = JSON.parse(readFileSync(new URL("../app/data/dem/shah-alam_lowground.json", import.meta.url), "utf8"));
  assert.deepEqual(doc.tones.map((tone) => tone.colour), LOW_RAMP.map(({ color }) => color));
  assert.deepEqual(doc.tones.map((tone) => tone.up_to_m), LOW_RAMP.map(({ upTo }) => upTo));
});

test("every stylesheet in styles/ is linked from the page, after tokens.css and app.css", async () => {
  const { readdirSync } = await import("node:fs");
  const page = readFileSync(new URL("../app/static/index.html", import.meta.url), "utf8");
  const linked = [...page.matchAll(/<link rel="stylesheet" href="styles\/([\w-]+\.css)">/g)].map((match) => match[1]);
  const files = readdirSync(new URL("../app/static/styles/", import.meta.url)).filter((name) => name.endsWith(".css"));
  assert.deepEqual([...linked].sort(), [...files].sort());
  assert.deepEqual(linked.slice(0, 2), ["tokens.css", "app.css"]);
});
