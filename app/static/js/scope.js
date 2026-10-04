// The scope bar on "Area overview": which area the page shows, and in a city split into sections which section (or the
// whole city). The way in to any point is the search's neighbour above it (index.html, #hero-point) and the map's own
// button.
import { h } from "./dom.js";
import { dataWord, t } from "./i18n.js";

/** A labelled select with its "Open" button. Choosing only chooses: Open calls onOpen(value) and the page navigates,
 *  and the hint says so (a select that navigated on change would take a keyboard user away at the first arrow key, WCAG
 *  3.2.2). Open is off while the choice is the one on show. Gives back what puts the select back on `current`. */
function picker({ id, label, options, current, onOpen }) {
  const select = h("select", { id, class: "field", "aria-describedby": "area-hint" },
    options.map(([value, text]) => h("option", { value }, text)));
  const openButton = h("button", {
    type: "button", class: "btn btn-secondary", "aria-describedby": "area-hint",
    onclick: () => { if (select.value !== current) onOpen(select.value); },
  }, t("scope.open"));
  const sync = () => { openButton.disabled = select.value === current; };
  const reset = () => { select.value = current; sync(); };
  select.addEventListener("change", sync);
  reset();
  const node = h("div", { class: "scope-area" },
    h("label", { class: "scope-label", for: id }, label),
    h("div", { class: "scope-pick" }, select, openButton));
  return { node, reset };
}

/** The section picker of a city: the whole city first (unless the city opens on a default section and has no whole-city
 *  page), then its sections in the data's order. onSection(id) opens one, onSection(null) the whole city. */
function sectionPicker({ sections, sectionId, word, wholeCity, onSection }) {
  const options = [...(wholeCity ? [["", t("scope.wholeCity")]] : []), ...sections.map((section) => [section.id, section.name])];
  return picker({ id: "section-select", label: dataWord(word), options, current: sectionId ?? "", onOpen: (value) => onSection(value || null) });
}

/** An "Area" select with one option per listed area (its display name) and an "Open" button; another area is another
 *  page. A city split into sections (`sections` not empty) adds the section select, in the area's own `word` for a
 *  section, and on a section's page a plain link back to the whole city (cityHref, named "All of {cityName}"). */
export function createScopeBar(slot, { areas, areaId, onArea, sections = [], sectionId = null, word = null, wholeCity = true, onSection = () => {}, cityHref = null, cityName = "" }) {
  const area = picker({
    id: "area-select", label: t("scope.area"), options: areas.map((entry) => [entry.id, entry.display_name]), current: areaId, onOpen: onArea,
  });
  const section = sections.length ? sectionPicker({ sections, sectionId, word, wholeCity, onSection }) : null;
  // coming back to this page from the browser's back-forward cache must show what it holds, not what was picked on the way out
  window.addEventListener("pageshow", (event) => { if (event.persisted) { area.reset(); section?.reset(); } });
  const back = section && sectionId && cityHref ? h("a", { class: "scope-back", href: cityHref }, t("scope.allOf", { city: cityName })) : null;
  const hint = section ? t("scope.hintSections", { word: dataWord(word, { lower: true }) }) : t("scope.hint");
  slot.replaceChildren(...[area.node, section?.node, back].filter(Boolean), h("p", { id: "area-hint", class: "fineprint scope-hint" }, hint));
}
