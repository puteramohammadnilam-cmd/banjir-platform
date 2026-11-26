// The new map's cards (map.html): the flood size card, the layers card, and the place card a shop or a section opens,
// Google Maps style. Built with dom.js's h(), so every word goes in as text. map-gl.js places and fills them.
// Layout adapted from Arus's "Site Flood Check" card by Farhan Syah (MIT, vendor/LICENSE-arus.txt); every number is
// MyFlood's own.
import { CHANCE_YEARS, SCENARIOS, chanceWithin, depthWords, h, kindText, roadName, UNNAMED_ROAD } from "./dom.js";
import { formatNumber, t } from "./i18n.js";
import { badge, nearestShelter } from "./map-gl-data.js";

const pct = (rp) => Math.round(chanceWithin(Number(rp), CHANCE_YEARS) * 100);
const dot = (tone, key) => h("span", {}, h("i", { class: `mg-dot mg-dot-${tone}` }), t(key));
/** The shop dots' colours: on the layers card, and on phones (where that card is hidden) under the flood size. */
const dotKey = (extraClass = "") => h("div", { class: `mg-dots ${extraClass}`.trim() }, dot("dry", "mg.dot.dry"), dot("watch", "mg.dot.shallow"),
  dot("high", "mg.dot.deep"), dot("deep", "mg.dot.veryDeep"));
const metres = (depth) => (typeof depth === "number" && depth > 0 ? t("common.metres", { m: depth.toFixed(2) }) : t("mg.dry"));

/** The flood size card: how many businesses get water, and the three flood sizes to pick from. */
export function summaryCard({ wet, all, rp, onPick }) {
  const pick = (size) => h("button", { type: "button", class: size === rp ? "on" : null, "aria-pressed": String(size === rp), "data-rp": size,
    onclick: () => onPick(size) }, h("b", {}, t("mg.rpShort", { rp: size })), h("span", {}, t("mg.chance", { pct: pct(size) })));
  return [
    h("p", { class: "mg-k" }, t("mg.floodSize")),
    h("p", { class: "mg-big" }, t("mg.wetOf", { wet: formatNumber(wet), all: formatNumber(all) })),
    h("p", { class: "mg-strong" }, t("mg.wetWords")),
    h("p", { class: "mg-muted mg-small mg-wet-sub" }, t("mg.wetSub", { rp, pct: pct(rp) })),
    h("div", { class: "mg-rp", role: "group", "aria-label": t("mg.floodSize") }, SCENARIOS.map(pick)),
    dotKey("mg-phone-only"),
  ];
}

/** The layers card: a switch for each layer, the squares' depth ramp and the shop dots' colours. */
export function layersCard(visible, onToggle) {
  const toggle = (key) => h("label", {}, h("input", { type: "checkbox", checked: visible[key],
    onchange: (event) => onToggle(key, event.target.checked) }), " ", t(`mg.layer.${key}`));
  return [
    h("p", { class: "mg-k" }, t("mg.layers")),
    ...["sections", "squares", "shops", "shelters"].map(toggle),
    h("div", { class: "mg-ramp", "aria-hidden": "true" }),
    h("div", { class: "mg-ramp-key" }, h("span", {}, t("mg.ramp.low")), h("span", {}, t("mg.ramp.high"))),
    dotKey(),
    h("p", { class: "mg-muted mg-small mg-note" }, t("mg.layersNote")),
  ];
}

const head = (title, onClose) => [
  h("div", { class: "mg-handle", "aria-hidden": "true" }),
  h("div", { class: "mg-place-head" }, h("h2", { tabindex: "-1" }, title),
    h("button", { type: "button", class: "mg-x", "aria-label": t("mg.close"), onclick: onClose }, "✕")),
];
const tile = (label, value, note = null, isPicked = false) => h("div", { class: isPicked ? "mg-stat mg-picked" : "mg-stat" },
  h("div", { class: "mg-stat-k" }, label), h("div", { class: "mg-stat-v" }, value), note && h("div", { class: "mg-stat-k" }, note));
const link = (text, href, primary = false, external = false) => h("a", { class: primary ? "mg-btn mg-primary" : "mg-btn", href,
  target: external ? "_blank" : null, rel: external ? "noopener noreferrer" : null }, text);

/** The words under a shop's name: its kind, its section and its road when the road has a name. */
function shopLine(shop, sectionName) {
  const road = shop.road?.name && shop.road.name !== UNNAMED_ROAD ? roadName(shop.road.name) : null;
  return [kindText(shop), sectionName, road].filter(Boolean).join(" · ");
}

function shopSentence(depth, rp) {
  if (!(typeof depth === "number" && depth > 0)) return t("mg.say.dry", { rp });
  return t("mg.say.wet", { rp, m: depth.toFixed(1), words: depthWords(depth) });
}

