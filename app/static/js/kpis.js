// The four figure tiles at the top of the Area overview: how many businesses get water, how deep it typically gets,
// how often this area has flooded, and the rain forecast (only when Google Weather is set up).
import { band, icon, h } from "./dom.js";
import { floodCounts, isSearched } from "./history.js";
import { miniGauge } from "./gauge.js";
import { t } from "./i18n.js";

const RAIN_HOURS = 12;   // what GET /api/rain sums, said while it is asked
const COUNT_MS = 1600;   // as long as the map's water takes to come in (--duration-rise in tokens.css)
const motionOk = () => globalThis.matchMedia?.("(prefers-reduced-motion: no-preference)").matches ?? false;

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** One figure tile, built once and updated in place, so its bar can animate and the live region only speaks on change.
 *  `art` gives the tile a slot for a picture beside its figure (setArt fills it, or clears it); `name` is a class for CSS. */
function kpiTile(iconName, { hero = false, bar = false, art = false, name = "" } = {}) {
  const figure = h("p", { class: "kpi-figure" });
  const label = h("p", { class: "kpi-label" });
  const note = h("p", { class: "kpi-note" });
  const fill = bar ? h("span") : null;
  const slot = art ? h("div", { class: "kpi-art", "aria-hidden": "true" }) : null;
  if (fill) fill.style.transform = "scaleX(0)";
  const node = h("div", { class: `kpi${hero ? " kpi-hero" : ""}${art ? " kpi-has-art" : ""}${name ? ` kpi-${name}` : ""}` }, icon(iconName), slot, figure, label, note,
    fill && h("div", { class: "kpi-bar", "aria-hidden": "true" }, fill));
  return {
    node,
    set(figureText, labelText, noteText, share) {
      figure.textContent = figureText;
      label.textContent = labelText;
      note.textContent = noteText;
      if (fill) fill.style.transform = `scaleX(${share})`;
    },
    setFigure(figureText) {
      figure.textContent = figureText;
    },
    setArt(picture) {
      slot.replaceChildren(...(picture ? [picture] : []));
      slot.hidden = !picture;
    },
  };
}

/** The rain tile is for areas where Google Weather is set up; until the page has heard that it is, or when it is not,
 *  the tile stays out of the grid rather than showing a dash. */
export const rainShown = (rain) => Boolean(rain?.configured || rain?.busy);

function rainText(rain) {
  const due = (hours) => t("overview.rainDue", { hours });
  if (!rain || rain.busy) return ["…", due(RAIN_HOURS), t("overview.rainChecking")];
  if (rain.error || !rain.data) return ["–", due(RAIN_HOURS), t("overview.rainNoAnswer")];
  const { total_mm: total, max_chance_pct: chance, hours } = rain.data;
  return [t("overview.rainMm", { mm: total }), due(hours), t("overview.rainNote", { pct: chance })];
}

/** The "Floods recorded" tile: the area's own counts, or a dash when none was found in the years searched, or when no
 *  flood record has been collected for it. */
function floodTileText(history) {
  const counts = floodCounts(history);
  if (!counts && isSearched(history)) {
    return ["–", t("overview.floodsTile"), t("overview.floodsNoneFound", { from: history.first_year, to: history.last_year })];
  }
  if (!counts) return ["–", t("overview.floodsTile"), t("overview.floodsNone")];
  return [String(counts.recent), t("overview.floodsSince", { year: counts.recentFrom }), t("overview.floodsNote", { dated: counts.dated, since: counts.since })];
}

/** Counts the lead figure up from 0 on its first showing, as the map's water comes in: `show(n)` writes it. The live
 *  region waits (aria-busy), so it is read once, at the end. `isCurrent()` stops it when the flood size changes. */
function countUp(container, show, to, isCurrent) {
  container.setAttribute("aria-busy", "true");
  const start = performance.now();
  const step = (now) => {
    if (!isCurrent()) return container.removeAttribute("aria-busy");
    const k = Math.min(1, (now - start) / COUNT_MS);
    show(Math.round(to * (1 - (1 - k) ** 3)));
    if (k < 1) requestAnimationFrame(step);
    else container.removeAttribute("aria-busy");
  };
  requestAnimationFrame(step);
}

/** Builds the tiles into `container`. `data-tiles` says how many are in the grid (the CSS lays them out by it). */
export function createKpis(container, { history, areaName, premises }) {
  const tiles = { wet: kpiTile("wave", { hero: true, bar: true }), depth: kpiTile("store", { art: true }), flood: kpiTile("clock", { name: "flood" }), rain: kpiTile("rain") };
  tiles.flood.set(...floodTileText(history));
  container.replaceChildren(tiles.wet.node, tiles.depth.node, tiles.flood.node, tiles.rain.node);
  const showRain = (rain) => {
    tiles.rain.node.hidden = !rainShown(rain);
    container.dataset.tiles = tiles.rain.node.hidden ? "3" : "4";
  };
  showRain(undefined);
  let shownRp = null;
  return {
    /** How many businesses get water at this flood size, and how deep it typically is (the median over the wet ones). */
    setScenario(rp) {
      const wet = premises.filter((p) => band(p.depth_m[rp]));
      const typical = wet.length ? median(wet.map((p) => p.depth_m[rp])) : null;
      if (!premises.length) tiles.wet.set("–", t("overview.wetLabel", { area: areaName }), t("city.noneMappedTile"), 0);   // a section with none mapped
      else tiles.wet.set(t("overview.wetFigure", { wet: wet.length, total: premises.length }), t("overview.wetLabel", { area: areaName }), t("overview.wetNote", { rp }), wet.length / premises.length);
      if (shownRp === null && wet.length && motionOk()) {
        countUp(container, (n) => tiles.wet.setFigure(t("overview.wetFigure", { wet: n, total: premises.length })), wet.length, () => shownRp === rp);
      }
      shownRp = rp;
      tiles.depth.set(typical === null ? "–" : t("common.metres", { m: typical.toFixed(1) }), t("overview.typical"), t("overview.typicalNote"), 0);
      tiles.depth.setArt(typical === null ? null : miniGauge(typical));
    },
    setRain(rain) {
      showRain(rain);
      if (rainShown(rain)) tiles.rain.set(...rainText(rain));
    },
  };
}
