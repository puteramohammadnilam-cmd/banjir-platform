// The Reference tab on the new map (map.html), in its sheet: the old interface's markup, copied into map.html with its
// data-i18n words, its "On this page" jumps (reference.js) and its three cards from the area's data (reference-cards.js),
// for the section on show or the whole area. Its buttons to other tabs (data-goto) open them in the sheet.
import { fillReferenceCards } from "./reference-cards.js";
import { syncReferenceNav, wireReferenceNav } from "./reference.js";

/** `panel` is #panel-reference; scope() as map-gl-area.js has it ({areaId, sectionId, page, word}); goto(tab) opens a tab. */
export function createReferencePanel({ panel, scope, goto }) {
  wireReferenceNav(panel.querySelector(".ref-nav"));
  panel.addEventListener("click", (event) => {
    const to = event.target.closest?.("[data-goto]");
    if (!to) return;
    event.preventDefault();
    goto(to.getAttribute("data-goto"));
  });
  const jumps = [...panel.querySelectorAll(".ref-nav [data-jump]")]
    .map((button) => ({ item: button.closest("li"), target: button.getAttribute("data-jump") }));
  let shownKey = null;
  return {
    render() {
      const now = scope();
      const key = `${now.areaId}|${now.sectionId ?? ""}`;
      if (key === shownKey) return;
      shownKey = key;
      fillReferenceCards(now.page, { word: now.word });
      syncReferenceNav(jumps, (id) => document.getElementById(id)?.closest("section"));   // a card the area has no data for, and its jump, hide
    },
  };
}
