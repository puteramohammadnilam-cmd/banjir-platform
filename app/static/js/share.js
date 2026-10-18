// "Share this result" on My business: a picture of the place's modelled water (its name, the depth in the flood size on
// show, the three sizes side by side and the chance in 10 years) with a short text and a link to this page, through the
// phone's share sheet (WhatsApp and the rest). Where the browser cannot share a picture, it is saved and the text with
// the link is copied. Drawn in the browser on a canvas; nothing is sent to this site. A point's link leaves out its
// #fragment, so its coordinates are never shared; the picture names it only as a spot checked.
import { CHANCE_YEARS, SCENARIOS, band, chanceWithin, depthText, depthWords, h } from "./dom.js";
import { t } from "./i18n.js";

const W = 1080;
const H = 1350;
const PAD = 80;
const FONT = '"Plus Jakarta Sans", system-ui, sans-serif';
const SERIF = '"Source Serif 4", Georgia, serif';   // headings and figures, as on the page (tokens.css --font-serif)
const COLORS = { brand: "#0c447c", ink: "#0d1b2a", ink2: "#3d4f63", wash: "#e8f0f8", line: "#c3ccd7", white: "#ffffff" };

// metres, or the short "no water" (the long one does not fit a box)
const short = (depth) => (band(depth) ? t("common.metres", { m: depth.toFixed(2) }) : t("compare.noWater"));
const pct = (rp) => Math.round(chanceWithin(Number(rp), CHANCE_YEARS) * 100);
const placeName = (premise) => (premise.is_point || !premise.name ? t("share.pointName") : premise.name);

/** The link to share: this page without its #fragment (where a point's coordinates are kept). */
export const shareLink = (where = globalThis.location) => `${where.origin}${where.pathname}${where.search}`;

/** The words sent with the picture. */
export function shareText(premise, rp, link) {
  const depth = premise.depth_m?.[rp];
  const key = band(depth) ? "share.textWet" : "share.textDry";
  return t(key, { name: placeName(premise), depth: depthText(depth), rp, pct: pct(rp), years: CHANCE_YEARS, link });
}

