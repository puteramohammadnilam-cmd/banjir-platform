// The Reference tab's cards that come from the area's data: the notes on its map's data, its past flood losses to
// business premises, and how its flood index is worked out. Both the old page (overview.js) and the new map's Reference
// panel (map-gl-reference.js) fill them; the cards' markup is the same in index.html and map.html.
import { h, ringgit } from "./dom.js";
import { numberLocale, t } from "./i18n.js";
import { methodBody, showsScore } from "./susceptibility.js";

const $ = (id) => document.getElementById(id);

/** A card of [key, text] notes, each under its heading; hidden when the area has none of them. */
export function listNotes(element, card, notes) {
  const shown = notes.filter(([, text]) => text);
  element.replaceChildren(...shown.flatMap(([key, text]) => [h("h3", { class: "small-heading" }, t(key)), h("p", {}, text)]));
  card.hidden = !shown.length;
}

// From RM 10 million a loss is said in millions, one decimal; below that in full, so RM 1,049,000 keeps its 49,000.
const MILLIONS_FROM_RM_THOUSAND = 10_000;
/** A loss in RM thousand, as people read it: "RM 396.4 million", "RM 1,049,000", or none recorded. */
export const lossWords = (thousand) => (thousand === 0 ? t("losses.none")
  : thousand >= MILLIONS_FROM_RM_THOUSAND
    ? t("losses.million", { n: (thousand / 1000).toLocaleString(numberLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) })
    : ringgit(thousand * 1000));

/** The Reference tab's card of past flood losses to business premises, from the area's config (`losses`), with its note
 *  and source; hidden for an area that has none. Place names come from the config, never from the page's strings. */
export function renderLosses(losses) {
  $("losses-card").hidden = !losses;
  if (!losses) return;
  const head = h("tr", {}, h("th", { scope: "col" }, t("losses.year")), losses.places.map((place) => h("th", { scope: "col" }, place)));
  const rows = losses.years.map((row) => h("tr", { class: row.rm_thousand.every((v) => v === 0) ? "is-none" : null },
    h("th", { scope: "row" }, String(row.year)), row.rm_thousand.map((value) => h("td", {}, lossWords(value)))));
  $("losses-body").replaceChildren(
    h("div", { class: "table-scroll" }, h("table", { class: "loss-table losses-table" },
      h("caption", { class: "visually-hidden" }, t("losses.caption")), h("thead", {}, head), h("tbody", {}, rows))),
    h("p", {}, losses.note), h("p", { class: "fineprint" }, losses.source));
}

/** "How these are worked out" (`details`, its words in `body`), where the area has the index's method or layer. */
export function renderMethod(details, body, area, { word = null } = {}) {
  const method = area.index_method ?? null;
  const layer = area.layers?.flash_flood ?? null;
  details.hidden = !method && !layer;
  body.replaceChildren(...(details.hidden ? [] : methodBody(method, { showScore: showsScore(method), word, credit: layer?.credit ?? null, squareM: layer?.square_m ?? 30 })));
}


/** The three cards for `area` (its config, or a section's page area), with the city's word for a section. */
export function fillReferenceCards(area, { word = null } = {}) {
  listNotes($("map-note"), $("map-notes-card"), [["overview.noteDepths", area.notes?.depths], ["overview.noteShelters", area.notes?.shelters],
    ["overview.noteSections", area.notes?.sections], ["overview.noteBusinesses", area.notes?.businesses]]);
  renderLosses(area.losses);
  renderMethod($("index-method"), $("index-method-body"), area, { word });
}
