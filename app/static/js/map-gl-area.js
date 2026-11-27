// The Area overview's cards on the new map (map.html), in its sheet: the old interface's figures (kpis.js), relief
// centres open now (evacuation.js), the tide (tide.js), the next 5 days (outlook.js), the flood record (history.js),
// the table of a city's sections (section-table.js) and the printable area summary (area-report.js), the same code.
// They are about the section on show, or the whole area. What comes from outside is asked for only while the panel is
// on show, once per area or section for the visit: the rain and the next 5 days (Google Weather has a free monthly
// cap), JKM's open centres and the tide.
import * as api from "./api.js";
import { buildAreaReport } from "./area-report.js";
import { h } from "./dom.js";
import { createEvacuation } from "./evacuation.js";
import { renderHistory } from "./history.js";
import { dataWord, dateLocale, t } from "./i18n.js";
import { createKpis } from "./kpis.js";
import { createOutlook } from "./outlook.js";
import { printSheet } from "./place-data.js";
import { createSectionTable } from "./section-table.js";
import { showsScore } from "./susceptibility.js";
import { createTide } from "./tide.js";

const keyOf = (now) => `${now.areaId}|${now.sectionId ?? ""}`;
const settled = (promise, shape) => promise.then(shape, () => ({ error: true }));

/** `panel` is #panel-area. scope() is what the cards are about now: {areaId, sectionId (or null), page (the area,
 *  or the section's page area), premises (with their depths), sections and word (a city's; else [] and null)}.
 *  `status` is GET /api/status's answer and areas() resolves the listed areas, for the chooser. `on`: section(id) opens
 *  a section on the map, wholeArea() goes back from a section to the whole area, sectionHref(id) and areaHref(id) are
 *  the links for them, and redraw() draws the panel again when an answer comes. */
export function createAreaPanel({ panel, scope, status, areas, on }) {
  const title = h("h1", { class: "view-title" });
  const back = h("p", { class: "small" });
  const chooser = h("p", { class: "mg-area-pick" });
  const kpiBox = h("div", { class: "kpis", "aria-live": "polite" });
  const evac = h("section", { class: "surface evac", "aria-labelledby": "evacuation-heading", hidden: true });
  const tide = h("section", { class: "surface tide", "aria-labelledby": "tide-heading", hidden: true });
  const outlook = h("section", { class: "surface outlook", "aria-labelledby": "outlook-heading" });
  const history = h("section", { class: "surface", "aria-labelledby": "history-heading" });
  const tableHeading = h("h2", { id: "sections-heading" });
  const tableLead = h("p", { class: "muted small" });
  const tableSlot = h("div", { class: "table-scroll sections-scroll" });
  const table = h("section", { class: "surface sections-surface", "aria-labelledby": "sections-heading", hidden: true },
    tableHeading, tableLead, tableSlot);
  const print = h("section", { class: "surface area-print", "aria-labelledby": "area-print-heading" },
    h("h2", { id: "area-print-heading", class: "small-heading" }, t("overview.printHeading")),
    h("p", { class: "muted small" }, t("overview.printLead")),
    h("button", { type: "button", class: "btn btn-secondary", onclick: () => printSummary() }, t("overview.printButton")));
  panel.replaceChildren(h("header", { class: "view-head" }, h("p", { class: "kicker" }, t("tab.overview")), title, back, chooser),
    kpiBox, h("div", { class: "overview-live" }, evac, tide, outlook, history), table, print);
  const cards = { evacuation: createEvacuation(evac), tide: createTide(tide), outlook: createOutlook(outlook) };
  const answers = new Map();   // by area or section: {rain, evacuation, tide, outlook}
  let shown = { key: null, kpis: null, sections: null };

  // a link in the sections table opens that section on this map, not a new page
  tableSlot.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    const id = link && new URL(link.href, globalThis.location?.href).searchParams.get("section");
    if (!id || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    on.section(id);
  });

  /** The answers for `now`, asked for once: a later redraw shows each as it comes. */
  function load(now, key) {
    if (answers.has(key)) return answers.get(key);
    // the old page's first states (pick.js initialState): each card shows it is loading until its answer comes
    const got = { rain: status?.maps_ready ? { configured: true, busy: true } : { configured: false }, evacuation: { busy: true }, tide: { busy: true },
      outlook: { busy: true } };
    answers.set(key, got);
    const keep = (name) => (value) => {
      got[name] = value;
      on.redraw();
    };
    if (status?.maps_ready) {
      api.getRain(now.areaId, now.sectionId).then(({ configured, rain, capped, until }) => keep("rain")({ configured, data: rain, capped: Boolean(capped), until }),
        () => keep("rain")({ configured: true, error: true }));
    }
    settled(api.getEvacuation(now.areaId, now.sectionId), ({ centres }) => ({ data: centres })).then(keep("evacuation"));
    settled(api.getTide(now.areaId), ({ tide: found }) => ({ data: found })).then(keep("tide"));
    settled(api.getOutlook(now.areaId, now.sectionId), ({ outlook: found }) => ({ data: found })).then(keep("outlook"));
    return got;
  }

  /** What changes with the area or section: the title, the way back to the whole area, the figures, the record and
   *  the sections table (a city's, on the whole city only). */
  function drawScope(now) {
    title.textContent = now.page.display_name ?? now.page.name;
    back.replaceChildren(...(now.sectionId ? [h("button", { type: "button", class: "btn btn-link", onclick: on.wholeArea },
      t("mg.allArea", { area: now.page.city_name ?? now.page.name }))] : []));
    shown.kpis = createKpis(kpiBox, { history: now.page.history, areaName: now.page.name, premises: now.premises });
    renderHistory(history, now.page);
    const isCity = now.sections.length > 0 && !now.sectionId;
    table.hidden = !isCity;
    shown.sections = isCity ? createSectionTable(tableSlot, { sections: now.sections, word: now.word, hrefOf: on.sectionHref,
      showScore: showsScore(now.page.index_method) }) : null;
    if (isCity) tableHeading.textContent = t("sections.heading", { word: dataWord(now.word, { lower: true }) });
  }

  function drawChooser(list) {
    if (list.length < 2) return;
    const now = scope();
    const select = h("select", { "aria-label": t("mg.areaPick"), onchange: (event) => globalThis.location.assign(on.areaHref(event.target.value)) },
      list.map((area) => h("option", { value: area.id, selected: area.id === now.areaId }, area.display_name ?? area.name)));
    chooser.replaceChildren(h("label", {}, t("mg.areaPick"), " ", select));
  }
  areas().then(drawChooser, () => {});

  function printSummary() {
    const now = scope();
    const isCity = now.sections.length > 0 && !now.sectionId;
    printSheet(buildAreaReport({ area: now.page, premises: now.premises, sections: isCity ? now.sections : null, word: now.word,
      date: new Date().toLocaleDateString(dateLocale(), { day: "numeric", month: "short", year: "numeric" }) }));
  }

  return {
    /** Draws the panel for the flood size on show; called only while it is on show. */
    render(rp) {
      const now = scope();
      const key = keyOf(now);
      if (key !== shown.key) {
        shown = { ...shown, key };
        drawScope(now);
      }
      const got = load(now, key);
      shown.kpis.setScenario(rp);
      shown.kpis.setRain(got.rain);
      if (shown.sections) {
        shown.sections.show(rp);
        tableLead.textContent = t("sections.lead", { rp, word: dataWord(now.word, { lower: true }) });
      }
      cards.evacuation.set(got.evacuation);
      cards.tide.set(got.tide);
      cards.outlook.set(got.outlook);
    },
  };
}
