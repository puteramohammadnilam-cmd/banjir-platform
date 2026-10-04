// Start-up: what the link asks for, and the data to show it. Kept apart from main.js, with the API handed in, so node can
// test it (tests/start.test.mjs). An area is plain (one page, as every area was) or a city split into sections
// (`has_sections`): a city opens on the whole city (choropleth and table, its businesses as a lean `index`) or on one
// section (its businesses in full). A section is its own page, as an area is, so switching is a new page load.
import * as realApi from "./api.js";
import { squaresOf } from "./cells.js";
import { t } from "./i18n.js";
import { businessPlace, parseRef, snapToGrid } from "./place.js";

/** The listed area whose `aliases` hold this id, with the alias: an old area that is now a section of a city. */
function aliasOf(list, id) {
  for (const area of list.areas) {
    const alias = (area.aliases ?? []).find((entry) => entry.id === id);
    if (alias) return { area, alias };
  }
  return null;
}

/** {areaId, sectionId, isAreaMissing}: the area a link names (else the default) and the section it names. An alias
 *  stands for its area and section; a section the link names itself wins. An alias's link to a business also gives
 *  `aliasSection` and no section, as the business may lie in another section: the city's index says which. */
export function resolveTarget(url, list) {
  if (url.area === null) return { areaId: list.default, sectionId: url.section, isAreaMissing: false };
  if (list.areas.some((area) => area.id === url.area)) return { areaId: url.area, sectionId: url.section, isAreaMissing: false };
  const found = aliasOf(list, url.area);
  if (!found) return { areaId: list.default, sectionId: null, isAreaMissing: true };
  const target = { areaId: found.area.id, sectionId: url.section ?? found.alias.section, isAreaMissing: false };
  return !url.section && parseRef(url.place)?.kind === "business" ? { ...target, sectionId: null, aliasSection: found.alias.section } : target;
}

/** The section of a business, from the city's lean index; null when the index does not hold it. */
export const sectionOf = (index, id) => (index ?? []).find((row) => row.id === id)?.section ?? null;

/** The area the page's words name: the area itself, or for a section the section dressed as one (its name, and its
 *  city's after it), keeping the area's id for requests, `section_id` for the section's and `city_name`. */
export function pageArea(area, section) {
  if (!section) return area;
  return { ...area, name: section.name, display_name: `${section.name}, ${area.name}`, section_id: section.id, city_name: area.name };
}

/** Whether the page shows a whole city split into sections (the choropleth, the table and the lean index). */
export const isCityView = (start) => Boolean(start.area.has_sections) && !start.section;

/** A section's data, or null when it cannot be had (an unknown id answers 404; the page then shows the whole city and
 *  says the link's place is not in this build). */
const sectionData = (api, areaId, sectionId) => api.getSectionData(areaId, sectionId).catch(() => null);

/** The data for the target: a section's, else the area's. isSectionMissing: the link named a section not shown. */
async function loadScope(api, list, target) {
  const summary = list.areas.find((area) => area.id === target.areaId);
  if (!target.sectionId) return { data: await api.getAreaData(target.areaId), isSectionMissing: false };
  const data = summary?.has_sections ? await sectionData(api, target.areaId, target.sectionId) : null;
  return data ? { data, isSectionMissing: false } : { data: await api.getAreaData(target.areaId), isSectionMissing: true };
}

/** A whole city's data, moved on to a section when the link needs one: an old link to a business (its section is in
 *  the index), or a city whose data names a default section. Anything else stays on the whole city. */
async function intoSection(api, url, scope, aliasSection = null) {
  const { data } = scope;
  if (!data.area.has_sections || data.section) return scope;
  const ref = parseRef(url.place);
  const wanted = (ref?.kind === "business" && sectionOf(data.index, ref.id)) || aliasSection || (!url.section && data.area.default_section) || null;
  const moved = wanted ? await sectionData(api, data.area.id, wanted) : null;
  return moved ? { ...scope, data: moved } : scope;
}

/** The listed areas, the status and the data the link asks for. With no area or section in the link the default's
 *  data is asked for at once, beside the list; anything else waits for the list, to check it. The flood model's
 *  coverage (its grids, for points) is asked for now but never waited on before the first view. */
export async function loadStart(url, api = realApi) {
  const coverage = api.getCoverage().catch(() => null);   // null: points cannot be checked; businesses still work
  const isPlain = url.area === null && url.section === null;
  const [list, status, early] = await Promise.all([api.getAreas(), api.getStatus(), isPlain ? api.getDefaultData() : null]);
  const target = resolveTarget(url, list);
  const loaded = early ? { data: early, isSectionMissing: false } : await loadScope(api, list, target);
  const scope = await intoSection(api, url, loaded, target.aliasSection);
  const { data } = scope;
  return {
    list, status, coverage, area: data.area, page: pageArea(data.area, data.section), town: data.town,
    premises: data.premises.map((premise) => businessPlace(premise, data.area.id)),
    sections: data.sections ?? [], section: data.section ?? null, index: data.index ?? null,
    isAreaMissing: target.isAreaMissing || target.areaId !== data.area.id, isSectionMissing: scope.isSectionMissing,
  };
}

/** The city's lean index, for a section's page: asked for only when the search needs the whole city. */
export const loadCityIndex = (start, api = realApi) => api.getAreaData(start.area.id).then((data) => data.index ?? []);

const foundPlace = (place, squares = null) => (place ? { place, squares } : null);

/** What a link names, as {place, squares}: a business of the loaded area or section, or a point the server checks
 *  again (POST /api/point), snapped here first so that only a square's centre is sent, with the flood squares around it
 *  that come in the same answer (cells.js squaresOf; null for a business). null when the page holds no such place;
 *  throws when the server could not be asked. */
export async function linkedPlace(ref, start, api = realApi) {
  const parsed = parseRef(ref);
  if (parsed?.kind === "business") return foundPlace(start.premises.find((premise) => premise.id === parsed.id));
  if (parsed?.kind !== "point" || !start.status.points_ready) return null;
  const coverage = await start.coverage;
  const centre = coverage ? snapToGrid(parsed.lat, parsed.lon, coverage.grids) : parsed;
  if (!centre) return null;
  const answer = await api.checkPoint({ lat: centre.lat, lon: centre.lon, source: "pin" });
  return answer.coverage === "covered" ? foundPlace(answer.place, squaresOf(answer)) : null;
}

export const missedWords = (page) => t("main.missed", { area: page.name });

/** The place the link names ({place, squares}, as linkedPlace gives it), when the page holds it, and a note for a link
 *  to an area, section or place it does not hold (a point in the query counts: points are read only from the fragment).
 *  isFailed: the server could not be asked. */
export async function openLink(url, start, api = realApi) {
  const missed = missedWords(start.page);
  const isOff = start.isAreaMissing || start.isSectionMissing;
  if (!url.place) return { linked: null, note: isOff || url.pointInQuery ? missed : null };
  try {
    const linked = await linkedPlace(url.place, start, api);
    return { linked, note: linked && !isOff ? null : missed };
  } catch (error) {
    return { linked: null, note: `${error.message} ${t("main.showing", { area: start.page.name })}`, isFailed: true };
  }
}
