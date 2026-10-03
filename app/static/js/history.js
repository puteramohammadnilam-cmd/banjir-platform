import { h, s } from "./dom.js";

// Floods reported at Taman Sri Muda, paraphrased from the sources named, with figures as printed there.
// `year` only places the dot on the strip. `account` marks a single person's undated memory.
export const FLOODS = [
  { when: "April 1995", year: 1995.25, what: "The area flooded. It was called the worst in 10 years at the time.", source: "Free Malaysia Today, opinion, 28 Dec 2021" },
  { when: "24 to 25 Dec 1995", year: 1995.98, what: "Seksyen 25 flooded, water a little over 1 m.", source: "DOSM newsletter, citing the New Straits Times; Free Malaysia Today, 1 Jan 2022" },
  { when: "2001", year: 2001.5, account: true, what: "One resident recalls her house was flooded for four days.", source: "Free Malaysia Today, 14 Apr 2025, one person's account" },
  { when: "17 Oct 2019", year: 2019.79, what: "The river rose over the bund and most homes and shops flooded, after more than 150 mm of rain.", source: "Sinar Harian, 18 Oct 2019" },
  { when: "29 Jan 2020", year: 2020.08, what: "Flash flood.", source: "Malaysia Gazette, 29 Jan 2020" },
  { when: "18 to 19 Dec 2021", year: 2021.96, what: "The big flood. Depth was reported as over six feet, and later as over 4 m. No survey was published.", source: "Malaysiakini, 21 Dec 2021; The Star, 6 Aug 2024" },
  { when: "24 Jan 2022", year: 2022.06, what: "Streets flooded 0.1 to 0.3 m.", source: "Rosmadi and others 2025, quoting MBSA's flood report for 2022" },
  { when: "20 Aug 2022", year: 2022.63, what: "Streets flooded 0.1 to 0.3 m.", source: "Rosmadi and others 2025, quoting MBSA's flood report for 2022" },
  { when: "8 Nov 2022", year: 2022.85, what: "Streets flooded 0.1 to 0.3 m.", source: "Rosmadi and others 2025, quoting MBSA's flood report for 2022" },
  { when: "11 Apr 2025", year: 2025.28, what: "About 700 houses flooded, knee to waist deep (0.5 to 1 m).", source: "Free Malaysia Today; Utusan Malaysia, 12 Apr 2025" },
];

const FIRST_YEAR = 1995;
const LAST_YEAR = 2026;
const RECENT_FROM = 2019;
const DOT_Y = 22;
const AXIS_Y = 30;

// Positions are percentages and the svg has no viewBox, so text keeps its real size on a phone.
const xOf = (year) => `${2 + ((year + 0.5 - FIRST_YEAR) / (LAST_YEAR - FIRST_YEAR)) * 96}%`;

function strip() {
  const byYear = new Map();   // one dot a year, with a count, so a narrow screen never piles dots on top of each other
  for (const flood of FLOODS) {
    const year = Math.floor(flood.year);
    const seen = byYear.get(year) ?? { count: 0, account: true };
    byYear.set(year, { count: seen.count + 1, account: seen.account && Boolean(flood.account) });
  }
  const dots = [...byYear].map(([year, { count, account }]) => s("g", {},
    s("circle", { class: account ? "flood-dot is-account" : "flood-dot", cx: xOf(year), cy: DOT_Y, r: 5 }),
    count > 1 && s("text", { class: "flood-count", x: xOf(year), y: DOT_Y - 9, "text-anchor": "middle" }, `×${count}`)));
  const ticks = [1995, 2000, 2005, 2010, 2015, 2020, 2025].map((year) =>
    s("text", { x: xOf(year), y: AXIS_Y + 16, "text-anchor": "middle" }, String(year)));
  return s("svg", { class: "flood-strip", height: AXIS_Y + 22, "aria-hidden": "true" },
    s("line", { class: "axis", x1: "1%", x2: "99%", y1: AXIS_Y, y2: AXIS_Y }), ticks, dots);
}

export function renderHistory(element) {
  const dated = FLOODS.filter((f) => !f.account);
  const recent = dated.filter((f) => f.year >= RECENT_FROM).length;
  element.replaceChildren(
    h("h2", { id: "history-heading" }, "Floods recorded here"),
    h("p", { class: "history-lead" }, h("strong", {}, `${dated.length} dated floods`), ` at Taman Sri Muda since ${FIRST_YEAR}, `,
      h("strong", {}, `${recent} of them since ${RECENT_FROM}`), "."),
    strip(),
    h("p", { class: "fineprint" }, "The map shows river floods expected once in 10 years or less often. Smaller, more frequent floods ",
      "and flash floods from heavy rain are not on it. A hollow dot is one resident's memory, not a dated report."),
    h("details", {}, h("summary", {}, "The floods and their sources"),
      h("ol", { class: "flood-list" }, FLOODS.map((f) => h("li", {},
        h("strong", {}, f.when), ` ${f.what} `, h("span", { class: "muted" }, f.source))))),
  );
}
