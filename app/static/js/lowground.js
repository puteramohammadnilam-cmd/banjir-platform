// The "low ground" layer: land within 1, 2, 3 or 5 m of the level of the nearest mapped river, shaded darker the lower it
// sits (from Copernicus GLO-30 heights and OpenStreetMap rivers, tools/build_lowground.py). Never a flood forecast: the
// key says land left unshaded can still flood from rain or drains. The server sends the area's `layers.low_ground`
// {levels, url (holding "{level}"), bounds, credit}, or null; with none, the page offers no control.
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { createPictureLayer } from "./map.js";
import { rampSwatch } from "./susceptibility.js";

export const LOW_LEVELS = Object.freeze([1, 2, 3, 5]);   // metres; also the tops of the four tones
export const DEFAULT_LEVEL = 2;
export const LOW_OPACITY = 0.65;
export const LOW_PANE = "low-ground";
export const LOW_PANE_Z = 300;   // under the flash flood picture (350) and the squares and dots (400)

// The PNGs' own palette (tools/build_lowground.py TONES_OKLCH): a teal-grey, OKLCH hue 175, lowest ground (darkest)
// first. Apart from the squares' blue, flash potential's orange and the score's orchid; tests/palette.test.mjs holds it.
const LOW_STEPS = ["#1d4c41", "#417467", "#6e9e90", "#a0c8bc"];
export const LOW_RAMP = Object.freeze(LOW_STEPS.map((color, i) => Object.freeze({ upTo: LOW_LEVELS[i], color, opacity: LOW_OPACITY })));

/** The layer's address for one level: the server's template with {level} filled in. */
export const levelUrl = (layer, level) => layer.url.replaceAll("{level}", String(level));

/** The levels on offer: the server's, of those the page knows; none for a layer it cannot draw. */
export const levelsOf = (layer) => (typeof layer?.url === "string" && Array.isArray(layer.levels) && Array.isArray(layer.bounds)
  ? LOW_LEVELS.filter((level) => layer.levels.includes(level)) : []);

const stepWords = (step, i) => (i === 0
  ? t("lowground.stepFirst", { to: step.upTo }) : t("lowground.step", { from: LOW_RAMP[i - 1].upTo, to: step.upTo }));

/** The key's group for the layer at `level`: the tones shaded at that level, what the shading means and does not, the
 *  3 km limit and the credit. */
export function lowGroundKey(level) {
  const steps = LOW_RAMP.filter((step) => step.upTo <= level);
  return h("li", { class: "legend-group lowground-key" },
    h("p", { class: "legend-heading" }, t("lowground.legend")),
    h("ul", { class: "legend-items ramp-key" }, steps.map((step, i) => h("li", {}, rampSwatch(step), stepWords(step, i)))),
    h("p", { class: "fineprint" }, t("lowground.note", { m: level })),
    h("p", { class: "fineprint" }, t("lowground.beyond")),
    h("p", { class: "fineprint" }, t("lowground.credit")));
}

/** One radio per level, `level` chosen; onPick(level) hears a choice. */
const levelChoice = (levels, level, onPick) => h("fieldset", { class: "metric-choice lowground-levels", hidden: true },
  h("legend", {}, t("lowground.levelLegend")),
  levels.map((value) => h("label", {},
    h("input", { type: "radio", name: "lowground-level", value, checked: value === level, onchange: () => onPick(value) }),
    t("lowground.level", { m: value }))));

/** The "Show low ground" box (off at first) and, once ticked, the choice of level (DEFAULT_LEVEL at first), for the
 *  area's `layer`; each level's picture is fetched the first time it shows, in a pane under the flash flood picture.
 *  onChange(key) hears the key's group to show, or null while off. A picture that fails to load unticks the box and
 *  says so; the next tick tries again. Gives back {nodes} to put under the map: none without a layer. */
export function createLowGround(map, layer, { onChange = () => {} } = {}) {
  const levels = levelsOf(layer);
  if (!levels.length) return { nodes: [] };
  let state = { isOn: false, level: levels.includes(DEFAULT_LEVEL) ? DEFAULT_LEVEL : levels[0] };
  const pictures = new Map();
  const alert = h("p", { class: "alert alert-inline layer-error", role: "alert", hidden: true });
  const pictureOf = (level) => {
    if (!pictures.has(level)) {
      pictures.set(level, map.addOverlay(({ map: leaflet }) => createPictureLayer(leaflet, { url: levelUrl(layer, level), bounds: layer.bounds },
        { opacity: LOW_OPACITY, className: "lowground-overlay", pane: LOW_PANE, zIndex: LOW_PANE_Z, onError: () => failed(level) })));
    }
    return pictures.get(level);
  };
  const set = (change) => {
    const before = state;
    state = { ...state, ...change };
    if (before.isOn && (!state.isOn || before.level !== state.level)) pictureOf(before.level).show(false);
    if (state.isOn) alert.hidden = true;
    if (state.isOn) pictureOf(state.level).show(true);
    box.checked = state.isOn;
    choice.hidden = !state.isOn;
    onChange(state.isOn ? lowGroundKey(state.level) : null);
  };
  const failed = (level) => {
    if (!state.isOn || state.level !== level) return;   // a level no longer on show: nothing to undo
    set({ isOn: false });
    alert.textContent = t("lowground.layerError");
    alert.hidden = false;
  };
  const box = h("input", { type: "checkbox", onchange: (event) => set({ isOn: Boolean(event.target.checked) }) });
  const choice = levelChoice(levels, state.level, (level) => set({ level }));
  return { nodes: [h("label", { class: "layer-toggle" }, box, t("lowground.toggle")), choice, alert] };
}
