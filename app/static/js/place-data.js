// What both pages load and send for the place on show, with no state of their own: the old interface (main.js) and the
// new map's place sheet (map-gl-sheet.js) keep their answers in their own stores and pass a setter in.
import { h } from "./dom.js";
import { t } from "./i18n.js";

const PHOTO_MAX_EDGE = 1280;
const PHOTO_QUALITY = 0.85;

/** Shrink and re-encode in the browser: smaller upload, and location data in the file is dropped. */
export async function shrinkPhoto(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, PHOTO_MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = h("canvas", { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
  const context = canvas.getContext("2d");
  context.fillStyle = "#fff";   // JPEG has no transparency
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  if (typeof bitmap.close === "function") bitmap.close();   // frees the decoded photo now, not whenever the GC gets to it
  return canvas.toDataURL("image/jpeg", PHOTO_QUALITY);
}

/** An answer asked for once per place: none yet, or one that was an error (asked again), is asked for; `set` gets
 *  {busy: true}, then the answer, or {error}. `known` is the place's answer so far. */
export async function loadOnce(known, set, ask) {
  if (known && !known.error) return;
  set({ busy: true });
  try {
    set(await ask());
  } catch (error) {
    set({ error: error.message });
  }
}

/** A shop-front photo, read by the server (`send(image)` gives its answer): the photo so far (`before`) stays on show
 *  while the new one is read, and if reading it fails. */
export async function readShopPhoto(file, before, set, send) {
  set({ ...before, busy: true, error: null });
  try {
    const image = await shrinkPhoto(file).catch(() => { throw new Error(t("common.photoUnreadable")); });
    set({ ...before, busy: true, error: null, preview: image });
    set({ preview: image, ...(await send(image)) });
  } catch (error) {
    set({ ...before, busy: false, error: error.message });
  }
}

/** Prints one sheet alone (the flood plan or the area summary): a copy goes in #print-root, a child of the body, and
 *  business.css prints only that while it holds something. It is emptied after printing; where the browser never says
 *  so (iOS), the screen is unchanged anyway, as #print-root is never shown on screen. */
export function printSheet(sheet) {
  if (!sheet) return;
  let root = document.getElementById("print-root");
  if (!root) {
    root = h("div", { id: "print-root" });
    document.body.append(root);
    window.addEventListener("afterprint", () => root.replaceChildren());
  }
  root.replaceChildren(sheet.cloneNode(true));
  window.print();
}
