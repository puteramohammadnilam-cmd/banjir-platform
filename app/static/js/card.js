// The "My business" tab: the depth for one business, drawn to scale, with what it means and what to do next.
import { SCENARIO_LABEL, band, depthText, depthWords, h, icon, kindText, renderPicker } from "./dom.js";
import { MAX_DRAWN_FLOOR_M, gauge } from "./gauge.js";
import { floodCounts } from "./history.js";
import { NO_WATER_NOTE, pointHeader } from "./point.js";

const LISTED = { open: "open", "closed for now": "closed for now", "closed for good": "closed for good", "not open yet": "not open yet" };

function headline(premise, rp) {
  const depth = premise.depth_m[rp];
  if (!band(depth)) {
    return [h("p", { class: "headline is-dry" }, h("strong", {}, "No water"), h("span", {}, "in the model here")),
      h("p", { class: "subhead" }, `In a flood expected ${SCENARIO_LABEL[rp]}. That is not a promise of staying dry.`),
      ...(premise.is_point ? [h("p", { class: "subhead" }, NO_WATER_NOTE)] : [])];   // a point can be in the sea or on a road
  }
  return [h("p", { class: "headline" }, h("strong", {}, `${depth.toFixed(2)} m`), h("span", {}, depthWords(depth))),
    h("p", { class: "subhead" }, `Water in the model at street level here, in a flood expected ${SCENARIO_LABEL[rp]}.`)];
}

const fact = (iconName, label, ...body) => h("section", { class: "fact" }, h("h2", { class: "fact-label" }, icon(iconName), label), ...body);

function roadFact(premise, rp) {
  const depth = premise.road.depth_m[rp];
  return fact("road", "Road access",
    h("p", { class: "fact-value" }, band(depth) ? `${depthText(depth)} at the nearest road` : "No water at the nearest road"),
    h("p", { class: "fact-note" }, `${premise.road.name}, ${premise.road.distance_m} m away. A rough sign of being cut off, not a road closure.`));
}

function shelterFact(shelter) {
  return fact("pin", "Flood relief centre",
    h("p", { class: "fact-value" }, shelter.name),
    h("p", { class: "fact-note" }, `${shelter.distance_m.toLocaleString()} m in a straight line.`));
}

function listingFact(listing) {
  if (!listing || listing.configured === false) return null;
  if (listing.busy) return fact("pin", "Google Maps", h("p", { class: "fact-note" }, "Checking Google Maps…"));
  if (listing.error) return fact("pin", "Google Maps", h("p", { class: "fact-note" }, listing.error));
  if (!listing.place) {
    return fact("pin", "Google Maps", h("p", { class: "fact-value" }, "No listing found"),
      h("p", { class: "fact-note" }, "Nothing with this name within 150 m on Google Maps."));
  }
  const { place } = listing;
  return fact("pin", "Google Maps",
    h("p", { class: "fact-value" }, `Listed as ${LISTED[place.status] || "status unknown"}`),
    h("p", { class: "fact-note" }, place.name ? `As "${place.name}". ` : "",
      place.maps_uri && h("a", { href: place.maps_uri, target: "_blank", rel: "noopener noreferrer" }, "View on Google Maps")),
    h("p", { class: "fineprint" }, "Source: Google Maps. Listings can be out of date."));
}

