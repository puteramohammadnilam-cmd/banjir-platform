// "Compare places" on My business: for someone choosing between shop lots, up to three places (businesses or points)
// side by side, with the same modelled figures each one's own page shows. Kept for this visit only, in the page.
// It walks the owner through it: a step line says what to do next, "Find another place" goes to the search, and once
// two are in, one line says which gets the least and the most water, and the least in each column is marked.
import { SCENARIOS, band, h } from "./dom.js";
import { formatNumber, t } from "./i18n.js";
import { DEFAULT_RP } from "./pick.js";

export const MAX_COMPARED = 3;

/** The ids after adding one: no repeats, the newest last, the oldest dropped past MAX_COMPARED. */
export const addCompared = (ids, id) => (ids.includes(id) ? ids : [...ids, id].slice(-MAX_COMPARED));

const water = (value) => (band(value) ? value : 0);   // the build stores a dry square as null (raster.depth_value)
const depth = (value) => (band(value) ? t("common.metres", { m: value.toFixed(2) }) : t("compare.noWater"));
const nameOf = (place) => (place.is_point ? t("compare.square", { lat: place.lat.toFixed(5), lon: place.lon.toFixed(5) }) : place.name);
const roadWater = (place) => (place.road ? depth(place.road.depth_m[DEFAULT_RP]) : t("compare.noRoad"));
const shelterOf = (place) => (place.shelter
  ? t("compare.shelter", { name: place.shelter.name, distance: formatNumber(place.shelter.distance_m) }) : t("compare.noShelter"));

/** One line that answers the question for the biggest flood size: where the least water is, and where the most. */
export function verdict(places, rp = DEFAULT_RP) {
  const depths = places.map((place) => water(place.depth_m[rp]));
  const low = Math.min(...depths);
  const high = Math.max(...depths);
  if (high === 0) return t("compare.verdictDry", { rp });
  if (low === high) return t("compare.verdictSame", { rp, m: depth(high) });
  const named = (value) => places.filter((_, i) => depths[i] === value).map(nameOf).join(", ");
  return t("compare.verdict", { rp, least: named(low), lessM: depth(low), most: named(high), moreM: depth(high) });
}

/** A cell with the least water of its row (and not all the same) says so in words, not only by its look. */
function depthCell(value, least, isSpread) {
  const isLeast = isSpread && water(value) === least;
  return h("td", { class: isLeast ? "is-least" : null }, depth(value), isLeast && h("span", { class: "least-tag" }, t("compare.least")));
}

/** The heading of a place's column: its name, which opens it, and "On show" for the place on show. */
const placeHead = (place, { current, onOpen }) => h("th", { scope: "col", class: place.id === current.id ? "is-current" : null },
  h("button", { type: "button", class: "btn btn-link", onclick: () => onOpen(place) }, nameOf(place)),
  place.id === current.id && h("span", { class: "here-tag" }, t("compare.onShow")));

/** A row of water at the places for one flood size, the least marked. */
function waterRow(places, rp) {
  const depths = places.map((place) => water(place.depth_m[rp]));
  const least = Math.min(...depths);
  const isSpread = least !== Math.max(...depths);
  return h("tr", {}, h("th", { scope: "row" }, t("compare.colWater", { rp })),
    places.map((place) => depthCell(place.depth_m[rp], least, isSpread)));
}

/** Places across the top and what is compared down the side, so three places fit a phone. */
function table(places, handlers) {
  const line = (label, cell) => h("tr", {}, h("th", { scope: "row" }, label), places.map((place) => h("td", {}, cell(place))));
  const remove = (place) => h("button", { type: "button", class: "btn btn-link compare-remove",
    "aria-label": t("compare.removeNamed", { name: nameOf(place) }), onclick: () => handlers.onRemove(place.id) }, t("compare.removeOne"));
  return h("div", { class: "table-scroll" }, h("table", { class: "loss-table compare-table" },
    h("caption", { class: "visually-hidden" }, t("compare.caption")),
    h("thead", {}, h("tr", {}, h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, t("compare.colPlace"))), places.map((place) => placeHead(place, handlers)))),
    h("tbody", {}, SCENARIOS.map((rp) => waterRow(places, rp)),
      line(t("compare.colRoad", { rp: DEFAULT_RP }), roadWater), line(t("compare.colShelter"), shelterOf),
      line(h("span", { class: "visually-hidden" }, t("compare.colRemove")), remove))));
}

