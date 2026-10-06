// "Where to move your car" on My business, under Getting out: the nearest street the flood model keeps dry in the flood
// size on show (POST /api/dry-spot, app/dryspots.py), how far and which way, with directions in Google Maps. Cars were
// often the biggest single cost in the Flood cost tab, and moving them early is free.
import { h } from "./dom.js";
import { distanceText, factCard } from "./fact.js";
import { t } from "./i18n.js";

const COMPASS = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];
const DIRECTIONS_URL = "https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=";

/** "north-east" for a bearing in degrees from north. */
export const directionWords = (bearing) => t(`dir.${COMPASS[Math.round(bearing / 45) % COMPASS.length]}`);

/** A link that opens Google Maps with directions to the spot (a point on a public street, never the place picked). */
const directions = (spot) => h("a", { href: `${DIRECTIONS_URL}${spot.lat},${spot.lon}`, target: "_blank", rel: "noopener noreferrer" },
  t("car.directions"));

const REACH_KM = 3;   // app/dryspots.REACH_M

/** The answer: the place's own street (or, for a point, the spot itself) dry in the model; a dry street near it, with
 *  a warning not to drive through water to reach it; or none within reach. */
function answer(spot, dryHere, rp) {
  if (dryHere) return { value: t(`car.${dryHere}`), lead: h("p", { class: "fact-note" }, t(`car.${dryHere}Note`, { rp })) };
  if (!spot) return { value: t("car.none"), tone: "high", lead: h("p", { class: "fact-note" }, t("car.noneNote", { rp, km: REACH_KM })) };
  const road = spot.road ?? t("car.unnamed");
  return {
    value: t("car.away", { distance: distanceText(spot.distance_m), direction: directionWords(spot.bearing) }),
    lead: [h("p", { class: "fact-note" }, t("car.spotNote", { rp, road }), " ", directions(spot)),
      h("p", { class: "fact-note car-warning" }, t("car.warning"))],
  };
}

/** "here" when a business's street has no water in the model at `rp`, "point" when a point has none; else null. A
 *  business with no street on the map is not counted as dry: it gets the nearest dry street. */
function dryHere(premise, rp) {
  if (premise.is_point) return premise.depth_m?.[rp] > 0 ? null : "point";
  const road = premise.road?.depth_m;
  return road && !(road[rp] > 0) ? "here" : null;
}

/** The same answer as plain nodes, for the "Flood is coming" checklist: the value, then its notes; null while the
 *  answer is not in or the area has no dry spots. */
export function carStep(premise, rp, dry) {
  if (!dry?.spots) return null;
  const { value, lead } = answer(dry.spots[rp], dryHere(premise, rp), rp);
  return [h("p", { class: "step-answer" }, value), ...[lead].flat()];
}

/** The fact. `dry` is the place's answer from the server ({busy} | {spots} | {error}); a place in an area without dry
 *  spots (spots null) gets no fact. A business counts its own street; a point counts the water at the point. */
export function carFact(premise, rp, dry) {
  const label = t("car.label");
  if (!dry || dry.spots === null) return null;
  if (dry.busy) return factCard({ iconName: "road", label, lead: h("p", { class: "fact-note" }, t("car.finding")) });
  if (dry.error) return factCard({ iconName: "road", label, lead: h("p", { class: "fact-note" }, dry.error) });
  return factCard({ iconName: "road", label, ...answer(dry.spots[rp], dryHere(premise, rp), rp),
    more: [h("p", {}, t("car.limit")), h("p", { class: "fineprint" }, dry.spots.credit)] });
}
