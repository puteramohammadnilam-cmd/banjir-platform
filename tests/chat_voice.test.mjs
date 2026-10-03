// Run from 11_Platform_Draft:  node --test tests/chat_voice.test.mjs
// Spoken questions in the chat (chat.js with voice.js, plan card G3), on the fake DOM with a stand-in recorder: press to
// record, press again to send; the words heard go in as the user's, the answer is read aloud in its language.
import assert from "node:assert/strict";
import { test } from "node:test";

import { VOICE_WORDS, createChat } from "../app/static/js/chat.js";
import { h } from "../app/static/js/dom.js";
import { installFakeDom } from "./fake_dom.mjs";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const AUDIO = "data:audio/wav;base64,UklGRg==";

function mount({ canRecord = true, record = null, reply = { question: "Kedai ni kena air tak?", language: "ms", answer: "Dalam model, 1.88 m." } } = {}) {
  installFakeDom();
  const asked = [];
  globalThis.fetch = async (path, init) => {
    asked.push([path, JSON.parse(init.body)]);
    const answer = reply instanceof Error ? { success: false, data: null, error: reply.message } : { success: true, data: reply, error: null };
    return { json: async () => answer };
  };
  const spoken = [];
  let stops = 0;
  let stopRecording = () => {};
  const voice = {
    canRecord: () => canRecord,
    startRecording: record ?? (async () => {
      let finish;
      const done = new Promise((resolve) => { finish = resolve; });
      stopRecording = () => finish(AUDIO);
      return { stop: () => stopRecording(), done };
    }),
    speak: (text, language) => spoken.push([text, language]),
    stopSpeaking: () => { stops += 1; },
  };
  const messages = h("ol");
  const input = h("input", {});
  const form = h("form", {}, input, h("button", { type: "submit" }, "Ask"));
  const page = h("section", {}, form);
  const chat = createChat({ messages, chips: h("div"), form, input, news: h("button"), getPlaceRef: () => "node-1", areaId: "home", areaName: "Home", voice });
  const mic = form.querySelectorAll("button").find((b) => b.getAttribute("class")?.includes("mic"));
  const said = () => messages.children.map((item) => [item.getAttribute("class"), item.textContent]);
  return { chat, mic, asked, spoken, said, page, form, stopped: () => stops };
}

test("there is no microphone button where the browser cannot record", () => {
  assert.equal(mount({ canRecord: false }).mic, undefined);
});

test("press to record, press again to send: the words heard and the answer join the conversation, read aloud", async () => {
  const { mic, asked, spoken, said, page } = mount();
  assert.equal(mic.textContent, VOICE_WORDS.speak);
  assert.match(page.textContent, /recording goes to Google Gemini/);
  mic.click();
  await settle();
  assert.equal(mic.getAttribute("aria-pressed"), "true");
  assert.equal(mic.textContent, VOICE_WORDS.stop);
  mic.click();
  await settle();
  await settle();
  assert.deepEqual(asked, [["/api/voice", { audio: AUDIO, place: "node-1", area_id: "home", history: [] }]]);
  assert.deepEqual(said().slice(-2), [["msg-user", "Kedai ni kena air tak?"], ["msg-model", `Dalam model, 1.88 m.${VOICE_WORDS.stopReading}`]]);
  assert.deepEqual(spoken, [["Dalam model, 1.88 m.", "ms"]]);
  assert.equal(mic.getAttribute("aria-pressed"), "false");
});

test("the spoken exchange is in the history of the next question", async () => {
  const { mic, asked } = mount();
  for (let i = 0; i < 2; i += 1) {
    mic.click();
    await settle();
    mic.click();
    await settle();
    await settle();
  }
  assert.deepEqual(asked[1][1].history, [{ role: "user", text: "Kedai ni kena air tak?" }, { role: "model", text: "Dalam model, 1.88 m." }]);
});

test("a blocked microphone, an unreadable recording and a server refusal each say so", async () => {
  const blocked = mount({ record: async () => { throw new Error("NotAllowedError"); } });
  blocked.mic.click();
  await settle();
  assert.deepEqual(blocked.said().at(-1), ["msg-error", VOICE_WORDS.blocked]);

  const broken = mount({ record: async () => ({ stop() {}, done: Promise.reject(new Error("decode")) }) });
  broken.mic.click();
  await settle();
  await settle();
  assert.deepEqual(broken.said().at(-1), ["msg-error", VOICE_WORDS.unreadable]);
  assert.deepEqual(broken.asked, []);

  const refused = mount({ reply: new Error("Sorry, I could not hear a question in that recording.") });
  refused.mic.click();
  await settle();
  refused.mic.click();
  await settle();
  await settle();
  assert.deepEqual(refused.said().at(-1), ["msg-error", "Sorry, I could not hear a question in that recording."]);
  assert.deepEqual(refused.spoken, []);
  assert.equal(refused.mic.disabled, false);
});

// ---------- review fixes ----------

test("the button keeps one name, and its state is in aria-pressed", async () => {
  const { mic } = mount();
  assert.equal(mic.getAttribute("aria-label"), VOICE_WORDS.label);
  mic.click();
  await settle();
  assert.equal(mic.getAttribute("aria-label"), VOICE_WORDS.label);
  assert.equal(mic.getAttribute("aria-pressed"), "true");
});

test("a second press while the microphone is being asked for starts nothing more", async () => {
  let starts = 0;
  let allow;
  const asked = new Promise((resolve) => { allow = resolve; });
  const { mic } = mount({ record: async () => { starts += 1; await asked; return { stop() {}, done: new Promise(() => {}) }; } });
  mic.click();
  mic.click();
  allow();
  await settle();
  assert.equal(starts, 1);
});

test("while a typed question is being answered, the microphone says to wait", async () => {
  const { mic, said, form } = mount();
  form.querySelector("button").disabled = true;
  mic.click();
  await settle();
  assert.deepEqual(said().at(-1), ["msg-error", VOICE_WORDS.wait]);
});

test("moving to another place stops reading the last answer aloud", () => {
  const { chat, stopped } = mount();
  chat.render({ id: "node-1", is_point: false });
  const before = stopped();
  chat.render({ id: "node-1", is_point: false });
  assert.equal(stopped(), before, "the same place: reading goes on");
  chat.render({ id: "node-2", is_point: false });
  assert.equal(stopped(), before + 1);
});
