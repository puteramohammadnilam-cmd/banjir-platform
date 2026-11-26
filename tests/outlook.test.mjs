// node --test tests/outlook.test.mjs
// The "Next 5 days" card (outlook.js): MetMalaysia's Malay words in English, day names, the worst day's headline, the
// level of each day, warnings, and what it says when Google's rain is missing.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { createOutlook, dayName, metWords, worstDay } from "../app/static/js/outlook.js";
import { installFakeDom } from "./fake_dom.mjs";

const NOW = new Date("2026-11-26T02:00:00Z");   // 10 am on 26 Nov in Malaysia
const day = (date, mm, level, extra = {}) => ({ date, rain_mm: mm, chance_pct: mm == null ? null : 75, level, warned: false, met: null, big_tide: false, ...extra });
const DAYS = [day("2026-11-26", 6.3, "low", { met: { text: "Ribut petir", when: "Petang dan Malam" } }), day("2026-11-27", 48.1, "high", { big_tide: true }),
  day("2026-11-28", 24.4, "watch"), day("2026-11-29", 17.4, "low"), day("2026-11-30", 7.3, "low")];
const THRESHOLDS = { watch_mm: 20, high_mm: 30, set_from: "Shah Alam", since: 2024, floods: 10, watch_days: 79, watch_floods: 8, high_days: 28, high_floods: 5 };
const FOUND = { days: DAYS, warnings: [], trend: "rising", rain: "ok", met: "ok", levels: true, met_place: "Shah Alam", thresholds: THRESHOLDS, source: "https://www.met.gov.my/" };

beforeEach(() => {
  installFakeDom();
  useLang("en");
});

function mount(state) {
  const section = document.createElement("section");
  createOutlook(section, () => NOW).set(state);
  return section;
}

test("MetMalaysia's Malay words read in English, and as given in Malay", () => {
  assert.equal(metWords({ text: "Ribut petir di beberapa tempat", when: "Petang" }, "en"), "Thunderstorms in places, afternoon");
  assert.equal(metWords({ text: "Tiada Hujan", when: "Sepanjang Hari" }, "en"), "No rain, all day");
  assert.equal(metWords({ text: "Hujan di beberapa tempat di kawasan pantai", when: "" }, "en"), "Rain in places along the coast");
  assert.equal(metWords({ text: "Hujan lebat luar biasa", when: "Pagi" }, "en"), "Hujan lebat luar biasa, morning", "a phrase not listed stays as written");
  assert.equal(metWords({ text: "Ribut petir", when: "Petang dan Malam" }, "ms"), "Ribut petir, petang dan malam");
  assert.equal(metWords(null), "");
});

test("days are Today, Tomorrow, then a short date in Malaysian time", () => {
  assert.equal(dayName("2026-11-26", NOW), "Today");
  assert.equal(dayName("2026-11-27", NOW), "Tomorrow");
  assert.match(dayName("2026-11-28", NOW), /28/);
});

test("the worst day is the highest level, the wettest among those", () => {
  assert.equal(worstDay(DAYS).date, "2026-11-27");
  assert.equal(worstDay([day("a", 1, "low"), day("b", 9, "low")]).date, "b");
  assert.equal(worstDay([day("a", null, null)]), null);
});

test("the card says Checking until the answer comes, and so the page can see it scroll into view", () => {
  const section = mount({ busy: true });
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /Next 5 days.*Checking/);
  assert.match(mount({ error: true }).textContent, /could not be loaded/);
});

test("the card leads with the worst day, then a row a day with its level, rain and MetMalaysia's words", () => {
  const section = mount({ data: FOUND });
  assert.match(section.textContent, /Tomorrow: about 48 mm of rain forecast\. In Shah Alam since 2024, most days this wet had no recorded flood; about 1 in 6 did\. More rain ahead\./);
  const rows = [...section.querySelector(".outlook-days").children];
  assert.equal(rows.length, 5);
  assert.match(rows[0].textContent, /Today.*Low.*6 mm · 75%.*Thunderstorms, afternoon and night/);
  assert.match(rows[1].textContent, /Tomorrow.*High.*48 mm.*Big tide/);
  assert.match(rows[2].textContent, /Watch/);
  assert.match(section.textContent, /Not a flood warning/);
  assert.match(section.textContent, /Watch: 20 mm.*High: 30 mm/);
});

test("a MetMalaysia warning is shown first, and a quiet week says so", () => {
  const warned = { ...FOUND, days: [day("2026-11-26", 3, "high", { warned: true }), ...DAYS.slice(1).map((d) => ({ ...d, level: "low" }))],
    warnings: [{ title_en: "Thunderstorms Warning", title_ms: "Amaran Ribut Petir", valid_from: "2026-11-26T14:00:00", valid_to: "2026-11-26T17:00:00" }] };
  const section = mount({ data: warned });
  assert.match(section.querySelector(".outlook-warning").textContent, /MetMalaysia: Thunderstorms Warning, until/);
  assert.match(section.textContent, /Today: a MetMalaysia continuous-rain warning covers this area/);
  const quiet = mount({ data: { ...FOUND, trend: "steady", days: DAYS.map((d) => ({ ...d, level: "low" })) } });
  assert.match(quiet.textContent, /No day with 20 mm of rain or more forecast in the next 5 days\./);
  assert.doesNotMatch(quiet.textContent, /rain ahead/, "steady says nothing");
});

