// The "My business" tab: the depth for one business, drawn to scale, with what it means and what to do next.
import { band, depthText, depthWords, h, icon, kindText, renderPicker, roadName, scenarioLabel } from "./dom.js";
import { carFact } from "./car.js";
import { floodModeButton } from "./floodmode.js";
import { forecastFact } from "./forecast.js";
import { gaugeFact } from "./river-gauge.js";
import { shareButton } from "./share.js";
import { elevationFact } from "./elevation.js";
import { MAX_DRAWN_FLOOR_M, gauge } from "./gauge.js";
import { floodCounts } from "./history.js";
import { t } from "./i18n.js";
import { distanceText, factCard, factGroup, openFolds, reopenFolds } from "./fact.js";
import { emptyState } from "./pick.js";
import { NO_WATER_NOTE, pointHeader } from "./point.js";
import { flashFact } from "./susceptibility.js";

// Past this, the global model is often far deeper than reports of real floods (5 to 10 m against 0.1 to 2 m in the
// towns screened on 3 Oct 2026), so the number gets a warning beside it, not only in the area's notes.
const DEEP_M = 3;
const LISTED = { open: "listing.open", "closed for now": "listing.closedNow", "closed for good": "listing.closedGood", "not open yet": "listing.notYet" };
const CONFIDENCE = { low: "confidence.low", medium: "confidence.medium", high: "confidence.high" };
/** Gemini's confidence ("low", "medium" or "high") in the page's language; anything else as it came. */
const confidenceText = (value) => (CONFIDENCE[value] ? t(CONFIDENCE[value]) : value);

function headline(premise, rp) {
  const depth = premise.depth_m[rp];
  if (!band(depth)) {
    return [h("p", { class: "headline is-dry" }, h("strong", {}, t("business.noWater")), h("span", {}, t("business.noWaterHere"))),
      h("p", { class: "subhead" }, t("business.dryNote", { label: scenarioLabel(rp) })),
      ...(premise.is_point ? [h("p", { class: "subhead" }, NO_WATER_NOTE)] : [])];   // a point can be in the sea or on a road
  }
  return [h("p", { class: "headline" }, h("strong", {}, depthText(depth)), h("span", {}, depthWords(depth))),
    h("p", { class: "subhead" }, t("business.wetNote", { label: scenarioLabel(rp) })),
    ...(depth >= DEEP_M ? [h("p", { class: "deep-note" }, t("business.deepNote"))] : [])];
}

// Water on the road a car meets: about 15 cm reaches the underside of most cars and 30 cm can float one (US National
// Weather Service, "Turn Around Don't Drown"). Said in the chip only; the number is the model's.
const ROAD_HARD_M = 0.15;
const ROAD_DEEP_M = 0.3;

/** The road's tone and chip: dry in the model, shallow, hard for cars, or too deep for them. */
function roadVerdict(depth) {
  if (!band(depth)) return { tone: "low", chip: t("business.roadChipDry") };
  if (depth < ROAD_HARD_M) return { tone: "some", chip: t("business.roadChipShallow") };
  if (depth < ROAD_DEEP_M) return { tone: "some", chip: t("business.roadChipHard") };
  return { tone: "high", chip: t("business.roadChipDeep") };
}

function roadFact(premise, rp) {
  const depth = premise.road.depth_m[rp];
  return factCard({ iconName: "road", label: t("business.road"), ...roadVerdict(depth),
    value: band(depth) ? t("business.roadWet", { depth: depthText(depth) }) : t("business.roadDry"),
    lead: h("p", { class: "fact-note" }, t("business.roadWhere", { road: roadName(premise.road.name), distance: distanceText(premise.road.distance_m) })),
    more: h("p", {}, t("business.roadLimit")) });
}

function shelterFact(shelter) {
  return factCard({ iconName: "pin", label: t("common.relief"), value: distanceText(shelter.distance_m),
    lead: h("p", { class: "fact-note" }, shelter.name), more: h("p", {}, t("business.shelterLine")) });
}

function listingFact(listing) {
  if (!listing || listing.configured === false) return null;
  const card = (value, lead, more = []) => factCard({ iconName: "pin", label: "Google Maps", value, lead, more });
  if (listing.busy) return card(null, h("p", { class: "fact-note" }, t("business.mapsChecking")));
  if (listing.error) return card(null, h("p", { class: "fact-note" }, listing.error));
  if (!listing.place) return card(t("business.mapsNone"), h("p", { class: "fact-note" }, t("business.mapsNoneNote")));
  const { place } = listing;
  return card(t("business.listedAs", { status: t(LISTED[place.status] ?? "listing.unknown") }),
    h("p", { class: "fact-note" }, place.name ? `${t(place.same_name === false ? "business.listedOther" : "business.listedName", { name: place.name })} ` : "",
      place.maps_uri && h("a", { href: place.maps_uri, target: "_blank", rel: "noopener noreferrer" }, t("business.mapsView"))),
    h("p", {}, t("business.mapsSource")));
}

