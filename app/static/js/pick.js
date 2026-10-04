// Picking the place to show. Nothing is picked for anyone: the page starts on the place its link names, else the
// business this browser last picked in the area, else none, and My business and Flood cost then say how to pick one
// (the empty state). The finder forms, the header's and the Area overview's own, open a business by its name, or show
// the businesses a name could mean. Only the elements handed in are touched, so node can test all of it
// (tests/pick.test.mjs).
import { h, icon, roadName } from "./dom.js";
import { lang, t } from "./i18n.js";

export const DEFAULT_RP = "100";
const STORE_KEY = "banjir-check-place";   // {[areaId]: placeId}: the business last picked in each area, in this browser

/** Storage can be missing, blocked or full (a private window), or hold anything: what is not a plain object reads as
 *  nothing remembered. */
function readPicks() {
  try {
    const picks = JSON.parse(globalThis.localStorage?.getItem(STORE_KEY) ?? "null");
    return picks && typeof picks === "object" && !Array.isArray(picks) ? picks : {};
  } catch {
    return {};
  }
}

/** Remembers a business someone picked (by name, on the map or in the list) for their next visit to the area. */
export function rememberPlace(areaId, placeId) {
  try {
    globalThis.localStorage?.setItem(STORE_KEY, JSON.stringify({ ...readPicks(), [areaId]: placeId }));
  } catch {
    // not remembered: the next visit starts with nothing picked, as a first visit does
  }
}

/** The business last picked in the area, while the area still lists it; else null. */
export function rememberedPlace(areaId, premises) {
  const id = readPicks()[areaId];
  return premises.some((premise) => premise.id === id) ? id : null;
}

/** The page's first state. `linked` is the place the link names ({place, squares}, main.js linkedPlace) or null. */
export function initialState(url, start, linked) {
  const place = linked?.place ?? null;
  return {
    tab: url.tab ?? (linked ? "business" : "overview"),
    rp: url.rp ?? DEFAULT_RP,
    areaId: start.area.id,
    placeKey: place?.id ?? rememberedPlace(start.area.id, start.premises),   // null: nothing picked yet
    points: place?.is_point ? { [place.id]: place } : {},   // points checked on this visit, by id
    squares: linked?.squares ? { [place.id]: linked.squares } : {},   // {blocks, cells} that came with the latest point, by its id
    photos: {},    // by place id: { busy, preview, estimate, water_above_floor_m, error }
    stocks: {},    // by place id: { busy, result, error }: the photo of the stock (POST /api/stock)
    plans: {},     // by place id: { busy, result, error }: the flood plan (POST /api/plan)
    planLanguage: lang,   // the plan is written in the page's language unless the owner picks the other
    compare: [],   // ids of the places side by side on My business, oldest first (compare.js)
    listings: {},  // by business id: { busy } | { configured, place } | { error }
    estimates: {}, // by place id: { busy, result } | { result } | { error, result }
    rain: start.status.maps_ready ? { busy: true, configured: true } : { configured: false },
  };   // aim mode, the mode in which a point is picked, is the Area overview's own and lives in pin.js
}

// ---------- the finder ----------

/** One suggestion per business, made unique with its road, by name: a Map of the text to the business's id. */
export function finderEntries(premises) {
  const ids = new Map();
  for (const p of [...premises].sort((a, b) => a.name.localeCompare(b.name))) {
    let text = `${p.name} · ${roadName(p.road.name)}`;
    for (let n = 2; ids.has(text); n += 1) text = `${p.name} · ${roadName(p.road.name)} (${n})`;
    ids.set(text, p.id);
  }
  return ids;
}

/** The ids of the businesses a search means: the suggestion it is, else the one business whose name it is, else every
 *  business whose suggestion holds it. */
function matchesOf(ids, typed) {
  if (ids.has(typed)) return [ids.get(typed)];
  const needle = typed.toLowerCase();
  const hits = [...ids].filter(([text]) => text.toLowerCase().includes(needle));
  const named = hits.filter(([text]) => text.slice(0, text.lastIndexOf(" · ")).toLowerCase() === needle);
  return (named.length === 1 ? named : hits).map(([, id]) => id);
}

function wireForm(form, input, ids, onOpen, onShowMatches) {
  const open = (id) => { input.value = ""; input.blur(); onOpen(id); };
  input.addEventListener("input", () => { if (ids.has(input.value)) open(ids.get(input.value)); });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const typed = input.value.trim();
    if (!typed) { input.focus(); return; }   // an empty Search sends the reader to the box
    const matches = matchesOf(ids, typed);
    if (matches.length === 1) open(matches[0]);
    else onShowMatches(typed);   // several, or none: the list of businesses, filtered by it, says which
  });
}

/** The browser's own suggestion list in `datalist`, built once, shared by every [form, input] pair in `forms`: picking
 *  a suggestion opens its business at once. Enter opens the one business the text means; when it could mean several,
 *  or none, onShowMatches(text) shows them, as a business picked for someone would be a stranger's shop. */
export function wireFinder({ datalist, forms }, premises, onOpen, onShowMatches) {
  const ids = finderEntries(premises);
  datalist.replaceChildren(...[...ids.keys()].map((text) => h("option", { value: text })));
  for (const [form, input] of forms) wireForm(form, input, ids, onOpen, onShowMatches);
}

// ---------- nothing picked yet ----------

/** What My business and Flood cost show while no place is picked: what to do, and the ways to do it. Its h1 is where
 *  focus lands when the tab is opened from a button. onFind() goes to the search; onCheckPoint(button) starts checking
 *  a point, and is null when this build cannot check points. */
export function emptyState({ kicker, onFind, onCheckPoint = null }) {
  return h("section", { class: "surface pick-empty" },
    h("p", { class: "kicker" }, kicker),
    h("h1", { class: "view-title" }, t("empty.title")),
    h("p", { class: "muted" }, t("empty.line")),
    h("div", { class: "pick-empty-actions" },
      h("button", { type: "button", class: "btn btn-primary", onclick: () => onFind() }, icon("search"), t("empty.find")),
      onCheckPoint && h("button", { type: "button", class: "btn btn-secondary", onclick: (event) => onCheckPoint(event.currentTarget) },
        icon("pin"), t("empty.check"))));
}
