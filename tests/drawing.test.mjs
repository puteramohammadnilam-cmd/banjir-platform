// Run from 11_Platform_Draft:  node --test tests/drawing.test.mjs
// The line drawings made with Google Gemini (drawing.js, and the Reference header's in index.html): every file is there,
// small, and the size the page gives it; each says, in both languages, that it is a drawing made with Gemini.
import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { afterEach, test } from "node:test";

import { DRAWINGS, drawing } from "../app/static/js/drawing.js";
import { DEFAULT_LANG, useLang } from "../app/static/js/i18n.js";
import en from "../app/static/js/strings/en.js";
import ms from "../app/static/js/strings/ms.js";
import { installFakeDom } from "./fake_dom.mjs";

const DIR = new URL("../app/static/img/illustrations/", import.meta.url);
const PAGE = readFileSync(new URL("../app/static/index.html", import.meta.url), "utf8");
const MAX_BYTES = 150_000;   // as tools/gen_illustrations.py

installFakeDom();
afterEach(() => useLang(DEFAULT_LANG));

const [, streetWidth, streetHeight] = PAGE.match(/d-street\.png" width="(\d+)" height="(\d+)"/);
const ALL = { ...DRAWINGS, "d-street": { width: Number(streetWidth), height: Number(streetHeight) } };

/** A PNG's width and height, read from its header. */
const pngSize = (bytes) => [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];

test("each drawing has its WebP at 1x and 2x and a PNG, each small, the PNG the size the page gives it", () => {
  for (const [name, { width, height }] of Object.entries(ALL)) {
    for (const file of [`${name}.webp`, `${name}@2x.webp`, `${name}.png`]) {
      const bytes = statSync(new URL(file, DIR)).size;
      assert.ok(bytes < MAX_BYTES, `${file} is ${bytes} bytes`);
    }
    assert.deepEqual(pngSize(readFileSync(new URL(`${name}.png`, DIR))), [width, height], name);
  }
});

test("every drawing's words say, in both languages, that it is a drawing made with Google Gemini", () => {
  const keys = Object.keys(en).filter((key) => key.startsWith("drawing."));
  assert.equal(keys.length, Object.keys(ALL).length);
  for (const key of keys) {
    assert.match(en[key], /^Drawing made with Google Gemini: /, key);
    assert.match(ms[key], /^Lukisan dibuat dengan Google Gemini: /, key);
  }
});

test("drawing() gives a picture: WebP at 1x and 2x, then the PNG with its size, its words and a lazy load", () => {
  useLang("ms");
  const picture = drawing("e-ready");
  const [source, img] = picture.children;
  assert.equal(picture.tagName, "picture");
  assert.equal(source.getAttribute("srcset"), "img/illustrations/e-ready.webp 1x, img/illustrations/e-ready@2x.webp 2x");
  assert.equal(img.getAttribute("src"), "img/illustrations/e-ready.png");
  assert.deepEqual([img.getAttribute("width"), img.getAttribute("height")], ["560", "240"]);
  assert.equal(img.getAttribute("alt"), ms["drawing.ready"]);
  assert.equal(img.getAttribute("loading"), "lazy");
});

test("the Reference header shows the street drawing, and Sources credits Gemini for the drawings", () => {
  assert.match(PAGE, /<img src="img\/illustrations\/d-street\.png"[^>]*data-i18n-attr="alt:drawing\.street"/);
  assert.match(PAGE, /data-i18n="reference\.srcDraw">Made with Google Gemini/);
});