/** What the floor photo says: the floor's height, and the water above it, or why there is none. */
function floorWords(rp, photo) {
  const estimate = photo?.estimate;
  if (!estimate) return { value: t("business.floorUnknown"), note: t("business.floorHint") };
  if (!estimate.is_shop_front) return { value: t("business.notShopFront"), note: t("business.notShopFrontNote") };
  const above = photo.water_above_floor_m[rp];
  const water = above == null ? "" : above > 0
    ? t("business.aboveFloor", { m: above.toFixed(2), words: depthWords(above) }) : t("business.belowFloor");
  return { value: t("business.floorAbout", { cm: estimate.floor_height_cm }),
    note: `${t("business.floorAi", { confidence: confidenceText(estimate.confidence) })} ${water}` };
}

function floorFact(rp, photo, onPhoto, isReady) {
  const isOff = Boolean(photo?.busy) || !isReady;
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "visually-hidden", disabled: isOff, onchange: (event) => onPhoto(event.target.files[0]) });
  const picker = h("label", { class: "btn btn-secondary photo-button", "aria-disabled": isOff ? "true" : null }, icon("camera"),
    photo?.busy ? t("common.photoReading") : photo?.estimate ? t("common.photoAgain") : t("business.photoAdd"), input);
  const estimate = photo?.estimate;
  const { value, note } = floorWords(rp, photo);
  return factCard({ iconName: "camera", label: t("business.floor"), value, lead: [
    h("p", { class: "fact-note" }, note),
    photo?.error && h("p", { class: "fact-note", role: "alert" }, photo.error),
    photo?.preview && h("img", { class: "photo-thumb", src: photo.preview, alt: t("business.photoAlt"), width: 96, height: 72 }),
    picker,
    !isReady && h("p", { class: "fact-note ai-off" }, t("common.needsAi")),
    h("p", { class: "fineprint" }, t("common.photoPrivacy"))].filter(Boolean),
  more: estimate?.is_shop_front && h("p", {}, `${estimate.reasoning} ${t("business.goodsAtFloor", { stock: estimate.stock_at_floor_level })}`) });
}

// Floods on record since the recent years began: this many or more is said as "often". The record is the whole area's,
// not this shop's, so it never takes the high tone: any recent flood is "some".
const OFTEN_RECENT = 3;

/** The area's own flood record. An area with none collected shows no fact: the Area overview says so. */
function historyFact(area, goto) {
  const counts = floodCounts(area.history);
  if (!counts) return null;
  const { dated, recent, since, recentFrom } = counts;
  const tone = recent > 0 ? "some" : null;
  return factCard({ iconName: "clock", label: t("history.heading"), tone,
    chip: tone && t(recent >= OFTEN_RECENT ? "business.historyChipOften" : "business.historyChipSome"),
    value: t("business.historyValue", { recent, from: recentFrom }),
    lead: h("button", { type: "button", class: "btn btn-link fact-link", onclick: () => goto("overview") }, t("business.historySee")),
    more: h("p", {}, t("business.historyNote", { dated, area: area.name, since })) });
}

/** The Ask AI shortcut's second line: what it reads, or that the assistant is off in this build. */
const askNote = (isReady, hasMaps) => t(!isReady ? "business.nextAskOff" : hasMaps ? "business.nextAskNote" : "business.nextAskNoMaps");

const nextStep = (title, text, onclick, isPrimary = false) =>
  h("button", { type: "button", class: `next-step${isPrimary ? " is-primary" : ""}`, onclick },
    h("span", {}, h("strong", {}, title), text), icon("arrow"));

function caption(photoFloorM, floorM) {
  let floor = t("business.floorLevel");
  if (photoFloorM > floorM) floor = t("business.floorMax", { drawn: Math.round(floorM * 100), photo: Math.round(photoFloorM * 100) });
  else if (floorM > 0) floor = t("business.floorRaised");
  return h("p", { class: "fineprint" }, `${t("business.scale")} `, floor);
}

const spoken = (premise, rp) => {
  const depth = premise.depth_m[rp];
  const where = premise.is_point ? t("business.spokenSquare") : premise.name;
  return t("business.spoken", { where, depth: band(depth) ? `${depthText(depth)}, ${depthWords(depth)}` : depthText(depth), label: scenarioLabel(rp) });
};