function floorFact(rp, photo, onPhoto) {
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "visually-hidden", disabled: Boolean(photo?.busy), onchange: (event) => onPhoto(event.target.files[0]) });
  const picker = h("label", { class: "btn btn-secondary photo-button", "aria-disabled": photo?.busy ? "true" : null }, icon("camera"),
    photo?.busy ? "Reading the photo…" : photo?.estimate ? "Try another photo" : "Add a shop-front photo", input);
  const estimate = photo?.estimate;
  let value = "Unknown";
  let note = "A photo of the entrance lets Gemini estimate how high the floor sits above the street.";
  if (estimate && !estimate.is_shop_front) {
    value = "Not a shop front";
    note = "That photo does not look like a shop entrance. Try one taken from the street, facing the door.";
  } else if (estimate) {
    const above = photo.water_above_floor_m[rp];
    value = `About ${estimate.floor_height_cm} cm above the street`;
    note = `AI estimate, ${estimate.confidence} confidence. ${above == null ? "" : above > 0
      ? `About ${above.toFixed(2)} m of water above the floor (${depthWords(above)}) in this flood.`
      : "The modelled water stays below the floor in this flood."}`;
  }
  return fact("camera", "Floor height",
    h("p", { class: "fact-value" }, value),
    h("p", { class: "fact-note" }, note),
    estimate?.is_shop_front && h("p", { class: "fact-note" }, `${estimate.reasoning} Goods at floor level: ${estimate.stock_at_floor_level}.`),
    photo?.error && h("p", { class: "fact-note", role: "alert" }, photo.error),
    photo?.preview && h("img", { class: "photo-thumb", src: photo.preview, alt: "Your shop-front photo", width: 96, height: 72 }),
    picker,
    h("p", { class: "fineprint" }, "The photo is shrunk in your browser, sent to Google Gemini, and not saved by this tool."));
}

/** The area's own flood record. An area with none collected shows no fact: the Area overview says so. */
function historyFact(area, goto) {
  const counts = floodCounts(area.history);
  if (!counts) return null;
  const { dated, recent, since, recentFrom } = counts;
  return fact("clock", "Floods recorded here",
    h("p", { class: "fact-value" }, `${recent} since ${recentFrom}`),
    h("p", { class: "fact-note" }, `${dated} dated floods at ${area.name} since ${since}, in the sources we checked. `,
      h("button", { type: "button", class: "btn btn-link", onclick: () => goto("overview") }, "See them")));
}

const nextStep = (title, text, onclick, isPrimary = false) =>
  h("button", { type: "button", class: `next-step${isPrimary ? " is-primary" : ""}`, onclick },
    h("span", {}, h("strong", {}, title), text), icon("arrow"));

function caption(photoFloorM, floorM) {
  let floor = "The floor is drawn level with the street until a photo says otherwise.";
  if (photoFloorM > floorM) floor = `The floor is drawn ${Math.round(floorM * 100)} cm up, the most this drawing shows. The photo estimate is ${Math.round(photoFloorM * 100)} cm.`;
  else if (floorM > 0) floor = "The floor is raised by the photo's estimate.";
  return h("p", { class: "fineprint" }, "Drawn to scale, up to one storey (about 3 m). Dashed lines are the other flood sizes. ", floor);
}

const spoken = (premise, rp) => {
  const depth = premise.depth_m[rp];
  const where = premise.is_point ? "This 90 m square" : premise.name;
  return `${where}: ${band(depth) ? `${depthText(depth)}, ${depthWords(depth)}` : "no water in the model"}, in a flood expected ${SCENARIO_LABEL[rp]}.`;
};

const seeOnMap = (showOnMap) =>
  h("button", { type: "button", class: "btn btn-secondary", onclick: showOnMap }, icon("pin"), "See on map");

/** A business's name, kind and tags, and the way to see it on the map. */
function businessHead(premise, showOnMap) {
  return [
    h("div", {},
      h("p", { class: "kicker" }, kindText(premise)),
      h("h1", { class: "view-title" }, premise.name),
      h("ul", { class: "tags" },
        h("li", { class: "tag" }, "From a public map"),
        h("li", { class: "tag" }, "Not checked on the ground"),
        premise.is_chain && h("li", { class: "tag" }, "Chain outlet"))),
    seeOnMap(showOnMap),
  ];
}

/** Where a point lies, when that is a listed area other than the page's: said, and a way to open that area. Without
 *  onOpenArea only the sentence shows. */
const elsewhereOffer = ({ id, text, action }, onOpenArea) => h("p", { class: "fact-note" }, text, " ",
  onOpenArea && h("button", { type: "button", class: "btn btn-link", onclick: () => onOpenArea(id) }, action));

/** A point, a model square someone picked, has no name, kind or road of its own: its words are in point.js. "Move the
 *  pin" shows only where the page can move the pin (onMovePin). */
