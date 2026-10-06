// The line drawings made with Google Gemini for the 6 Oct 2026 look (tools/gen_illustrations.py makes the files). They
// are drawings, never photos of a real place, and their alt text says so. The Reference header's drawing (d-street) is
// in index.html; the others are built here.
import { h } from "./dom.js";
import { t } from "./i18n.js";

const DIR = "img/illustrations/";

// name: its size in CSS pixels, as tools/gen_illustrations.py makes it, and the key of its alt text
export const DRAWINGS = Object.freeze({
  "a-shop": { width: 320, height: 180, alt: "drawing.shop" },
  "b-contents": { width: 320, height: 180, alt: "drawing.contents" },
  "c-cover": { width: 320, height: 180, alt: "drawing.cover" },
  "e-ready": { width: 560, height: 240, alt: "drawing.ready" },
});

/** One drawing: WebP at 1x and 2x, a PNG for browsers without WebP, and loaded only when it comes into view. */
export function drawing(name) {
  const { width, height, alt } = DRAWINGS[name];
  return h("picture", { class: `drawing drawing-${name}` },
    h("source", { type: "image/webp", srcset: `${DIR}${name}.webp 1x, ${DIR}${name}@2x.webp 2x` }),
    h("img", { src: `${DIR}${name}.png`, width, height, alt: t(alt), loading: "lazy", decoding: "async" }));
}
