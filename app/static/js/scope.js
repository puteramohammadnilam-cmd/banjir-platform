// The scope bar on "Area overview": which area the page shows. The way in to any point is the search's neighbour above
// it (index.html, #hero-point) and the map's own button.
import { h } from "./dom.js";
import { t } from "./i18n.js";

/** An "Area" select with one option per listed area (its display name) and an "Open" button. Another area is another
 *  page, so choosing one in the select only chooses it: Open calls onArea(areaId) and the page navigates, and a hint on
 *  show says so (a select that navigated on change would take a keyboard user away at the first arrow key, WCAG
 *  3.2.2). Open is off while the area chosen is the one on show. */
export function createScopeBar(slot, { areas, areaId, onArea }) {
  const select = h("select", { id: "area-select", class: "field", "aria-describedby": "area-hint" },
    areas.map((area) => h("option", { value: area.id }, area.display_name)));
  const openButton = h("button", {
    type: "button", class: "btn btn-secondary", "aria-describedby": "area-hint",
    onclick: () => { if (select.value !== areaId) onArea(select.value); },
  }, t("scope.open"));
  const sync = () => { openButton.disabled = select.value === areaId; };
  select.addEventListener("change", sync);
  select.value = areaId;
  sync();
  // coming back to this page from the browser's back-forward cache must show the area it holds, not the one picked on the way out
  window.addEventListener("pageshow", (event) => { if (event.persisted) { select.value = areaId; sync(); } });
  slot.replaceChildren(
    h("div", { class: "scope-area" },
      h("label", { class: "scope-label", for: "area-select" }, t("scope.area")),
      h("div", { class: "scope-pick" }, select, openButton)),
    h("p", { id: "area-hint", class: "fineprint scope-hint" }, t("scope.hint")));
}