/** The relief centre nearest a shop: the server's (app/places.py), or worked out here from the area's list. */
function shelterOf(shop, shelters) {
  const given = shop.shelter;
  if (given?.name && Number.isFinite(given.distance_m)) return { shelter: given, km: given.distance_m / 1000 };
  return nearestShelter(shop, shelters);
}

/** A shop's card: its badge and one sentence for the flood size picked, the water at its door for each size, the
 *  nearest relief centre, and the ways on: the main page's details and cost, share, 3D and directions. */
export function shopCard(shop, { rp, sectionName, shelters, links, onClose, onShare }) {
  const depth = shop.depth_m?.[rp];
  const mark = badge(depth);
  const near = shelterOf(shop, shelters);
  return [
    ...head(shop.name, onClose),
    h("p", { class: "mg-sub" }, shopLine(shop, sectionName)),
    h("span", { class: `mg-badge mg-${mark.tone}` }, t(mark.key)),
    h("p", { class: "mg-say" }, shopSentence(depth, rp)),
    h("div", { class: "mg-stats" }, SCENARIOS.map((size) => tile(t("scenario.label", { rp: size }), metres(shop.depth_m?.[size]), null, size === rp)),
      tile(t("mg.shelter"), near ? t("mg.km", { km: formatNumber(near.km, { maximumFractionDigits: 1 }) }) : "–", near?.shelter.name)),
    h("div", { class: "mg-acts" }, link(t("mg.details"), links.details, true), link(t("mg.cost"), links.cost),
      h("button", { type: "button", class: "mg-btn", onclick: onShare }, t("mg.share")),
      links.see3d && link(t("business.see3d"), links.see3d), link(t("mg.directions"), links.directions, false, true)),
    h("p", { class: "mg-fine" }, t("mg.fine"), near ? ` ${t("business.shelterLine")}` : null,
      shop.map_last_edited ? ` ${t("mg.edited", { date: shop.map_last_edited })}` : null),
  ];
}

/** A checked point's card, as a shop's: where it is (point.js pointHeader gives the title and the line under it), its
 *  badge and sentence for the square, the water there for each flood size, the server's nearest relief centre, and the
 *  ways on: the main page's details and cost, share, move the pin, directions. */
export function pointCard(place, { rp, title, subline, links, onClose, onShare, onMove }) {
  const depth = place.depth_m?.[rp];
  const mark = badge(depth);
  const near = shelterOf(place, []);   // only the server's: a point can be far from this area's own list
  const isWet = typeof depth === "number" && depth > 0;
  return [
    ...head(title, onClose),
    subline && h("p", { class: "mg-sub" }, subline),
    h("span", { class: `mg-badge mg-${mark.tone}` }, t(mark.key)),
    h("p", { class: "mg-say" }, isWet ? t("mg.say.pointWet", { rp, m: depth.toFixed(1), words: depthWords(depth) }) : t("mg.say.pointDry", { rp })),
    h("div", { class: "mg-stats" }, SCENARIOS.map((size) => tile(t("scenario.label", { rp: size }), metres(place.depth_m?.[size]), null, size === rp)),
      tile(t("mg.shelter"), near ? t("mg.km", { km: formatNumber(near.km, { maximumFractionDigits: 1 }) }) : "–", near?.shelter.name)),
    h("div", { class: "mg-acts" }, link(t("mg.details"), links.details, true), link(t("mg.cost"), links.cost),
      h("button", { type: "button", class: "mg-btn", onclick: onShare }, t("mg.share")),
      h("button", { type: "button", class: "mg-btn", onclick: onMove }, t("mg.movePin")),
      link(t("mg.directions"), links.directions, false, true)),
    h("p", { class: "mg-fine" }, t("mg.fine"), near ? ` ${t("business.shelterLine")}` : null, isWet ? null : ` ${t("point.noWaterNote")}`),
  ].filter(Boolean);
}

/** A section's card: its share of wet squares, its wet businesses, and the way to it on the main page. */
export function sectionCard(section, { rp, link: href, onClose }) {
  const exact = section[`s${rp}`] * 100;
  const share = Math.round(exact);
  let tone = "dry";
  if (share >= 30) tone = "deep";
  else if (share >= 5) tone = "high";
  else if (exact > 0) tone = "watch";
  return [
    ...head(section.name, onClose),
    h("p", { class: "mg-sub" }, t("mg.sectionSub", { n: formatNumber(section.n) })),
    h("span", { class: `mg-badge mg-${tone}` }, exact > 0 && share < 1 ? t("mg.wetShareUnder") : t("mg.wetShare", { pct: share })),
    h("p", { class: "mg-say" }, t("mg.sectionSay", { rp, wet: formatNumber(section[`w${rp}`]), n: formatNumber(section.n) })),
    h("div", { class: "mg-acts" }, link(t("mg.openSection"), href, true)),
  ];
}
