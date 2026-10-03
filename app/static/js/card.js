import { ADULT_M, COUNTER_M, DOOR_M, SCENARIOS, SCENARIO_LABEL, band, bandColor, depthText, depthWords, h, s } from "./dom.js";

// The shop-front drawing, in SVG units: a street, an adult, a door and a counter, to scale.
const WIDTH = 330;
const GROUND_Y = 208;
const PX_PER_M = 62;
const TOP_M = 3;                  // one storey: deeper water is cut off at the top, and the drawing says so
const MAX_DRAWN_FLOOR_M = 0.75;   // a taller floor estimate would push the door past one storey
const PERSON_X = 58;
const DOOR = { x: 104, w: 54 };
const COUNTER = { x: 180, w: 82 };
const LABEL_X = WIDTH - 4;
const LABEL_GAP = 14;
let drawnWaterM = 0;   // where the water stood in the last drawing, so the next one rises or falls from there

const yAt = (m) => GROUND_Y - m * PX_PER_M;

function objects(floorM) {
  const y = (m) => yAt(floorM + m);
  return [
    floorM > 0 && s("rect", { class: "floor", x: 24, y: y(0), width: 244, height: floorM * PX_PER_M }),
    s("g", { class: "figure" },
      s("circle", { cx: PERSON_X, cy: y(1.53), r: 7 }),
      s("rect", { x: PERSON_X - 11, y: y(1.38), width: 22, height: (1.38 - 0.85) * PX_PER_M, rx: 6 }),
      s("rect", { x: PERSON_X - 10, y: y(0.88), width: 9, height: 0.88 * PX_PER_M, rx: 3 }),
      s("rect", { x: PERSON_X + 1, y: y(0.88), width: 9, height: 0.88 * PX_PER_M, rx: 3 })),
    s("rect", { class: "door", x: DOOR.x, y: y(DOOR_M), width: DOOR.w, height: DOOR_M * PX_PER_M }),
    s("circle", { class: "knob", cx: DOOR.x + DOOR.w - 8, cy: y(1), r: 2 }),
    s("rect", { class: "counter", x: COUNTER.x, y: y(COUNTER_M), width: COUNTER.w, height: COUNTER_M * PX_PER_M }),
  ];
}

/** Drawn after the water, so they stay readable when it covers the objects. */
function objectLabels(floorM) {
  const y = (m) => yAt(floorM + m) - 6;
  return [
    s("text", { class: "object-label", x: PERSON_X, y: y(ADULT_M), "text-anchor": "middle" }, `adult ${ADULT_M} m`),
    s("text", { class: "object-label", x: DOOR.x + DOOR.w / 2, y: y(DOOR_M), "text-anchor": "middle" }, `door ${DOOR_M} m`),
    s("text", { class: "object-label", x: COUNTER.x + COUNTER.w / 2, y: y(COUNTER_M), "text-anchor": "middle" }, `counter ${COUNTER_M} m`),
  ];
}

/** One label per flood size at its water line, pushed apart where two lines sit close together. */
function levelLabels(premise, rp) {
  const labels = SCENARIOS.filter((key) => band(premise.depth_m[key]))
    .map((key) => ({ key, y: yAt(Math.min(premise.depth_m[key], TOP_M)) - 4 }))   // just above the line, not struck through
    .sort((a, b) => a.y - b.y);
  labels.forEach((label, i) => { if (i && label.y - labels[i - 1].y < LABEL_GAP) label.y = labels[i - 1].y + LABEL_GAP; });
  return labels.map(({ key, y }) => s("text", { class: key === rp ? "level is-active" : "level", x: LABEL_X, y, "text-anchor": "end" }, `1 in ${key}`));
}

function gauge(premise, rp, floorM) {
  const depth = premise.depth_m[rp];
  const shownM = band(depth) ? Math.min(depth, TOP_M) : 0;
  const water = s("rect", { class: "water", x: 0, y: yAt(TOP_M), width: WIDTH, height: TOP_M * PX_PER_M, fill: bandColor(depth) });
  const surface = s("line", { class: "surface", x1: 0, x2: WIDTH, y1: GROUND_Y, y2: GROUND_Y });
  water.style.transform = `scaleY(${drawnWaterM / TOP_M})`;
  surface.style.transform = `translateY(${-drawnWaterM * PX_PER_M}px)`;
  drawnWaterM = shownM;
  requestAnimationFrame(() => {   // the card is in the page by now, so the change animates
    water.getBoundingClientRect();
    water.style.transform = `scaleY(${shownM / TOP_M})`;
    surface.style.transform = `translateY(${-shownM * PX_PER_M}px)`;
  });
  const others = SCENARIOS.filter((key) => key !== rp && band(premise.depth_m[key]))
    .map((key) => s("line", { class: "other-level", x1: 0, x2: LABEL_X - 46, y1: yAt(Math.min(premise.depth_m[key], TOP_M)), y2: yAt(Math.min(premise.depth_m[key], TOP_M)) }));
  return s("svg", { class: "gauge", viewBox: `0 0 ${WIDTH} ${GROUND_Y + 24}`, role: "img", "aria-label": gaugeSummary(premise, rp) },
    objects(floorM), water, surface, others, objectLabels(floorM), levelLabels(premise, rp),
    s("line", { class: "storey", x1: 0, x2: LABEL_X - 46, y1: yAt(TOP_M), y2: yAt(TOP_M) }),
    depth > TOP_M && s("text", { class: "object-label", x: 6, y: yAt(TOP_M) + 28 }, `water deeper than shown: ${depth.toFixed(2)} m`),
    s("line", { class: "street", x1: 0, x2: WIDTH, y1: GROUND_Y, y2: GROUND_Y }),
    s("text", { x: 6, y: GROUND_Y + 17 }, "street level"));
}