function pointHead(place, { area, areas, showOnMap, onMovePin, onOpenArea }) {
  const words = pointHeader(place, area, areas);
  const move = onMovePin && h("button", { type: "button", class: "btn btn-secondary", onclick: () => onMovePin() }, icon("map"), "Move the pin");
  return [
    h("div", {},
      h("p", { class: "kicker" }, words.kicker),
      h("h1", { class: "view-title" }, words.title),
      words.subline && h("p", { class: "muted small" }, words.subline),
      h("ul", { class: "tags" }, words.tags.map((tag) => h("li", { class: "tag" }, tag))),
      words.elsewhere && elsewhereOffer(words.elsewhere, onOpenArea)),
    h("div", { class: "biz-actions" }, move, " ", seeOnMap(showOnMap)),
  ];
}

const header = (place, options) => (place.is_point ? pointHead(place, options) : businessHead(place, options.showOnMap));

/** The facts beside the drawing. A point has no road or Google Maps listing: it is not a business. Its relief centre
 *  is the server's, for a point in a listed area with one; the flood record is the page's area's, so only a point in
 *  that area shows it (another area's record is on that area's own page). */
function sideFacts({ premise, rp, photo, listing }, { area, goto, onPhoto }) {
  const isPoint = premise.is_point;
  const hasPageRecord = !isPoint || premise.area_id === area.id;
  return h("div", { class: "facts" },
    !isPoint && premise.road && roadFact(premise, rp),
    premise.shelter && shelterFact(premise.shelter),
    !isPoint && listingFact(listing),
    floorFact(rp, photo, onPhoto),
    hasPageRecord && historyFact(area, goto));
}

/** Built once, for the page's area (its name and flood record). `areas` are the listed areas, to name the one a point
 *  lies in; onOpenArea(areaId) opens that area when it is not the page's; onMovePin() puts the pin of a point back in
 *  the map's hands. The drawing is rebuilt only when the place, flood size or floor changes, so its water animation is
 *  not restarted by other updates, such as the Google Maps listing arriving. */
export function createBusiness(panel, { area, areas = [], onPhoto, onPick, goto, showOnMap, onMovePin, onOpenArea }) {
  const head = h("header", { class: "biz-head" });
  const risk = h("section", { class: "surface risk", "aria-label": "Modelled flood depth" });
  const picker = h("div");
  const drawing = h("div");
  const side = h("aside", { class: "biz-side", "aria-label": "Details and next steps" });
  const announcer = h("p", { class: "visually-hidden", "aria-live": "polite" });
  risk.append(picker, drawing);
  panel.replaceChildren(head, h("div", { class: "biz-grid" }, risk, side), announcer);
  let drawnKey = null;
  let shown = {};

  return {
    render({ premise, rp, photo, listing }) {
      // state objects are replaced, never changed, so the same objects mean nothing here changed
      if (premise === shown.premise && rp === shown.rp && photo === shown.photo && listing === shown.listing) return;
      const isNewBusiness = premise !== shown.premise;
      shown = { premise, rp, photo, listing };
      const photoFloorM = photo?.estimate?.is_shop_front ? photo.estimate.floor_height_cm / 100 : 0;
      const floorM = Math.min(photoFloorM, MAX_DRAWN_FLOOR_M);
      if (isNewBusiness) head.replaceChildren(...header(premise, { area, areas, showOnMap, onMovePin, onOpenArea }));
      const key = `${premise.id}|${rp}|${photoFloorM}`;
      if (key !== drawnKey) {
        drawnKey = key;
        renderPicker(picker, rp, onPick);
        drawing.replaceChildren(...headline(premise, rp), gauge(premise, rp, floorM), caption(photoFloorM, floorM));
        announcer.textContent = spoken(premise, rp);
      }
      side.replaceChildren(
        sideFacts(shown, { area, goto, onPhoto }),
        h("div", { class: "next" },
          nextStep("What would a flood cost you?", "Loss per flood, per year and over 10 years", () => goto("cost"), true),
          nextStep("Ask in Bahasa Melayu or English", "Gemini, with Google Weather and Google Maps", () => goto("ask"))));
    },
  };
}
