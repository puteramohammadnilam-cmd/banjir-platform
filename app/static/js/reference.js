// The Reference tab's "On this page" list. Each button scrolls to its section and puts focus on the section's heading
// (no #fragment: the page keeps a picked point there). A section the area has no data for is hidden, and so is its button.

const reducedMotion = () => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;

/** Buttons in `nav` with data-jump="<heading id>" jump to that heading. */
export function wireReferenceNav(nav) {
  if (!nav) return;   // a page without the Reference tab
  nav.addEventListener("click", (event) => {
    const heading = document.getElementById(event.target.closest?.("[data-jump]")?.getAttribute("data-jump") ?? "");
    if (!heading) return;
    heading.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
    heading.focus({ preventScroll: true });
  });
}

/** Hide the buttons whose section is hidden. `sectionOf(id)` gives a heading's section (closest("section") in the page). */
export function syncReferenceNav(items, sectionOf) {
  for (const { item, target } of items) item.hidden = Boolean(sectionOf(target)?.hidden);
}
