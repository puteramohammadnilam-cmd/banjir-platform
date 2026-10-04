// A city's sections in a sortable table: the choropleth's figures (choropleth.js) for the keyboard and screen readers,
// and a ranked list for everyone. Each name is a real link to its section's page. The header buttons sort, set
// aria-sort on their column alone and say the new order in a live region; the figures follow the flood size on show.
// Sections with `indexes` add flash flood potential and, once allowed, our score (susceptibility.js).
import { h } from "./dom.js";
import { dataWord, t } from "./i18n.js";
import { FLASH_METRIC, SCORE_METRIC, shareClass, shareOf, shareText } from "./choropleth.js";
import { highShare, oneDecimal, scoreOf, swatchStyle } from "./susceptibility.js";

const FIRST_ORDER = { name: "ascending", share: "descending", wet: "descending", flash: "descending", score: "descending" };   // a figure's first press: biggest first

/** One row per section, in the data's order (`order`), for flood size `rp`: {id, name, order, share, wet, total, flash,
 *  score}, the last two null where not worked out. */
export function sectionRows(sections, rp) {
  return sections.map((section, order) => ({
    id: section.id, name: section.name, order, share: shareOf(section, rp),
    wet: section.counts?.wet_businesses?.[rp] ?? 0, total: section.counts?.businesses ?? 0,
    flash: highShare(section), score: scoreOf(section),
  }));
}

/** A new list sorted by `key` ("name" is the data's own order, 1-36 then U1-U20) in `direction`; ties keep the data's
 *  order and a figure not worked out (null) goes last, whichever way the list runs. */
export function sortRows(rows, key, direction) {
  const sign = direction === "ascending" ? 1 : -1;
  const value = key === "name" ? (row) => row.order : (row) => row[key];
  return [...rows].sort((a, b) => {
    const [x, y] = [value(a), value(b)];
    const missing = (x === null) - (y === null);
    return missing || (x === null ? 0 : sign * (x - y)) || a.order - b.order;
  });
}

const headerWords = (word) => ({
  name: dataWord(word), share: t("sections.colSquares"), wet: t("sections.colBusinesses"), flash: t("sections.colFlash"), score: t("sections.colScore"),
});

/** A figure with its class's swatch, or "not worked out". */
const indexCell = (value, metric, text) => (value === null
  ? h("td", { class: "index-cell muted" }, t("sections.notWorkedOut"))
  : h("td", { class: "index-cell" }, h("span", { class: "choro-swatch", style: swatchStyle(metric.classes[metric.class(value)]), "aria-hidden": "true" }), text(value)));
const indexCells = (row, columns) => [
  columns.includes("flash") && indexCell(row.flash, FLASH_METRIC, shareText),
  columns.includes("score") && indexCell(row.score, SCORE_METRIC, oneDecimal),
];

const businessesText = ({ wet, total }) => (total ? t("overview.wetFigure", { wet, total }) : t("sections.noneMapped"));

function rowNode(row, { hrefOf, onHighlight, columns }) {
  const share = Number(row.share.toFixed(3));
  const tr = h("tr", {},
    h("th", { scope: "row" }, h("a", { href: hrefOf(row.id) }, row.name)),
    h("td", {}, h("span", { class: "share-cell" },
      h("span", { class: "share-track", "aria-hidden": "true" },
        h("span", { class: `share-bar sq-${shareClass(row.share)}`, style: `--share: ${share}`, "aria-hidden": "true" })),
      h("span", { class: "share-figure" }, shareText(row.share)))),
    h("td", { class: "wet-cell" }, businessesText(row)),
    indexCells(row, columns));
  if (onHighlight) {
    tr.addEventListener("mouseenter", () => onHighlight(row.id));
    tr.addEventListener("mouseleave", () => onHighlight(null));
    tr.addEventListener("focusin", () => onHighlight(row.id));
    tr.addEventListener("focusout", () => onHighlight(null));
  }
  return tr;
}

/** The river model's columns, then flash flood potential and our score (when showScore) where any section has them. */
const columnsOf = (sections, showScore) => ["name", "share", "wet",
  ...(sections.some((section) => highShare(section) !== null) ? ["flash"] : []),
  ...(showScore && sections.some((section) => scoreOf(section) !== null) ? ["score"] : [])];

/** The table in `slot`. `word` is the area's word for a section ({en, ms}); hrefOf(id) the link to a section's page;
 *  onHighlight(id | null) lifts that section on the map while its row is hovered or focused. show(rp) draws the rows for
 *  a flood size, in the order the reader chose (biggest share first until they choose). */
export function createSectionTable(slot, { sections, word, hrefOf, onHighlight = null, showScore = false }) {
  const words = headerWords(word);
  const columns = columnsOf(sections, showScore);
  let sort = { key: "share", direction: "descending" };
  let rp = null;
  const announcer = h("p", { class: "visually-hidden", "aria-live": "polite" });
  const body = h("tbody");
  const heads = columns.map((key) => h("th", { scope: "col", class: `col-${key}` },
    h("button", { type: "button", class: "sort-button", onclick: () => sortBy(key) }, words[key])));
  slot.replaceChildren(
    h("table", { class: "section-table" },
      h("caption", { id: "sections-caption", class: "visually-hidden" }, t("sections.caption", { word: dataWord(word, { lower: true }) })),
      h("thead", {}, h("tr", {}, heads)), body),
    announcer);

  function draw() {
    heads.forEach((th, i) => {
      if (columns[i] === sort.key) th.setAttribute("aria-sort", sort.direction);
      else th.removeAttribute("aria-sort");
    });
    body.replaceChildren(...sortRows(sectionRows(sections, rp), sort.key, sort.direction).map((row) => rowNode(row, { hrefOf, onHighlight, columns })));
  }

  function sortBy(key) {
    const direction = key === sort.key ? (sort.direction === "ascending" ? "descending" : "ascending") : FIRST_ORDER[key];
    sort = { key, direction };
    draw();
    announcer.textContent = t("sections.sorted", { column: words[key], order: t(`sections.${direction}`) });
  }

  return {
    show(next) {
      rp = next;
      draw();
    },
  };
}