/** `line` cut with an ellipsis until it fits `width` at the context's font; unchanged when it fits. */
function fit(ctx, line, width) {
  if (ctx.measureText(line).width <= width) return line;
  let cut = line;
  while (cut && ctx.measureText(`${cut}…`).width > width) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}…`;
}

/** Lines of `text` that fit `width` at the context's font, at most `max`: the last one takes the rest, and any line
 *  still too wide (one long word) is cut with an ellipsis. */
export function wrap(ctx, text, width, max) {
  const lines = [];
  let line = "";
  for (const word of text.split(" ")) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width <= width || !line) line = next;
    else { lines.push(line); line = word; }
  }
  lines.push(line);
  const kept = lines.length <= max ? lines : [...lines.slice(0, max - 1), lines.slice(max - 1).join(" ")];
  return kept.map((each) => fit(ctx, each, width));
}

function text(ctx, value, x, y, { size, weight = 400, color = COLORS.ink, align = "left", font = FONT }) {
  ctx.font = `${weight} ${size}px ${font}`;
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.fillText(value, x, y);
}

/** The band with the tool's name and the area. */
function drawTop(ctx, areaName) {
  ctx.fillStyle = COLORS.brand;
  ctx.fillRect(0, 0, W, 200);
  text(ctx, "MyFlood", PAD, 105, { size: 56, weight: 700, color: COLORS.white });
  text(ctx, areaName ?? "", PAD, 160, { size: 32, color: COLORS.wash });
}

/** The three flood sizes side by side, the one on show filled. */
function drawSizes(ctx, premise, rp, top) {
  const gap = 24;
  const boxW = (W - 2 * PAD - 2 * gap) / SCENARIOS.length;
  SCENARIOS.forEach((size, i) => {
    const x = PAD + i * (boxW + gap);
    const isOn = size === rp;
    ctx.fillStyle = isOn ? COLORS.brand : COLORS.wash;
    ctx.fillRect(x, top, boxW, 170);
    const color = isOn ? COLORS.white : COLORS.ink;
    text(ctx, t("common.rpYears", { rp: size }), x + boxW / 2, top + 55, { size: 30, weight: 600, color, align: "center" });
    text(ctx, short(premise.depth_m?.[size]), x + boxW / 2, top + 125, { size: 46, weight: 600, color, align: "center", font: SERIF });
  });
}

/** The picture, as a canvas. */
export function drawCard(premise, rp, areaName, doc = document) {
  const canvas = doc.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = COLORS.white;
  ctx.fillRect(0, 0, W, H);
  drawTop(ctx, areaName);
  ctx.font = `600 64px ${SERIF}`;
  wrap(ctx, placeName(premise), W - 2 * PAD, 2).forEach((line, i) => text(ctx, line, PAD, 320 + i * 76, { size: 64, weight: 600, font: SERIF }));
  const depth = premise.depth_m?.[rp];
  text(ctx, t("share.inFlood", { rp }), PAD, 520, { size: 36, color: COLORS.ink2 });
  text(ctx, short(depth), PAD, 690, { size: 170, weight: 600, color: COLORS.brand, font: SERIF });
  if (band(depth)) text(ctx, depthWords(depth), PAD, 770, { size: 48, weight: 600 });
  drawSizes(ctx, premise, rp, 850);
  text(ctx, t("scenario.chance", { pct: pct(rp), years: CHANCE_YEARS }), PAD, 1100, { size: 34, color: COLORS.ink2 });
  ctx.fillStyle = COLORS.line;
  ctx.fillRect(PAD, 1170, W - 2 * PAD, 2);
  ctx.font = `400 28px ${FONT}`;
  // the disclaimer has room for three lines and is never cut short in either language (tests/share.test.mjs)
  wrap(ctx, t("share.footer"), W - 2 * PAD, 3).forEach((line, i) => text(ctx, line, PAD, 1215 + i * 36, { size: 26, color: COLORS.ink2 }));
  text(ctx, globalThis.location?.host ?? "", PAD, 1325, { size: 28, weight: 700, color: COLORS.brand });
  return canvas;
}

const toBlob = (canvas) => new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("no image"))), "image/png"));

/** The picture as a PNG file, its fonts loaded first. Made before the tap: a phone gives the share sheet only for a short
 *  time after it (iOS about a second), too short to draw and encode in. */
export async function makeFile(premise, rp, areaName, draw = drawCard) {
  const fonts = globalThis.document?.fonts;   // the picture's words in the page's font, each weight it uses
  await Promise.all([`400 40px ${FONT}`, `600 40px ${FONT}`, `700 40px ${FONT}`, `600 40px ${SERIF}`].map((face) => fonts?.load(face).catch(() => null)));
  return new File([await toBlob(draw(premise, rp, areaName))], t("share.fileName"), { type: "image/png" });
}

/** Save the picture and copy the text: "saved" when the text was copied too, "savedOnly" when copying was refused. */
async function saveAndCopy(file, words, nav) {
  // both started before any wait, while the tap still counts
  const copying = (nav?.clipboard?.writeText(words) ?? Promise.reject(new Error("no clipboard"))).then(() => true, () => false);
  const url = URL.createObjectURL(file);
  h("a", { href: url, download: file.name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return (await copying) ? "saved" : "savedOnly";
}

/** Share the ready picture and text through the share sheet; where there is none, or it is refused, save the picture
 *  and copy the text. Gives "shared", "cancelled", "saved" or "savedOnly". */
export async function sharePlace(premise, rp, file, { nav = globalThis.navigator, link = shareLink() } = {}) {
  const words = shareText(premise, rp, link);
  if (nav?.canShare?.({ files: [file] })) {
    try {
      await nav.share({ files: [file], text: words });
      return "shared";
    } catch (error) {
      if (error?.name === "AbortError") return "cancelled";   // the person closed the share sheet
      // refused (the tap's permission ran out, or a policy): save and copy instead
    }
  }
  return saveAndCopy(file, words, nav);
}

const STATUS = { saved: "share.saved", savedOnly: "share.savedOnly" };
const later = (fn) => (globalThis.requestIdleCallback ?? ((run) => setTimeout(run, 300)))(fn);

/** The button and its status line, for the place and flood size on show. The picture is made in the background as the
 *  button appears, so the tap goes straight to the share sheet. A point's picture names no area. */
export function shareButton(premise, rp, areaName, { prepare = makeFile } = {}) {
  const area = premise.is_point ? null : areaName;
  let ready = new Promise((resolve) => later(() => resolve(prepare(premise, rp, area).catch(() => null))));
  const status = h("p", { class: "fact-note share-status", "aria-live": "polite" });
  const button = h("button", { type: "button", class: "btn btn-secondary share-button", onclick: async () => {
    status.textContent = t("share.making");
    const file = (await ready) ?? (await (ready = prepare(premise, rp, area).catch(() => null)));
    if (!file) {
      status.textContent = t("share.failed");
      return;
    }
    const done = await sharePlace(premise, rp, file);
    status.textContent = STATUS[done] ? t(STATUS[done]) : "";
  } }, t("share.button"));
  return h("div", { class: "share" }, button, status);
}
