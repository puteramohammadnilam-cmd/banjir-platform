// The new map's search box (map.html): the shops of the area by name (its index) and, in a city split into sections,
// its sections by name, by another name the area's data gives them, or by the area's word for a section in either
// language (pick.js sectionFinder, as the old page's search). A pick opens the shop or the section on the map.
import { h } from "./dom.js";
import { dataWord, t } from "./i18n.js";
import { searchIndex, searchSections } from "./map-gl-data.js";
import { sectionFinder } from "./pick.js";

/** `area` is the area's data, `sections` a city's (else []), `index` its shops' lean list; sectionName(id) names a
 *  section; onShop(entry) and onSection(id) open a pick. */
export function wireSearch({ input, box, area, sections, index, sectionName, onShop, onSection }) {
  const finder = sections.length ? sectionFinder(sections, area.aliases ?? [], area.section_word, area.name) : null;
  const word = dataWord(area.section_word);
  const close = () => { box.hidden = true; };
  const pick = (open, text) => () => { close(); input.value = text; open(); };
  input.addEventListener("input", () => {
    const places = searchSections(finder, input.value).map(({ text, section }) => h("button", { type: "button", class: "mg-hit-section",
      onclick: pick(() => onSection(section), sectionName(section)) }, sectionName(section), h("small", {}, text && !text.startsWith(sectionName(section))
      ? text : t("mg.sectionHit", { word, area: area.name }))));
    const shops = searchIndex(index, input.value).map((entry) => h("button", { type: "button", onclick: pick(() => onShop(entry), entry.name) },
      entry.name, h("small", {}, sectionName(entry.section))));
    const hits = [...places, ...shops];
    box.replaceChildren(...(hits.length ? hits : [h("p", { class: "mg-muted mg-small" }, t("mg.noMatch"))]));
    box.hidden = input.value.trim().length < 2;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || box.hidden) return;
    event.stopPropagation();   // the first Escape closes the list, not the place card
    close();
  });
  input.closest(".mg-search").addEventListener("focusout", (event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) close();
  });
}
