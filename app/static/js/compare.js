// "Compare places" on My business: for someone choosing between shop lots, up to three places (businesses or points)
// side by side, with the same modelled figures each one's own page shows. Kept for this visit only, in the page.
import { SCENARIOS, band, h } from "./dom.js";
import { formatNumber, t } from "./i18n.js";
import { DEFAULT_RP } from "./pick.js";

export const MAX_COMPARED = 3;

/** The ids after adding one: no repeats, the newest last, the oldest dropped past MAX_COMPARED. */
export const addCompared = (ids, id) => (ids.includes(id) ? ids : [...ids, id].slice(-MAX_COMPARED));

const depth = (value) => (band(value) ? t("common.metres", { m: value.toFixed(2) }) : t("compare.noWater"));
const nameOf = (place) => (place.is_point ? t("compare.square", { lat: place.lat.toFixed(5), lon: place.lon.toFixed(5) }) : place.name);
const roadWater = (place) => (place.road ? depth(place.road.depth_m[DEFAULT_RP]) : "–");
const shelterOf = (place) => (place.shelter
  ? t("compare.shelter", { name: place.shelter.name, distance: formatNumber(place.shelter.distance_m) }) : t("compare.noShelter"));

function table(places, onOpen) {
  const heads = [t("compare.colPlace"), ...SCENARIOS.map((rp) => t("common.rpYears", { rp })), t("compare.colRoad", { rp: DEFAULT_RP }), t("compare.colShelter")];
  return h("div", { class: "table-scroll" }, h("table", { class: "loss-table compare-table" },
    h("caption", { class: "visually-hidden" }, t("compare.caption")),
    h("thead", {}, h("tr", {}, heads.map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, places.map((place) => h("tr", {},
      h("th", { scope: "row" }, h("button", { type: "button", class: "btn btn-link", onclick: () => onOpen(place) }, nameOf(place))),
      ...SCENARIOS.map((rp) => h("td", {}, depth(place.depth_m[rp]))),
      h("td", {}, roadWater(place)), h("td", {}, shelterOf(place)))))));
}

/** The one place saved so far, said, with what to do next. When it is not the place on show it can be taken out here;
 *  when it is, the main button does that. */
function saved(place, isCurrent, onRemove) {
  const name = nameOf(place);
  return h("p", { class: "hint compare-saved" }, t(isCurrent ? "compare.added" : "compare.addedOther", { name }), " ",
    !isCurrent && h("button", { type: "button", class: "btn btn-link", onclick: () => onRemove(place.id) }, t("compare.removeOne")));
}

/** The card. render({current, compared}) with the place on show and the compared places, in order; with no place on
 *  show (nothing picked yet) it is left empty. onAdd(id) and onRemove(id) change the list; onOpen(place) shows a
 *  compared place. */
export function createCompareCard({ onAdd, onRemove, onOpen }) {
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
      const isIn = compared.some((place) => place.id === current.id);
      const toggle = isIn
        ? h("button", { type: "button", class: "btn btn-secondary", onclick: () => onRemove(current.id) }, t("compare.remove"))
        : h("button", { type: "button", class: "btn btn-secondary", onclick: () => onAdd(current.id) }, t("compare.add"));
      const hint = !isIn && compared.length >= MAX_COMPARED ? t("compare.full", { max: MAX_COMPARED }) : null;
      const hadFocus = node.contains(document.activeElement);   // the button is made again: give focus to the new one
      node.replaceChildren(...[
        h("h2", { id: "compare-heading", class: "small-heading" }, t("compare.heading")),
        h("p", { class: "hint" }, t("compare.hint")),
        toggle,
        hint && h("p", { class: "hint" }, hint),
        compared.length === 1 && saved(compared[0], isIn, onRemove),
        compared.length >= 2 && table(compared, onOpen),
      ].filter(Boolean));
      if (hadFocus) toggle.focus();
    },
  };
}