/** What to do next, as a numbered step, and the buttons for it: add the place on show, or find another one. */
function nextStep(current, compared, { onAdd, onRemove, onFind }) {
  const isIn = compared.some((place) => place.id === current.id);
  const count = compared.length;
  const key = count === 0 ? "compare.step1" : count === 1 ? (isIn ? "compare.step2Find" : "compare.step2Add")
    : isIn ? (count < MAX_COMPARED ? "compare.stepMore" : "compare.stepFull") : "compare.stepAddMore";
  const add = h("button", { type: "button", class: "btn btn-primary", onclick: () => onAdd(current.id) }, t("compare.add"));
  const remove = h("button", { type: "button", class: "btn btn-secondary", onclick: () => onRemove(current.id) }, t("compare.remove"));
  const canFind = count < MAX_COMPARED;
  // the next thing to do is the main button: find another place once this one is in, else add this one
  const find = h("button", { type: "button", class: `btn ${isIn ? "btn-primary" : "btn-secondary"}`, onclick: onFind }, t("compare.find"));
  return {
    focusable: isIn ? remove : add,
    nodes: [
      h("p", { class: "compare-step" }, t(key, { name: count ? nameOf(compared[0]) : "", max: MAX_COMPARED })),
      h("div", { class: "compare-actions" }, ...(isIn ? [canFind && find, remove] : [add, count > 0 && canFind && find])),
      !isIn && count >= MAX_COMPARED && h("p", { class: "hint" }, t("compare.full", { max: MAX_COMPARED })),
    ],
  };
}

/** The card. render({current, compared}) with the place on show and the compared places, in order; with no place on
 *  show (nothing picked yet) it is left empty. onAdd(id) and onRemove(id) change the list; onOpen(place) shows a
 *  compared place; onFind() goes to the search to pick another one. */
export function createCompareCard({ onAdd, onRemove, onOpen, onFind = () => {} }) {
  const node = h("section", { class: "surface compare-card", "aria-labelledby": "compare-heading" });
  let shownKey = null;
  return {
    node,
    render({ current, compared }) {
      if (!current) {
        node.replaceChildren();
        shownKey = null;
        return;
      }
      const key = [current.id, ...compared.map((place) => place.id)].join("|");
      if (key === shownKey) return;   // nothing it shows changed (rain or a listing arriving): keep focus where it is
      shownKey = key;
      const step = nextStep(current, compared, { onAdd, onRemove, onFind });
      const hadFocus = node.contains(document.activeElement);   // the buttons are made again: give focus to the new one
      node.replaceChildren(...[
        h("h2", { id: "compare-heading", class: "small-heading" }, t("compare.heading")),
        h("p", { class: "hint" }, t("compare.hint")),
        ...step.nodes,
        // the one saved place, when it is not the one on show (whose own button takes it out)
        compared.length === 1 && compared[0].id !== current.id && h("button", { type: "button", class: "btn btn-link compare-saved",
          onclick: () => onRemove(compared[0].id) }, t("compare.removeNamed", { name: nameOf(compared[0]) })),
        compared.length >= 2 && h("p", { class: "compare-verdict" }, verdict(compared)),
        compared.length >= 2 && table(compared, { current, onOpen, onRemove }),
        compared.length >= 2 && h("p", { class: "fineprint" }, t("compare.tableNote")),
      ].filter(Boolean));
      if (hadFocus) step.focusable.focus({ preventScroll: true });
    },
  };
}
