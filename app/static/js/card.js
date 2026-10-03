import { BAND_COLORS, SCENARIOS, SCENARIO_LABEL, band, depthText, h, s } from "./dom.js";

// Gauge geometry, in SVG units.
const WIDTH = 330;
const GROUND_Y = 150;
const PX_PER_M = 40;
const MAX_M = 3.3;         // taller water is clipped and marked
const DOOR_M = 2.1;
const DOOR_W = 34;
const COLUMN_W = 110;
const MAX_DRAWN_FLOOR_M = 1.2;   // a taller estimate would push the door off the drawing

function gaugeColumn(rp, depth, floorM, isActive, x) {
  const level = band(depth);
  const shown = Math.min(depth ?? 0, MAX_M);
  const floorY = GROUND_Y - floorM * PX_PER_M;
  const doorX = x + (COLUMN_W - DOOR_W) / 2;
  const label = level ? (depth > MAX_M ? `over ${MAX_M} m` : `${depth.toFixed(2)} m`) : "dry";
  return s("g", { class: `col${isActive ? " is-active" : ""}` },
    level > 0 && s("rect", { class: "water", x: x + 8, y: GROUND_Y - shown * PX_PER_M, width: COLUMN_W - 16, height: shown * PX_PER_M, fill: BAND_COLORS[level - 1], "fill-opacity": 0.8 }),
    floorM > 0 && s("rect", { x: doorX - 8, y: floorY, width: DOOR_W + 16, height: GROUND_Y - floorY, fill: "#d9d0bd", stroke: "#14262b", "stroke-width": 1 }),
    s("rect", { x: doorX, y: floorY - DOOR_M * PX_PER_M, width: DOOR_W, height: DOOR_M * PX_PER_M, fill: "none", stroke: "#14262b", "stroke-width": 1.5 }),
    s("circle", { cx: doorX + DOOR_W - 7, cy: floorY - PX_PER_M, r: 1.8, fill: "#14262b" }),
    s("text", { class: "depth-label", x: x + COLUMN_W / 2, y: Math.min(GROUND_Y - shown * PX_PER_M, floorY - DOOR_M * PX_PER_M) - 6, "text-anchor": "middle", "font-size": 13 }, label),
    s("text", { x: x + COLUMN_W / 2, y: GROUND_Y + 16, "text-anchor": "middle", "font-size": 11 }, `1 in ${rp} years`),
  );
}

function gauge(premise, rp, floorM) {
  const summary = SCENARIOS.map((key) => `${SCENARIO_LABEL[key]}: ${depthText(premise.depth_m[key])}`).join(". ");
  return s("svg", { class: "gauge", viewBox: `0 0 ${WIDTH} ${GROUND_Y + 24}`, role: "img", "aria-label": `Modelled water depth beside a 2.1 m door. ${summary}.` },
    SCENARIOS.map((key, i) => gaugeColumn(key, premise.depth_m[key], floorM, key === rp, i * COLUMN_W)),
    s("line", { x1: 0, x2: WIDTH, y1: GROUND_Y, y2: GROUND_Y, stroke: "#14262b", "stroke-width": 2 }),
  );
}

function headline(premise, rp) {
  const depth = premise.depth_m[rp];
  if (!band(depth)) {
    return h("p", { class: "headline is-dry" }, h("strong", {}, "No water"), ` in the model here in a flood expected ${SCENARIO_LABEL[rp]}.`);
  }
  return h("p", { class: "headline" }, h("strong", {}, `${depth.toFixed(2)} m`), ` of water in the model here in a flood expected ${SCENARIO_LABEL[rp]}.`);
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
      above == null ? "" : above > 0 ? `That leaves about ${above.toFixed(2)} m of water above the floor in this flood.` : "The modelled water stays below the floor in this flood."));
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
    headline(premise, rp),
    gauge(premise, rp, floorM),
    h("p", { class: "fineprint" }, "Water column beside a standard 2.1 m door. The highlighted column is the flood size chosen on the map."),
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
