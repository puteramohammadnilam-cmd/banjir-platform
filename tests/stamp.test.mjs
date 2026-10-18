// Run from 11_Platform_Draft:  node --test tests/stamp.test.mjs
// Where the Area overview's figures come from (stamp.js): the sources and their licences, the day the flood record was
// checked, a citation that never carries a point after #, and the flood size as a sentence.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { useLang } from "../app/static/js/i18n.js";
import { citation, renderStamp, scenarioSentence } from "../app/static/js/stamp.js";
import { installFakeDom } from "./fake_dom.mjs";

beforeEach(() => { installFakeDom(); useLang("en"); });

test("the source line names the model, the map and their licences, and the day the record was checked", () => {
  const node = document.createElement("div");
  renderStamp(node, { history: { checked: "2026-10-04" }, areaName: "Home Town" });
  assert.match(node.textContent, /JRC global river flood model v2\.1 \(CC BY 4\.0\).*OpenStreetMap contributors \(ODbL\).*checked 4 Oct 2026/);
  assert.match(node.querySelector("summary").textContent, /How to cite/);
  renderStamp(node, { history: null, areaName: "Home Town" });
  assert.doesNotMatch(node.textContent, /checked/);
});

test("the citation names the area and the page, never what follows #", () => {
  const text = citation("Home Town", "https://example.test/?area=home#place=pt:3.1,101.5", new Date(2026, 9, 6, 12));
  assert.equal(text, "MyFlood (2026). Modelled flood depth for businesses in Home Town. https://example.test/?area=home. Accessed 6 Oct 2026. Data: European Commission JRC (CC BY 4.0); OpenStreetMap contributors (ODbL).");
});

test("the flood size on show reads as a sentence with its chance, in both languages", () => {
  assert.equal(scenarioSentence("50"), "Showing a flood expected once in 50 years. Chance of at least one this big in the next 10 years: 18%.");
  useLang("ms");
  assert.match(scenarioSentence("10"), /sekali dalam 10 tahun\. Peluang .* 65%\./);
});
