// Run from 11_Platform_Draft:  node --test tests/insurance.test.mjs
// The Insurance tab (insurance.js) on the fake DOM: the model's cost beside a quoted yearly price, the empty states,
// and wording that informs without advising: no insurer named, no verdict on a quote, never "safe".
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { needsFirstLook } from "../app/static/js/cost.js";
import { useLang } from "../app/static/js/i18n.js";
import { compareRows, createInsurance, riskFigures } from "../app/static/js/insurance.js";
import en from "../app/static/js/strings/en.js";
import ms from "../app/static/js/strings/ms.js";
import { installFakeDom } from "./fake_dom.mjs";
import { shop } from "./point_fixtures.mjs";

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

const RESULT = { expected_yearly_loss_rm: 1440, per_flood: { 10: { total_rm: 0 }, 20: { total_rm: 0 }, 50: { total_rm: 41141 } } };

function mount() {
  const opened = [];
  const panel = document.createElement("section");
  const view = createInsurance(panel, { goto: (tab) => opened.push(tab) });
  return { panel, view, opened };
}

test("the model's figures are the yearly floor and the biggest flood with its chance in 10 years", () => {
  assert.deepEqual(riskFigures(RESULT), { yearly: 1440, bad: 41141, rp: "50", pct: 18, leftOut: false });
  assert.equal(riskFigures(undefined), null);
});

test("a typed quote joins the rows, and each bar is its share of the largest", () => {
  const figures = riskFigures(RESULT);
  assert.deepEqual(compareRows(0, figures).map((row) => row.key), ["yearly", "bad"], "no quote, no quote row");
  const rows = compareRows(900, figures);
  assert.deepEqual(rows.map((row) => [row.key, row.rm]), [["quote", 900], ["yearly", 1440], ["bad", 41141]]);
  assert.equal(rows[2].share, 1);
  assert.equal(Math.round(rows[0].share * 1000), 22);
});

test("with no place picked the tab shows how to pick one, and nothing else", () => {
  const { panel, view } = mount();
  view.render(undefined, undefined);
  const [empty, ...rest] = panel.children;
  assert.ok(empty.children.length > 0, "the empty state");
  assert.deepEqual(rest.map((part) => part.hidden), [true, true, true]);
  view.render(shop, { result: RESULT });
  assert.equal(empty.children.length, 0);
  assert.deepEqual(rest.map((part) => part.hidden), [false, false, false]);
});

test("a place with its estimate shows both figures, and typing a quote sets it beside them", () => {
  const { panel, view } = mount();
  view.render(shop, { result: RESULT });
  assert.match(panel.querySelector("h1").textContent, /^Flood insurance for /);
  assert.match(panel.textContent, /at least RM\s?1,440/);
  assert.match(panel.textContent, /RM\s?41,141/);
  const quote = panel.querySelector("#insurance-quote") ?? panel.querySelectorAll("input").find((input) => input.getAttribute("id") === "insurance-quote");
  quote.value = "900";
  quote.dispatch("input");
  assert.deepEqual(panel.querySelectorAll(".insurance-compare").at(-1).querySelectorAll("li").map((row) => row.getAttribute("class")), ["is-quote", "is-yearly", "is-bad"]);
  assert.match(panel.textContent, /not like-for-like/);
});

test("the quote typed stays with its place for this visit", () => {
  const { panel, view } = mount();
  view.render(shop, { result: RESULT });
  const quote = () => panel.querySelectorAll("input").find((input) => input.getAttribute("id") === "insurance-quote");
  quote().value = "900";
  quote().dispatch("input");
  view.render({ ...shop, id: "node-9", name: "Other" }, { result: RESULT });
  assert.equal(quote().getAttribute("value"), null);
  view.render(shop, { result: { ...RESULT } });
  assert.equal(quote().getAttribute("value"), "900");
});

test("with no estimate yet it says how to get one and offers Flood cost", () => {
  const { panel, view, opened } = mount();
  view.render(shop, undefined);
  assert.match(panel.textContent, /Open Flood cost to work out what a flood could cost here\./);
  panel.querySelectorAll("button").find((button) => button.textContent === "Change my answers").click();
  assert.deepEqual(opened, ["cost"]);
  view.render(shop, { busy: true });
  assert.match(panel.textContent, /Working it out/);
});