function gaugeSummary(premise, rp) {
  const depth = premise.depth_m[rp];
  const others = SCENARIOS.filter((key) => key !== rp).map((key) => `1 in ${key} years: ${depthText(premise.depth_m[key])}`).join(", ");
  const here = band(depth) ? `${depthText(depth)}, ${depthWords(depth)}` : depthText(depth);
  return `Drawn to scale against an adult, a counter and a door. Water at street level in a flood expected ${SCENARIO_LABEL[rp]}: ${here}. Other flood sizes: ${others}.`;
}

function headline(premise, rp) {
  const depth = premise.depth_m[rp];
  if (!band(depth)) {
    return [h("p", { class: "headline is-dry" }, h("strong", {}, "No water"), ` in the model here in a flood expected ${SCENARIO_LABEL[rp]}.`)];
  }
  return [h("p", { class: "headline" }, h("strong", {}, `${depth.toFixed(2)} m`), ` ${depthWords(depth)}`),
    h("p", { class: "subhead" }, `Water in the model at street level here, in a flood expected ${SCENARIO_LABEL[rp]}.`)];
}

function floorFact(premise, rp, photo, onPhoto) {
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "visually-hidden", disabled: Boolean(photo?.busy), onchange: (event) => onPhoto(event.target.files[0]) });
  const picker = h("label", { class: "photo-button", "aria-disabled": photo?.busy ? "true" : null }, photo?.busy ? "Reading the photo…" : photo?.estimate ? "Try another photo" : "Add a shop-front photo", input);
  const lines = [];
  if (photo?.error) lines.push(h("p", { class: "muted", role: "alert" }, photo.error));
  if (photo?.estimate && !photo.estimate.is_shop_front) {
    lines.push(h("p", {}, "That photo does not look like a shop entrance. Try one taken from the street, facing the door."));
  } else if (photo?.estimate) {
    const above = photo.water_above_floor_m[rp];
    lines.push(h("p", {}, `Floor about ${photo.estimate.floor_height_cm} cm above the street (AI estimate, ${photo.estimate.confidence} confidence). `,
      above == null ? "" : above > 0 ? `That leaves about ${above.toFixed(2)} m of water above the floor (${depthWords(above)}) in this flood.` : "The modelled water stays below the floor in this flood."));
    lines.push(h("p", { class: "muted" }, `${photo.estimate.reasoning} Goods at floor level: ${photo.estimate.stock_at_floor_level}.`));
  } else {
    lines.push(h("p", { class: "muted" }, "Unknown. A photo of the entrance lets Gemini estimate how high the floor sits above the street."));
  }
  return [h("dt", {}, "Floor height"), h("dd", {}, lines,
    photo?.preview && h("img", { class: "photo-thumb", src: photo.preview, alt: "Your shop-front photo", width: 120, height: 90 }),
    picker,
    h("p", { class: "fineprint" }, "The photo is shrunk in your browser, sent to Google Gemini, and not saved by this tool."))];
}

const LISTED = { open: "open", "closed for now": "closed for now", "closed for good": "closed for good", "not open yet": "not open yet" };

function listingFact(listing) {
  if (!listing || listing.configured === false) return null;
  let body;
  if (listing.busy) body = h("p", { class: "muted" }, "Checking Google Maps…");
  else if (listing.error) body = h("p", { class: "muted" }, listing.error);
  else if (!listing.place) body = h("p", {}, "No listing with this name within 150 m on Google Maps.");
  else {
    const place = listing.place;
    body = [h("p", {}, `Google Maps lists ${place.name || "it"} as `, h("strong", {}, LISTED[place.status] || "status unknown"), ". ",
      place.maps_uri && h("a", { href: place.maps_uri, target: "_blank", rel: "noopener noreferrer" }, "View on Google Maps")),
    h("p", { class: "fineprint" }, "Source: Google Maps. Listings can be out of date.")];
  }
  return [h("dt", {}, "Open or closed"), h("dd", {}, body)];
}

export function renderCard(element, premise, rp, photo, onPhoto, listing) {
  const floorM = photo?.estimate?.is_shop_front ? Math.min(photo.estimate.floor_height_cm / 100, MAX_DRAWN_FLOOR_M) : 0;
  element.replaceChildren(
    h("p", { class: "card-kicker" }, premise.sector === "eatery" ? "Eatery" : "Shop", premise.kind ? ` · ${premise.kind.replaceAll("_", " ")}` : ""),
    h("h2", {}, premise.name),
    h("ul", { class: "tags" },
      h("li", { class: "tag" }, "From a public map"),
      h("li", { class: "tag" }, "Not checked on the ground"),
      premise.is_chain && h("li", { class: "tag" }, "Chain outlet")),
    ...headline(premise, rp),
    gauge(premise, rp, floorM),
    h("p", { class: "fineprint" }, "Drawn to scale, up to one storey (about 3 m). Dashed lines are the other flood sizes. ",
      floorM > 0 ? "The floor is raised by the photo's estimate." : "The floor is drawn level with the street until a photo says otherwise."),
    h("dl", { class: "facts" },
      h("dt", {}, "Nearest road"),
      h("dd", {}, `${premise.road.name}, ${premise.road.distance_m} m away. Water there: ${depthText(premise.road.depth_m[rp])}. `,
        h("span", { class: "muted" }, "A rough sign of being cut off, not a road closure.")),
      premise.shelter && [h("dt", {}, "Nearest flood relief centre"),
        h("dd", {}, `${premise.shelter.name}, ${premise.shelter.distance_m.toLocaleString()} m in a straight line.`)],
      listingFact(listing),
      floorFact(premise, rp, photo, onPhoto)),
  );
}
