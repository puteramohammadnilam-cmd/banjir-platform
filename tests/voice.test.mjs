// Run from 11_Platform_Draft:  node --test tests/voice.test.mjs
// The pure parts of voice questions (voice.js, plan card G3): the WAV the page sends, and which of the browser's voices
// reads an answer aloud.
import assert from "node:assert/strict";
import { mock, test } from "node:test";

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

import { primeSpeech, speak, startRecording, stopSpeaking } from "../app/static/js/voice.js";

function fakeSpeech(voicesLater) {
  const spoken = [];
  let voices = [];
  let listeners = [];
  globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  globalThis.speechSynthesis = {
    cancelled: 0,
    getVoices: () => voices,
    speak: (u) => spoken.push([u.text, u.lang]),
    cancel() { this.cancelled += 1; },
    addEventListener: (_type, fn) => { listeners.push(fn); },
    removeEventListener: (_type, fn) => { listeners = listeners.filter((other) => other !== fn); },
  };
  return { spoken, arrive: () => { voices = voicesLater; [...listeners].forEach((fn) => fn()); } };
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

// ---------- review batch 3 ----------

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test("Stop reading, or another answer, while the voices are still loading is not overridden when they arrive", async () => {
  const stopped = fakeSpeech([{ lang: "ms-MY", name: "Amira" }]);
  const first = speak("Jawapan satu.", "ms");
  stopSpeaking();
  stopped.arrive();
  await first;
  assert.deepEqual(stopped.spoken, [], "stopped before the voices came");

  const speech = fakeSpeech([{ lang: "ms-MY", name: "Amira" }]);
  const older = speak("Jawapan lama.", "ms");
  const newer = speak("Jawapan baru.", "ms");
  speech.arrive();
  await Promise.all([older, newer]);
  assert.deepEqual(speech.spoken, [["Jawapan baru.", "ms-MY"]], "only the latest is read");
});

test("priming speech speaks an empty utterance, stopping what was being read, and needs no voices", () => {
  const order = [];
  globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  globalThis.speechSynthesis = { cancel: () => order.push("cancel"), speak: (u) => order.push(`speak:${u.text}`) };
  primeSpeech();
  assert.deepEqual(order, ["cancel", "speak:"]);
  delete globalThis.speechSynthesis;
  primeSpeech();   // no speech in this browser: nothing happens
});

/** A recorder, a microphone stream and the audio decoding, as far as startRecording touches them. */
function fakeRecording() {
  const handlers = {};
  const trackHandlers = [];
  const log = { stopped: 0, trackStops: 0 };
  const recorder = {
    state: "inactive", mimeType: "audio/mp4",
    addEventListener: (type, fn) => { handlers[type] = fn; },
    start() { this.state = "recording"; },
    stop() { this.state = "inactive"; log.stopped += 1; handlers.stop?.(); },
  };
  globalThis.MediaRecorder = class { constructor() { return recorder; } };
  const stream = { getTracks: () => [{ stop: () => { log.trackStops += 1; }, addEventListener: (_type, fn) => trackHandlers.push(fn) }] };
  Object.defineProperty(globalThis, "navigator", { value: { mediaDevices: { getUserMedia: async () => stream } }, configurable: true });
  globalThis.AudioContext = class { decodeAudioData = async () => ({ duration: 0.001 }); close() {} };
  globalThis.OfflineAudioContext = class {
    destination = {};
    createBufferSource() { return { connect() {}, start() {} }; }
    startRendering = async () => ({ getChannelData: () => new Float32Array(16) });
  };
  return { recorder, log, endTrack: () => trackHandlers.forEach((fn) => fn()) };
}

test("a recorder that goes inactive with no stop event ends the recording at the 30 s timer, as an error", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const fake = fakeRecording();
    const { done } = await startRecording();
    fake.recorder.state = "inactive";   // iOS after a call or backgrounding: no "stop" event follows
    const outcome = done.then(() => "resolved", (error) => error.message);
    mock.timers.tick(30_000);
    assert.equal(await outcome, "The recording stopped.");
    assert.equal(fake.log.trackStops, 1, "the microphone is released");
  } finally {
    mock.timers.reset();
  }
});

test("the timer still stops a recorder that is recording, and its audio is sent", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const fake = fakeRecording();
    const { done } = await startRecording();
    mock.timers.tick(30_000);
    assert.equal(fake.log.stopped, 1);
    mock.timers.reset();
    assert.match(await done, /^data:audio\/wav;base64,/);
  } finally {
    mock.timers.reset();
  }
});

test("a microphone that is taken away mid-recording stops the recorder, and what was heard is kept", async () => {
  const fake = fakeRecording();
  const { done } = await startRecording();
  fake.endTrack();
  assert.equal(fake.log.stopped, 1);
  assert.match(await done, /^data:audio\/wav;base64,/);
  assert.equal(fake.log.trackStops, 1);
});

test("a microphone that ends after the recorder already went inactive rejects at once", async () => {
  const fake = fakeRecording();
  const { done } = await startRecording();
  fake.recorder.state = "inactive";
  fake.endTrack();
  await assert.rejects(done, /The recording stopped\./);
  assert.equal(fake.log.trackStops, 1);
  await settle();
});