test("without Google's rain the rows keep MetMalaysia's words and the card says why the amounts are missing", () => {
  const noRain = { ...FOUND, rain: "capped", trend: null, days: DAYS.map((d) => ({ ...d, rain_mm: null, chance_pct: null, level: null })) };
  const section = mount({ data: noRain });
  assert.match(section.textContent, /free Google Weather checks are used up/);
  assert.match([...section.querySelector(".outlook-days").children][0].textContent, /Today.*–.*Thunderstorms/);
  assert.equal(section.querySelector(".outlook-headline"), null);
});

test("the card in Malay", () => {
  useLang("ms");
  const section = mount({ data: FOUND });
  assert.match(section.textContent, /5 hari akan datang/);
  assert.match(section.textContent, /Esok: kira-kira 48 mm hujan diramal\. Di Shah Alam sejak 2024/);
  assert.match([...section.querySelector(".outlook-days").children][1].textContent, /Tinggi.*Air pasang besar/);
});

test("before any answer the card already says it is checking, so it is never an empty box", () => {
  const section = document.createElement("section");
  createOutlook(section, () => NOW);
  assert.match(section.textContent, /Next 5 days.*Checking/);
});

test("a watch day says how often a day that wet had a flood, and the method says most such days had none", () => {
  const watch = { ...FOUND, days: DAYS.map((d) => ({ ...d, level: d.level === "high" ? "watch" : d.level })) };
  const section = mount({ data: watch });
  assert.match(section.textContent, /Tomorrow: about 48 mm of rain forecast\. In Shah Alam since 2024, about 1 in 10 days this wet had a recorded flood\./);
  assert.match(section.textContent, /8 of 10 recorded floods came on a day of 20 mm or more, but most such days had no flood/);
  assert.match(section.textContent, /Google Weather, whose day runs 7 am to 7 am/);
});

test("outside the area the levels were set on, the card gives the forecast with no level", () => {
  const plain = { ...FOUND, levels: false, trend: null, days: DAYS.map((d) => ({ ...d, level: null })) };
  const section = mount({ data: plain });
  assert.match(section.textContent, /Tomorrow has the most rain forecast: about 48 mm\./);
  assert.match(section.textContent, /No levels here: they were set on the floods in Shah Alam/);
  assert.equal(section.querySelector(".outlook-level"), null);
  assert.doesNotMatch(section.textContent, /recorded flood/);
});

test("when Google expects rain worth a level and MetMalaysia says none, the row says the forecasts disagree", () => {
  const split = { ...FOUND, days: [DAYS[0], { ...DAYS[1], met: { text: "Tiada Hujan", when: "Sepanjang Hari" } }, ...DAYS.slice(2)] };
  const rows = [...mount({ data: split }).querySelector(".outlook-days").children];
  assert.match(rows[1].textContent, /No rain, all day · Forecasts disagree/);
  assert.doesNotMatch(rows[0].textContent, /disagree/);
});

test("a MetMalaysia outage is said, not shown as no warning", () => {
  assert.match(mount({ data: { ...FOUND, met: "down" } }).textContent, /MetMalaysia could not be reached just now/);
});

test("an answer from an earlier day asks for a reload instead of calling yesterday Today", () => {
  const section = document.createElement("section");
  createOutlook(section, () => new Date("2026-11-27T02:00:00Z")).set({ data: FOUND });
  assert.match(section.textContent, /This outlook is from an earlier day\. Reload the page/);
  assert.equal(section.querySelector(".outlook-days"), null);
});

test("when today's share of Google checks is used up, the card says rain amounts are back tomorrow", () => {
  const noRain = { ...FOUND, rain: "capped_day", trend: null, days: DAYS.map((d) => ({ ...d, rain_mm: null, chance_pct: null, level: null })) };
  assert.match(mount({ data: noRain }).textContent, /rain amounts are back tomorrow/);
});

test("with an Arus address set, the card links to it and says it is the author's own model", () => {
  const section = mount({ data: { ...FOUND, arus: "https://arus.example/map?lat=3.07&lon=101.52" } });
  const link = [...section.querySelectorAll("a")].find((a) => a.textContent.includes("Arus"));
  assert.equal(link.getAttribute("href"), "https://arus.example/map?lat=3.07&lon=101.52");
  assert.match(section.textContent, /Arus is Farhan Syah's own forecast model, not checked by MyFlood/);
  assert.doesNotMatch(mount({ data: FOUND }).textContent, /Arus/);
});
