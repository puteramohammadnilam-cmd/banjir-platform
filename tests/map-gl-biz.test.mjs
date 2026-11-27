// node --test tests/map-gl-biz.test.mjs
// My business in a sheet over the new map (js/map-gl-biz.js): opening it adds one step to the browser's history and
// asks for the place's answers only then (the Google Maps listing only for a business, and only with Maps on); closing
// it from the page takes that step off quietly; the phone's back closes it. No network: fetch is faked.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { createBusinessSheet } from "../app/static/js/map-gl-biz.js";
import { loadOnce } from "../app/static/js/place-data.js";
import { installFakeDom } from "./fake_dom.mjs";
import { HOME, point, shop } from "./point_fixtures.mjs";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
let asked;
let steps;
let popListeners;

beforeEach(() => {
  installFakeDom();
  useLang("en");
  document.body = document.createElement("body");
  asked = [];
  steps = { pushed: 0, back: 0 };
  popListeners = [];
  globalThis.window = { addEventListener: (type, listener) => { if (type === "popstate") popListeners.push(listener); } };
  globalThis.history = { pushState: () => { steps.pushed += 1; }, back: () => { steps.back += 1; popListeners.forEach((listener) => listener()); } };
  globalThis.fetch = async (path) => {
    asked.push(String(path).split("?")[0]);
    return { json: async () => ({ success: true, data: { areas: [] } }) };
  };
});

function mount(status = { maps_ready: true, ai_ready: true }) {
  const sheet = document.createElement("section");
  sheet.hidden = true;
  const panel = document.createElement("div");
  const back = document.createElement("button");
  const changed = [];
  const biz = createBusinessSheet({ sheet, panel, back, status, areas: async () => [],
    on: { pickRp() {}, showOnMap() {}, movePin() {}, goto() {}, ask() {}, openArea() {}, find() {}, checkPoint() {}, changed: () => changed.push(sheet.hidden) } });
  return { sheet, panel, back, biz, changed };
}

test("opening the sheet shows the place, adds one history step, and only then asks for its listing and car spot", async () => {
  const { sheet, panel, biz, changed } = mount();
  assert.deepEqual(asked.filter((path) => path !== "/api/areas"), [], "nothing asked for before the sheet opens");
  biz.open(shop, HOME, "20");
  await settle();
  assert.equal(sheet.hidden, false);
  assert.equal(steps.pushed, 1);
  assert.ok(panel.textContent.includes(shop.name));
  assert.ok(asked.includes(`/api/place/${shop.id}`) && asked.includes("/api/dry-spot"));
  assert.deepEqual(changed, [false]);
  biz.open(shop, HOME, "50");   // already open: no second step
  assert.equal(steps.pushed, 1);
});

test("a point, or a build without Google Maps, asks for no listing", async () => {
  mount({ maps_ready: false }).biz.open(shop, HOME, "20");
  mount().biz.open(point(), HOME, "20");
  await settle();
  assert.ok(!asked.some((path) => path.startsWith("/api/place/")));
  assert.equal(asked.filter((path) => path === "/api/dry-spot").length, 2);
});

test("Back in the sheet closes it and takes its step off; the phone's back closes it too", () => {
  const first = mount();
  first.biz.open(shop, HOME, "20");
  first.back.click();
  assert.equal(first.sheet.hidden, true);
  assert.equal(steps.back, 1);
  assert.equal(first.biz.isOpen(), false);
  const second = mount();
  second.biz.open(shop, HOME, "20");
  popListeners.at(-1)();   // the browser's own back
  assert.equal(second.sheet.hidden, true);
  assert.equal(steps.back, 1, "the browser already went back: no second step off");
});

test("a link that opens the sheet adds no step, so closing it does not leave the page", () => {
  const { sheet, biz } = mount();
  biz.open(shop, HOME, "20", { push: false });
  assert.equal(steps.pushed, 0);
  biz.close();
  assert.equal(sheet.hidden, true);
  assert.equal(steps.back, 0);
});

test("an answer asked for once is asked again only after an error", async () => {
  const got = [];
  await loadOnce(undefined, (value) => got.push(value), async () => ({ ok: 1 }));
  await loadOnce({ ok: 1 }, (value) => got.push(value), async () => ({ ok: 2 }));
  await loadOnce({ error: "x" }, (value) => got.push(value), async () => { throw new Error("down"); });
  assert.deepEqual(got, [{ busy: true }, { ok: 1 }, { busy: true }, { error: "down" }]);
});
