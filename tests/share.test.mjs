// Run from 11_Platform_Draft:  node --test tests/share.test.mjs
// "Share this result" (share.js): the text and link sent with the picture, never a point's coordinates; the phone's
// share sheet where it takes a picture, else the picture saved and the text copied.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { shareButton, shareLink, sharePlace, shareText, wrap } from "../app/static/js/share.js";
import en from "../app/static/js/strings/en.js";
import ms from "../app/static/js/strings/ms.js";
import { installFakeDom } from "./fake_dom.mjs";
import { point, shop } from "./point_fixtures.mjs";

beforeEach(() => installFakeDom());

const FILE = new File(["png"], "banjir-check.png", { type: "image/png" });
const withBlobUrl = async (run) => {
  const real = URL.createObjectURL;
  URL.createObjectURL = () => "blob:x";
  try {
    return await run();
  } finally {
    URL.createObjectURL = real;
  }
};
/** A 2D context whose text is 10 px a character. */
const ctx = { measureText: (text) => ({ width: text.length * 10 }) };

test("the link is this page without its #fragment, where a point's coordinates are kept", () => {
  const where = { origin: "https://example.test", pathname: "/", search: "?place=node-1&lang=ms", hash: "#pt=3.1,101.5" };
  assert.equal(shareLink(where), "https://example.test/?place=node-1&lang=ms");
});

test("the text says the depth in the model and the chance, or that the model has no water", () => {
  assert.equal(shareText(shop, "50", "L"),
    "A Shop: 1.00 m of water in the model in a 1 in 50 years flood (18% chance in 10 years). Check your own shop: L");
  const dry = { ...shop, depth_m: { 10: null, 20: null, 50: null } };
  assert.equal(shareText(dry, "20", "L"), "A Shop: no water in the model in a 1 in 20 years flood. Check your own shop: L");
  assert.match(shareText(point(), "50", "L"), /^A spot I checked: 1\.76 m/);
  assert.doesNotMatch(shareText(point(), "50", "L"), /3\.02998|101\.53667/);
});

test("where the browser can share a picture, it goes to the share sheet with the text", async () => {
  const sent = [];
  const nav = { canShare: () => true, share: async (data) => { sent.push(data); } };
  assert.equal(await sharePlace(shop, "50", FILE, { nav, link: "L" }), "shared");
  assert.equal(sent[0].files[0].name, "banjir-check.png");
  assert.match(sent[0].text, /A Shop: 1\.00 m/);
});

test("closing the share sheet is not an error", async () => {
  const nav = { canShare: () => true, share: async () => { throw Object.assign(new Error("x"), { name: "AbortError" }); } };
  assert.equal(await sharePlace(shop, "50", FILE, { nav, link: "L" }), "cancelled");
});

test("elsewhere, or when the share sheet is refused, the picture is saved and the text copied", async () => {
  const copied = [];
  const clipboard = { writeText: async (text) => { copied.push(text); } };
  assert.equal(await withBlobUrl(() => sharePlace(shop, "50", FILE, { nav: { clipboard }, link: "L" })), "saved");
  assert.match(copied[0], /Check your own shop: L$/);
  const refused = { clipboard, canShare: () => true, share: async () => { throw Object.assign(new Error("x"), { name: "NotAllowedError" }); } };
  assert.equal(await withBlobUrl(() => sharePlace(shop, "50", FILE, { nav: refused, link: "L" })), "saved");
});

test("when the text cannot be copied, it says so instead of claiming it was", async () => {
  assert.equal(await withBlobUrl(() => sharePlace(shop, "50", FILE, { nav: {}, link: "L" })), "savedOnly");
  const denied = { clipboard: { writeText: async () => { throw new Error("denied"); } } };
  assert.equal(await withBlobUrl(() => sharePlace(shop, "50", FILE, { nav: denied, link: "L" })), "savedOnly");
});

test("lines wrap to fit, the last takes the rest, and a word too long is cut with an ellipsis", () => {
  assert.deepEqual(wrap(ctx, "aa bb cc", 50, 2), ["aa bb", "cc"]);
  assert.deepEqual(wrap(ctx, "aa bb cc dd ee", 50, 2), ["aa bb", "cc d…"]);
  assert.deepEqual(wrap(ctx, "abcdefghij", 50, 2), ["abcd…"]);
});

test("the picture's disclaimer fits its three lines in both languages, never cut", () => {
  // the canvas's 26 px font is about 14 px a character on average; 920 px of width
  const wide = { measureText: (text) => ({ width: text.length * 14 }) };
  for (const words of [en["share.footer"], ms["share.footer"]]) {
    assert.ok(wrap(wide, words, 920, 3).every((line) => !line.endsWith("…")), words);
  }
});

test("a failed picture says so when tapped, and a point's picture is made with no area name", async () => {
  const asked = [];
  const box = shareButton(point(), "50", "Town", { prepare: async (...args) => { asked.push(args[2]); throw new Error("no canvas"); } });
  box.querySelector("button").click();
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.match(box.querySelector(".share-status").textContent, /could not be made/);
  assert.ok(asked.every((area) => area === null));
});
