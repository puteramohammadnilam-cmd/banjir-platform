// The "My business" tab: the depth for one business, drawn to scale, with what it means and what to do next.
import { band, depthText, depthWords, h, icon, kindText, renderPicker, roadName, scenarioLabel } from "./dom.js";
import { elevationFact } from "./elevation.js";
import { MAX_DRAWN_FLOOR_M, gauge } from "./gauge.js";
import { floodCounts } from "./history.js";
import { formatNumber, t } from "./i18n.js";
import { emptyState } from "./pick.js";
import { NO_WATER_NOTE, pointHeader } from "./point.js";

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

const fact = (iconName, label, ...body) => h("section", { class: "fact" }, h("h2", { class: "fact-label" }, icon(iconName), label), ...body);

function roadFact(premise, rp) {
  const depth = premise.road.depth_m[rp];
  return fact("road", t("business.road"),
    h("p", { class: "fact-value" }, band(depth) ? t("business.roadWet", { depth: depthText(depth) }) : t("business.roadDry")),
    h("p", { class: "fact-note" }, t("business.roadNote", { road: roadName(premise.road.name), distance: premise.road.distance_m })));
}

function shelterFact(shelter) {
  return fact("pin", t("common.relief"),
    h("p", { class: "fact-value" }, shelter.name),
    h("p", { class: "fact-note" }, t("business.shelterNote", { distance: formatNumber(shelter.distance_m) })));
}

function listingFact(listing) {
  if (!listing || listing.configured === false) return null;
  if (listing.busy) return fact("pin", "Google Maps", h("p", { class: "fact-note" }, t("business.mapsChecking")));
  if (listing.error) return fact("pin", "Google Maps", h("p", { class: "fact-note" }, listing.error));
  if (!listing.place) {
    return fact("pin", "Google Maps", h("p", { class: "fact-value" }, t("business.mapsNone")),
      h("p", { class: "fact-note" }, t("business.mapsNoneNote")));
  }
  const { place } = listing;
  return fact("pin", "Google Maps",
    h("p", { class: "fact-value" }, t("business.listedAs", { status: t(LISTED[place.status] ?? "listing.unknown") })),
    h("p", { class: "fact-note" }, place.name ? `${t("business.listedName", { name: place.name })} ` : "",
      place.maps_uri && h("a", { href: place.maps_uri, target: "_blank", rel: "noopener noreferrer" }, t("business.mapsView"))),
    h("p", { class: "fineprint" }, t("business.mapsSource")));
}

function floorFact(rp, photo, onPhoto, isReady) {
  const isOff = Boolean(photo?.busy) || !isReady;
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "visually-hidden", disabled: isOff, onchange: (event) => onPhoto(event.target.files[0]) });
  const picker = h("label", { class: "btn btn-secondary photo-button", "aria-disabled": isOff ? "true" : null }, icon("camera"),
    photo?.busy ? t("common.photoReading") : photo?.estimate ? t("common.photoAgain") : t("business.photoAdd"), input);
  const estimate = photo?.estimate;
  let value = t("business.floorUnknown");
  let note = t("business.floorHint");
  if (estimate && !estimate.is_shop_front) {
    value = t("business.notShopFront");
    note = t("business.notShopFrontNote");
  } else if (estimate) {
    const above = photo.water_above_floor_m[rp];
    value = t("business.floorAbout", { cm: estimate.floor_height_cm });
    note = `${t("business.floorAi", { confidence: confidenceText(estimate.confidence) })} ${above == null ? "" : above > 0
      ? t("business.aboveFloor", { m: above.toFixed(2), words: depthWords(above) })
      : t("business.belowFloor")}`;
  }
  return fact("camera", t("business.floor"),
    h("p", { class: "fact-value" }, value),
    h("p", { class: "fact-note" }, note),
    estimate?.is_shop_front && h("p", { class: "fact-note" }, `${estimate.reasoning} ${t("business.goodsAtFloor", { stock: estimate.stock_at_floor_level })}`),
    photo?.error && h("p", { class: "fact-note", role: "alert" }, photo.error),
    photo?.preview && h("img", { class: "photo-thumb", src: photo.preview, alt: t("business.photoAlt"), width: 96, height: 72 }),
    picker,
    !isReady && h("p", { class: "fact-note ai-off" }, t("common.needsAi")),
    h("p", { class: "fineprint" }, t("common.photoPrivacy")));
}

