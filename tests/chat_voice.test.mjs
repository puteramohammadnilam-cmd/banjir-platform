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

function mount({ canRecord = true, record = null, gate = null, reply = { question: "Kedai ni kena air tak?", language: "ms", answer: "Dalam model, 1.88 m.", sig: "s1" } } = {}) {
  installFakeDom();
  const asked = [];
  globalThis.fetch = async (path, init) => {
    asked.push([path, JSON.parse(init.body)]);
    await gate;
    const answer = reply instanceof Error ? { success: false, data: null, error: reply.message } : { success: true, data: reply, error: null };
    return { json: async () => answer };
  };
  const spoken = [];
  let primed = 0;
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
    primeSpeech: () => { primed += 1; },
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
  return { chat, mic, asked, spoken, said, page, form, input, ask: form.querySelector("button"), primed: () => primed, stopped: () => stops };
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

test("the spoken exchange is in the history of the next question, the answer with its signature", async () => {
  const { mic, asked } = mount();
  for (let i = 0; i < 2; i += 1) {
    mic.click();
    await settle();
    mic.click();
    await settle();
    await settle();
  }
  assert.deepEqual(asked[1][1].history, [{ role: "user", text: "Kedai ni kena air tak?" }, { role: "model", text: "Dalam model, 1.88 m.", sig: "s1" }]);
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

test("the button's name is its visible words (no aria-label to differ from them), and its state is in aria-pressed", async () => {
  const { mic } = mount();
  assert.equal(mic.getAttribute("aria-label"), null);
  assert.equal(VOICE_WORDS.label, undefined);
  mic.click();
  await settle();
  assert.equal(mic.getAttribute("aria-label"), null);
  assert.equal(mic.textContent, VOICE_WORDS.stop);
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

// ---------- review batch 3 ----------

test("while recording, the Ask button and the question box are off, so a typed question cannot eat the recording", async () => {
  const { mic, asked, said, form, input, ask } = mount();
  mic.click();
  await settle();
  assert.equal(ask.disabled, true);
  assert.equal(input.disabled, true);
  input.value = "typed meanwhile";
  form.dispatch("submit");
  await settle();
  assert.deepEqual(asked, [], "nothing is sent by the form while recording");
  mic.click();
  await settle();
  await settle();
  assert.equal(asked.length, 1);
  assert.equal(asked[0][0], "/api/voice", "the recording is sent, not lost");
  assert.equal(said().some(([kind]) => kind === "msg-error"), false);
  assert.equal(ask.disabled, false);
  assert.equal(input.disabled, false);
});

test("the Ask button and the box are on again when the microphone is refused or the recording is unreadable", async () => {
  const blocked = mount({ record: async () => { throw new Error("NotAllowedError"); } });
  blocked.mic.click();
  await settle();
  assert.equal(blocked.ask.disabled, false);
  assert.equal(blocked.input.disabled, false);

  const broken = mount({ record: async () => ({ stop() {}, done: Promise.reject(new Error("decode")) }) });
  broken.mic.click();
  await settle();
  await settle();
  assert.equal(broken.ask.disabled, false);
  assert.equal(broken.input.disabled, false);
});

test("starting a recording primes speech inside the click, once, and stopping does not", async () => {
  const { mic, primed } = mount();
  mic.click();
  assert.equal(primed(), 1, "before the microphone prompt is even answered");
  await settle();
  mic.click();
  await settle();
  await settle();
  assert.equal(primed(), 1);
});

test("the microphone button gets focus back after the spoken question was sent, if the page took it", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { mic } = mount({ gate });
  const body = {};
  globalThis.document.body = body;
  mic.focus = () => { globalThis.document.activeElement = mic; };
  mic.click();
  await settle();
  mic.click();
  await settle();
  assert.equal(mic.disabled, true);
  globalThis.document.activeElement = body;   // a disabled button loses focus to the page
  release();
  await settle();
  await settle();
  assert.equal(mic.disabled, false);
  assert.equal(globalThis.document.activeElement, mic);
});

test("focus is left alone where the user moved it meanwhile", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { mic } = mount({ gate });
  const elsewhere = h("a");
  globalThis.document.body = {};
  mic.focus = () => { globalThis.document.activeElement = mic; };
  mic.click();
  await settle();
  mic.click();
  await settle();
  globalThis.document.activeElement = elsewhere;
  release();
  await settle();
  await settle();
  assert.equal(globalThis.document.activeElement, elsewhere);
});
