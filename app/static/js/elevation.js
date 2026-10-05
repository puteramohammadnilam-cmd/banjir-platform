// Height of the ground at a business or a picked square: the lowest satellite surface height within about 45 m and the
// lowest height above the nearest mapped river there, said in bands with what the numbers cannot tell. The server sends
// place.elevation (app/elevation.py): {ground_m, above_river_m}, above_river_m null with no mapped river within 3 km,
// or null where none is loaded.
import { h } from "./dom.js";
import { factCard } from "./fact.js";
import { formatNumber, t } from "./i18n.js";

// Bands on the whole metres the note shows, so the band and the number never disagree: under 1 m (or below the river's
// level) is "near", 1 to 3 m "mid", more than 3 m "high".
const NEAR_M = 1;
const HIGH_M = 3;
const BAND_KEYS = { near: "business.elevationNear", mid: "business.elevationMid", high: "business.elevationHigh" };

/** "near", "mid" or "high" for a height above the nearest river's level in metres; null when no river was measured. */
export function riverBand(aboveM) {
  if (aboveM == null) return null;
  const whole = Math.round(aboveM);
  if (whole < NEAR_M) return "near";
  return whole <= HIGH_M ? "mid" : "high";
}

const wholeMetres = (m) => formatNumber(Math.abs(Math.round(m)));

function riverNote(aboveM) {
  const whole = Math.round(aboveM);
  if (whole === 0) return t("business.elevationLevel");
  return t(whole > 0 ? "business.elevationAbove" : "business.elevationBelow", { m: wholeMetres(aboveM) });
}

/** {value, note} for a Place's elevation: the band (or that no river is near, or that nothing is loaded here) and the
 *  whole-metre heights behind it. */
export function elevationWords(elevation) {
  if (!elevation) return { value: t("business.elevationNotLoaded"), note: t("business.elevationNotLoadedNote") };
  const { ground_m: ground, above_river_m: above } = elevation;
  const band = riverBand(above);
  const surface = Math.round(ground) > 0 ? t("business.elevationGround", { m: wholeMetres(ground) }) : t("business.elevationGroundLow");
  return { value: t(band ? BAND_KEYS[band] : "business.elevationNoRiver"), note: band ? `${surface} ${riverNote(above)}` : surface };
}

// Lower ground floods first: a band's tone and the chip that says it.
const BAND_VERDICT = { near: ["high", "business.elevationChipNear"], mid: ["some", "business.elevationChipMid"], high: ["low", "business.elevationChipHigh"] };

/** The "Height of the ground" fact beside the drawing (card.js): the band leads, with the heights and the limits folded
 *  away wherever there is a number. */
export function elevationFact(place) {
  const { value, note } = elevationWords(place.elevation);
  const [tone, chip] = BAND_VERDICT[riverBand(place.elevation?.above_river_m)] ?? [null, null];
  return factCard({ iconName: "map", label: t("business.elevation"), value, tone, chip: chip && t(chip),
    lead: place.elevation ? [] : h("p", { class: "fact-note" }, note),
    more: place.elevation && [h("p", {}, note), h("p", { class: "fineprint" }, t("business.elevationLimits"))] });
}