const seeOnMap = (showOnMap) =>
  h("button", { type: "button", class: "btn btn-secondary", onclick: showOnMap }, icon("pin"), t("business.seeOnMap"));

/** The address of a business's 3D picture (3d.html: its section's bundle, app/areas.py `has_3d`) at a flood size. */
export const link3d = (premise, rp) =>
  `3d.html?${new URLSearchParams({ area: premise.area_id, section: premise.section, place: premise.id, rp })}`;

/** A link to the business's 3D picture, for one that has one. render() keeps its flood size the one on show. */
const seeIn3d = (premise, rp) => premise.has_3d &&
  h("a", { class: "btn btn-secondary see-3d", href: link3d(premise, rp) }, icon("wave"), t("business.see3d"));

/** For a business with no 3D view: which listed areas have one (`has_3d` in GET /api/areas), else nothing. */
function no3dNote(premise, areas) {
  const ready = areas.filter((listed) => listed.has_3d).map((listed) => listed.name);
  return !premise.has_3d && ready.length > 0 && h("p", { class: "muted small" }, t("business.no3d", { areas: ready.join(", ") }));
}

/** A business's name, kind and tags, and the ways to see it on the map and, where there is one, in 3D. */
function businessHead(premise, showOnMap, rp, areas) {
  return [
    h("div", {},
      h("p", { class: "kicker" }, kindText(premise)),
      h("h1", { class: "view-title" }, premise.name),
      h("ul", { class: "tags" },
        h("li", { class: "tag" }, t("business.tagPublic")),
        h("li", { class: "tag" }, t("business.tagUnchecked")),
        premise.is_chain && h("li", { class: "tag" }, t("business.tagChain"))),
      no3dNote(premise, areas)),
    h("div", { class: "biz-actions" }, seeOnMap(showOnMap), seeIn3d(premise, rp)),
  ];
}

/** Where a point lies, when that is a listed area, or a section of the page's city, other than the page's: said, and a
 *  way to open it (onOpenArea, or onOpenSection for a section). Without that callback only the sentence shows. */
const elsewhereOffer = ({ kind, id, text, action }, { onOpenArea, onOpenSection }) => {
  const onOpen = kind === "section" ? onOpenSection : onOpenArea;
  return h("p", { class: "fact-note" }, text, " ", onOpen && h("button", { type: "button", class: "btn btn-link", onclick: () => onOpen(id) }, action));
};

/** A point, a model square someone picked, has no name, kind or road of its own: its words are in point.js. "Move the
 *  pin" shows only where the page can move the pin (onMovePin). */
function pointHead(place, { area, areas, showOnMap, onMovePin, onOpenArea, onOpenSection }) {
  const words = pointHeader(place, area, areas);
  const move = onMovePin && h("button", { type: "button", class: "btn btn-secondary", onclick: () => onMovePin() }, icon("map"), t("business.movePin"));
  return [
    h("div", {},
      h("p", { class: "kicker" }, words.kicker),
      h("h1", { class: "view-title" }, words.title),
      words.subline && h("p", { class: "muted small" }, words.subline),
      h("ul", { class: "tags" }, words.tags.map((tag) => h("li", { class: "tag" }, tag))),
      words.elsewhere && elsewhereOffer(words.elsewhere, { onOpenArea, onOpenSection })),
    h("div", { class: "biz-actions" }, move, " ", seeOnMap(showOnMap)),
  ];
}

const header = (place, options) =>
  (place.is_point ? pointHead(place, options) : businessHead(place, options.showOnMap, options.rp, options.areas));

/** The facts beside the drawing, in three groups: the water at this place, getting out, and what makes it more exact.
 *  A point has no road or Google Maps listing: it is not a business. Its relief centre is the server's, for a point in
 *  a listed area with one; the flood record is the page's area's, so only a point in that area shows it (another
 *  area's record is on that area's own page). */
function sideFacts({ premise, rp, photo, listing, dry }, { area, goto, onPhoto, isReady }) {
  const isPoint = premise.is_point;
  const hasPageRecord = !isPoint || premise.area_id === area.id;
  return h("div", { class: "facts" },
    factGroup(t("business.groupWater"), [
      flashFact(premise, hasPageRecord && area),   // the example is the page's area's
      elevationFact(premise),
      hasPageRecord && historyFact(area, goto),
      forecastFact(premise),
      gaugeFact(premise)]),
    factGroup(t("business.groupOut"), [
      !isPoint && premise.road && roadFact(premise, rp),
      carFact(premise, rp, dry),
      premise.shelter && shelterFact(premise.shelter)]),
    factGroup(t("business.groupCheck"), [
      floorFact(rp, photo, onPhoto, isReady),
      !isPoint && listingFact(listing)]));
}