test("opening Insurance works out a first look, as Flood cost does", () => {
  const state = (tab) => ({ tab, placeKey: "a", estimates: {} });
  assert.ok(needsFirstLook(state("insurance"), shop));
  assert.ok(!needsFirstLook(state("reference"), shop));
});

test("the words inform without advising: no insurer named, no verdict, never safe, in both languages", () => {
  const INSURERS = /\b(AIG|Zurich|QBE|Tokio|Etiqa|Allianz|Takaful Malaysia|Berjaya|Sompo|RHB|MSIG|Chubb|Liberty|Lonpac|Great Eastern|Ikhlas|Howden|Marsh|Kurnia|Generali|Bjak|PolicyStreet)\b/i;
  const VERDICT = /\b(good deal|overpriced|worth it|you should|recommended|cheapest|best)\b/i;
  for (const strings of [en, ms]) {
    const words = Object.entries(strings).filter(([key]) => key.startsWith("insurance.")).map(([, text]) => text).join(" ");
    assert.ok(!INSURERS.test(words), "no insurer is named");
    assert.ok(!VERDICT.test(words), "no verdict on a quote");
    assert.ok(!/\b(safe|selamat)\b/i.test(words));
  }
  assert.match(en["insurance.lead"], /does not recommend any insurer, takaful operator or product, and is not financial advice/);
});

test("kinds of cover come by size of business, each with its covers and a published price, and point to BNM's lists", () => {
  const { panel, view } = mount();
  view.render(shop, { result: RESULT });
  const tiers = panel.querySelectorAll(".insurance-tier");
  assert.deepEqual(tiers.map((tier) => tier.querySelector("h3").textContent), ["Small shop", "Medium shop or small firm", "Factory, warehouse or large complex"]);
  for (const tier of tiers) {
    assert.equal(tier.querySelectorAll("li").length, 3);
    assert.ok(tier.querySelector(".insurance-example").textContent.length > 40, "a price line, or why there is none");
  }
  assert.match(tiers[0].textContent, /0\.086%/);
  assert.match(tiers[2].textContent, /No published prices/);
  const links = panel.querySelector(".insurance-kinds").querySelectorAll("a").map((a) => a.getAttribute("href"));
  assert.deepEqual(links, ["https://www.bnm.gov.my/list-of-licensed-financial-institutions", "https://www.bnm.gov.my/list-of-approved-and-registered-intermediaries"]);
});

test("vehicles and workers' pay are left out of the comparison, and said to be", () => {
  const wide = { expected_yearly_loss_rm: 3000, expected_yearly_shop_loss_rm: 1500,
    per_flood: { 10: { total_rm: 0 }, 20: { total_rm: 0 }, 50: { total_rm: 60000, vehicles_rm: 15000, wages_rm: 1000 } } };
  assert.deepEqual(riskFigures(wide), { yearly: 1500, bad: 44000, rp: "50", pct: 18, leftOut: true });
  const { panel, view } = mount();
  view.render(shop, { result: wide });
  assert.match(panel.textContent, /Vehicles and workers' pay from Flood cost are left out here/);
});

test("a first look is said to be one, not the owner's answers", () => {
  const { panel, view } = mount();
  view.render(shop, { result: RESULT, assumed: true });
  assert.match(panel.textContent, /First look: these are for a typical medium shop, not your answers\./);
  assert.ok(!/From your answers on Flood cost/.test(panel.textContent));
  view.render(shop, { result: { ...RESULT }, assumed: false });
  assert.ok(!/First look/.test(panel.textContent));
  assert.match(panel.textContent, /From your answers on Flood cost/);
});

test("going back to no place clears the old heading, so focus finds the empty state's", () => {
  const { panel, view } = mount();
  view.render(shop, { result: RESULT });
  view.render(undefined, undefined);
  assert.deepEqual(panel.querySelectorAll("h1").map((h1) => h1.textContent).length, 1);
});
