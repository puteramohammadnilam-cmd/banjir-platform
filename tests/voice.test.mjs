// Run from 11_Platform_Draft:  node --test tests/voice.test.mjs
// The pure parts of voice questions (voice.js, plan card G3): the WAV the page sends, and which of the browser's voices
// reads an answer aloud.
import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_SECONDS, SAMPLE_RATE, encodeWav, pickVoice, wavDataUrl } from "../app/static/js/voice.js";

const text = (bytes, from, to) => String.fromCharCode(...bytes.slice(from, to));

test("a recording becomes 16 kHz mono 16-bit WAV with a correct header", () => {
  const wav = encodeWav(new Float32Array([0, 1, -1, 0.5, 2, -2]), SAMPLE_RATE);
  const view = new DataView(wav.buffer);
  assert.equal(wav.length, 44 + 6 * 2);
  assert.equal(text(wav, 0, 4), "RIFF");
  assert.equal(view.getUint32(4, true), 36 + 12);
  assert.equal(text(wav, 8, 16), "WAVEfmt ");
  assert.equal(view.getUint16(20, true), 1);             // PCM
  assert.equal(view.getUint16(22, true), 1);             // mono
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint32(28, true), 32000);         // bytes a second
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(text(wav, 36, 40), "data");
  assert.equal(view.getUint32(40, true), 12);
  assert.deepEqual([0, 1, 2, 3, 4, 5].map((i) => view.getInt16(44 + i * 2, true)), [0, 32767, -32768, 16384, 32767, -32768]);
});

test("the longest recording fits the server's 1 MB limit", () => {
  assert.ok(44 + MAX_SECONDS * SAMPLE_RATE * 2 <= 1_000_000);
});

test("the data URL is WAV in base64", () => {
  const url = wavDataUrl(new Uint8Array([82, 73, 70, 70]));
  assert.equal(url, "data:audio/wav;base64,UklGRg==");
});

test("an answer in Bahasa Melayu is read by a Malay voice, else an Indonesian one, else none", () => {
  const voices = [{ lang: "en-US", name: "Samantha" }, { lang: "id-ID", name: "Damayanti" }, { lang: "ms-MY", name: "Amira" }];
  assert.equal(pickVoice(voices, "ms").name, "Amira");
  assert.equal(pickVoice(voices.slice(0, 2), "ms").name, "Damayanti");
  assert.equal(pickVoice(voices.slice(0, 1), "ms"), null);
  assert.equal(pickVoice(voices, "mixed").name, "Amira");
  assert.equal(pickVoice(voices, "en").name, "Samantha");
  assert.equal(pickVoice([{ lang: "en_GB", name: "Daniel" }], "en").name, "Daniel");
  assert.equal(pickVoice([], "en"), null);
});

// ---------- review fixes ----------

import { speak, stopSpeaking } from "../app/static/js/voice.js";

function fakeSpeech(voicesLater) {
  const spoken = [];
  let voices = [];
  const listeners = {};
  globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  globalThis.speechSynthesis = {
    cancelled: 0,
    getVoices: () => voices,
    speak: (u) => spoken.push([u.text, u.lang]),
    cancel() { this.cancelled += 1; },
    addEventListener: (type, fn) => { listeners[type] = fn; },
    removeEventListener: (type) => { delete listeners[type]; },
  };
  return { spoken, arrive: () => { voices = voicesLater; listeners.voiceschanged?.(); } };
}

test("the first answer waits for the browser's voices to load, then is read", async () => {
  const speech = fakeSpeech([{ lang: "ms-MY", name: "Amira" }]);
  const pending = speak("Dalam model, 1.88 m.", "ms");
  speech.arrive();
  await pending;
  assert.deepEqual(speech.spoken, [["Dalam model, 1.88 m.", "ms-MY"]]);
});

test("stopSpeaking stops what is being read", () => {
  fakeSpeech([]);
  stopSpeaking();
  assert.equal(globalThis.speechSynthesis.cancelled, 1);
});