/** Built once, for the page's area (its name and flood record). `areas` are the listed areas, to name the one a point
 *  lies in; onOpenArea(areaId) opens that area when it is not the page's, and onOpenSection(sectionId) a section of the
 *  page's city; onAsk(button) opens the floating chat (the button is
 *  where focus returns to); onMovePin() puts the pin of a point back in
 *  the map's hands. With no place picked the tab shows the empty state (pick.js), with onFind and onCheckPoint behind
 *  its buttons. isReady and hasMaps are false when the build has no Gemini key or no Google Maps key: the photo button
 *  is then off, and the Ask AI shortcut says what it can read. The drawing is rebuilt only when the place, flood size or floor changes, so its water animation is
 *  not restarted by other updates, such as the Google Maps listing arriving. */
export function createBusiness(panel, { area, areas = [], onWarning = null, onPhoto, onPick, goto, showOnMap, onMovePin, onOpenArea, onOpenSection = null, onAsk = () => {}, onFind = () => {}, onCheckPoint = null, isReady = true, hasMaps = true }) {
  const empty = h("div");   // first, so that its h1 is the one goto() focuses while it is on show
  const head = h("header", { class: "biz-head" });
  const risk = h("section", { class: "surface risk", "aria-label": t("business.riskLabel") });
  const picker = h("div");
  const drawing = h("div");
  const side = h("aside", { class: "biz-side", "aria-label": t("business.sideLabel") });
  const announcer = h("p", { class: "visually-hidden", "aria-live": "polite" });
  const grid = h("div", { class: "biz-grid" }, risk, side);
  risk.append(picker, drawing);
  panel.replaceChildren(empty, head, grid, announcer);
  let drawnKey = null;
  let shown = {};

  /** Nothing picked: the empty state alone, and nothing of the last place left behind to be focused or read. */
  function showEmpty() {
    if (!empty.children.length) empty.append(emptyState({ kicker: t("tab.business"), onFind, onCheckPoint }));
    head.replaceChildren();
    head.hidden = true;
    grid.hidden = true;
    drawnKey = null;
  }

  return {
    render({ premise, rp, photo, listing, dry }) {
      // state objects are replaced, never changed, so the same objects mean nothing here changed
      if (premise === shown.premise && rp === shown.rp && photo === shown.photo && listing === shown.listing && dry === shown.dry) return;
      const isNewBusiness = premise !== shown.premise;
      const isNewSize = rp !== shown.rp;
      shown = { premise, rp, photo, listing, dry };
      if (!premise) return showEmpty();
      empty.replaceChildren();
      head.hidden = false;
      grid.hidden = false;
      const photoFloorM = photo?.estimate?.is_shop_front ? photo.estimate.floor_height_cm / 100 : 0;
      const floorM = Math.min(photoFloorM, MAX_DRAWN_FLOOR_M);
      if (isNewBusiness) head.replaceChildren(...header(premise, { area, areas, showOnMap, onMovePin, onOpenArea, onOpenSection, rp }));
      else if (isNewSize) head.querySelector(".see-3d")?.setAttribute("href", link3d(premise, rp));   // the head stays; the size moves
      const key = `${premise.id}|${premise.area_id}|${rp}|${photoFloorM}`;
      if (key !== drawnKey) {
        drawnKey = key;
        const isPageArea = !premise.is_point || premise.area_id === area.id;   // the example is this area's flood
        renderPicker(picker, rp, onPick, isPageArea ? area.bigger_flood_example : null);
        const [figure, sentence, ...notes] = headline(premise, rp);   // the street scene comes straight after the figure, the caveats under it
        drawing.replaceChildren(figure, sentence, gauge(premise, rp, floorM), ...notes, caption(photoFloorM, floorM),
          shareButton(premise, rp, isPageArea ? area.display_name : null));
        announcer.textContent = spoken(premise, rp);
      }
      const wasOpen = openFolds(side);   // a fold the reader opened stays open when the listing arrives or the size changes
      side.replaceChildren(
        ...(onWarning ? [floodModeButton(onWarning)] : []),
        sideFacts(shown, { area, goto, onPhoto, isReady }),
        h("div", { class: "next" },
          nextStep(t("business.nextCost"), t("business.nextCostNote"), () => goto("cost"), true),
          nextStep(t("business.nextAsk"), askNote(isReady, hasMaps), (event) => onAsk(event.currentTarget))));
      reopenFolds(side, wasOpen);
    },
  };
}