/** The area's own flood record. An area with none collected shows no fact: the Area overview says so. */
function historyFact(area, goto) {
  const counts = floodCounts(area.history);
  if (!counts) return null;
  const { dated, recent, since, recentFrom } = counts;
  return fact("clock", t("history.heading"),
    h("p", { class: "fact-value" }, t("business.historyValue", { recent, from: recentFrom })),
    h("p", { class: "fact-note" }, `${t("business.historyNote", { dated, area: area.name, since })} `,
      h("button", { type: "button", class: "btn btn-link", onclick: () => goto("overview") }, t("business.historySee"))));
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

/** A business's name, kind and tags, and the way to see it on the map. */
function businessHead(premise, showOnMap) {
  return [
    h("div", {},
      h("p", { class: "kicker" }, kindText(premise)),
      h("h1", { class: "view-title" }, premise.name),
      h("ul", { class: "tags" },
        h("li", { class: "tag" }, t("business.tagPublic")),
        h("li", { class: "tag" }, t("business.tagUnchecked")),
        premise.is_chain && h("li", { class: "tag" }, t("business.tagChain")))),
    seeOnMap(showOnMap),
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

const header = (place, options) => (place.is_point ? pointHead(place, options) : businessHead(place, options.showOnMap));

/** The facts beside the drawing. A point has no road or Google Maps listing: it is not a business. Its relief centre
 *  is the server's, for a point in a listed area with one; the flood record is the page's area's, so only a point in
 *  that area shows it (another area's record is on that area's own page). */
function sideFacts({ premise, rp, photo, listing }, { area, goto, onPhoto, isReady }) {
  const isPoint = premise.is_point;
  const hasPageRecord = !isPoint || premise.area_id === area.id;
  return h("div", { class: "facts" },
    !isPoint && premise.road && roadFact(premise, rp),
    elevationFact(premise),
    premise.shelter && shelterFact(premise.shelter),
    !isPoint && listingFact(listing),
    floorFact(rp, photo, onPhoto, isReady),
    hasPageRecord && historyFact(area, goto));
}

/** Built once, for the page's area (its name and flood record). `areas` are the listed areas, to name the one a point
 *  lies in; onOpenArea(areaId) opens that area when it is not the page's, and onOpenSection(sectionId) a section of the
 *  page's city; onAsk(button) opens the floating chat (the button is
 *  where focus returns to); onMovePin() puts the pin of a point back in
 *  the map's hands. With no place picked the tab shows the empty state (pick.js), with onFind and onCheckPoint behind
 *  its buttons. isReady and hasMaps are false when the build has no Gemini key or no Google Maps key: the photo button
 *  is then off, and the Ask AI shortcut says what it can read. The drawing is rebuilt only when the place, flood size or floor changes, so its water animation is
 *  not restarted by other updates, such as the Google Maps listing arriving. */
export function createBusiness(panel, { area, areas = [], onPhoto, onPick, goto, showOnMap, onMovePin, onOpenArea, onOpenSection = null, onAsk = () => {}, onFind = () => {}, onCheckPoint = null, isReady = true, hasMaps = true }) {
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
    render({ premise, rp, photo, listing }) {
      // state objects are replaced, never changed, so the same objects mean nothing here changed
      if (premise === shown.premise && rp === shown.rp && photo === shown.photo && listing === shown.listing) return;
      const isNewBusiness = premise !== shown.premise;
      shown = { premise, rp, photo, listing };
      if (!premise) return showEmpty();
      empty.replaceChildren();
      head.hidden = false;
      grid.hidden = false;
      const photoFloorM = photo?.estimate?.is_shop_front ? photo.estimate.floor_height_cm / 100 : 0;
      const floorM = Math.min(photoFloorM, MAX_DRAWN_FLOOR_M);
      if (isNewBusiness) head.replaceChildren(...header(premise, { area, areas, showOnMap, onMovePin, onOpenArea, onOpenSection }));
      const key = `${premise.id}|${premise.area_id}|${rp}|${photoFloorM}`;
      if (key !== drawnKey) {
        drawnKey = key;
        const isPageArea = !premise.is_point || premise.area_id === area.id;   // the example is this area's flood
        renderPicker(picker, rp, onPick, isPageArea ? area.bigger_flood_example : null);
        drawing.replaceChildren(...headline(premise, rp), gauge(premise, rp, floorM), caption(photoFloorM, floorM));
        announcer.textContent = spoken(premise, rp);
      }
      side.replaceChildren(
        sideFacts(shown, { area, goto, onPhoto, isReady }),
        h("div", { class: "next" },
          nextStep(t("business.nextCost"), t("business.nextCostNote"), () => goto("cost"), true),
          nextStep(t("business.nextAsk"), askNote(isReady, hasMaps), (event) => onAsk(event.currentTarget))));
    },
  };
}
