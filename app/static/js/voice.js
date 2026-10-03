// Voice questions in Ask AI (plan card G3). The browser records with its own recorder, whatever format that gives, then
// decodes it and sends 16 kHz mono WAV, a format Gemini takes from every browser. Answers to spoken questions are read
// aloud by the browser's own voice for the answer's language, when it has one.
export const SAMPLE_RATE = 16_000;
export const MAX_SECONDS = 30;   // 44 + 30 x 16,000 x 2 bytes, under the server's 1 MB (main.MAX_AUDIO_BYTES)
const VOICE_LANGS = { ms: ["ms", "id"], mixed: ["ms", "id"], en: ["en"] };   // Indonesian reads Malay well enough

/** 16-bit PCM WAV, mono, for samples from -1 to 1 (louder ones are clipped). */
export function encodeWav(samples, sampleRate) {
  const bytes = new Uint8Array(44 + samples.length * 2);
  const view = new DataView(bytes.buffer);
  const ascii = (at, text) => [...text].forEach((ch, i) => view.setUint8(at + i, ch.charCodeAt(0)));
  ascii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, "WAVEfmt ");
  view.setUint32(16, 16, true);              // the size of the format chunk
  view.setUint16(20, 1, true);               // PCM
  view.setUint16(22, 1, true);               // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);  // bytes a second
  view.setUint16(32, 2, true);               // bytes a sample
  view.setUint16(34, 16, true);              // bits a sample
  ascii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => view.setInt16(44 + i * 2, Math.max(-32768, Math.min(32767, Math.round(sample * 32768))), true));
  return bytes;
}

/** The WAV as a data: URL for the JSON body. */
export function wavDataUrl(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return `data:audio/wav;base64,${btoa(binary)}`;
}

/** The browser voice for an answer in `language` (as /api/voice names it), or null when it has none that fits. */
export function pickVoice(voices, language) {
  for (const prefix of VOICE_LANGS[language] ?? VOICE_LANGS.en) {
    const found = voices.find((voice) => voice.lang?.toLowerCase().replace("_", "-").split("-")[0] === prefix);
    if (found) return found;
  }
  return null;
}

/** Whether this browser can record a question. */
export const canRecord = () => Boolean(globalThis.navigator?.mediaDevices?.getUserMedia && globalThis.MediaRecorder);

/** A recorded Blob as 16 kHz mono samples: the browser decodes its own format, then resamples. */
async function toSamples(blob) {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * SAMPLE_RATE), SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    return (await offline.startRendering()).getChannelData(0);
  } finally {
    context.close();
  }
}

/** Records from a stream until stop(), MAX_SECONDS or a recorder error; the stream is closed in every case. */
function record(stream) {
  let recorder;
  try {
    recorder = new MediaRecorder(stream);
  } catch (error) {
    stream.getTracks().forEach((track) => track.stop());
    throw error;
  }
  const chunks = [];
  let timer = null;
  const done = new Promise((resolve, reject) => {
    const finish = () => {
      clearTimeout(timer);
      stream.getTracks().forEach((track) => track.stop());
    };
    recorder.addEventListener("dataavailable", (event) => chunks.push(event.data));
    recorder.addEventListener("error", () => { finish(); reject(new Error("The recorder failed.")); });
    recorder.addEventListener("stop", () => {
      finish();
      toSamples(new Blob(chunks, { type: recorder.mimeType }))
        .then((samples) => resolve(wavDataUrl(encodeWav(samples.subarray(0, MAX_SECONDS * SAMPLE_RATE), SAMPLE_RATE))), reject);
    });
  });
  try {
    recorder.start();
  } catch (error) {
    stream.getTracks().forEach((track) => track.stop());
    throw error;
  }
  timer = setTimeout(() => recorder.state === "recording" && recorder.stop(), MAX_SECONDS * 1000);
  return { stop: () => { if (recorder.state === "recording") recorder.stop(); }, done };
}

/** Starts recording. Gives back {stop(), done}: `done` resolves to the WAV data URL once stopped (by stop(), or after
 *  MAX_SECONDS), and rejects when the recording cannot be read. Rejects at once when the microphone is refused. */
export async function startRecording() {
  return record(await navigator.mediaDevices.getUserMedia({ audio: true }));
}

const VOICES_WAIT_MS = 1500;   // Chrome loads its voices after the first getVoices(); voiceschanged says when

/** The browser's voices, waiting a moment for them on the first call. */
function voicesOf(synth) {
  const now = synth.getVoices();
  if (now.length || !synth.addEventListener) return Promise.resolve(now);
  return new Promise((resolve) => {
    const done = () => {
      synth.removeEventListener("voiceschanged", done);
      clearTimeout(timer);
      resolve(synth.getVoices());
    };
    const timer = setTimeout(done, VOICES_WAIT_MS);
    synth.addEventListener("voiceschanged", done);
  });
}

/** Reads an answer aloud in its language, stopping anything still being read. Nothing happens without a fitting voice. */
export async function speak(text, language) {
  const synth = globalThis.speechSynthesis;
  if (!synth) return;
  synth.cancel();
  const voice = pickVoice(await voicesOf(synth), language);
  if (!voice) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  synth.speak(utterance);
}

/** Stops reading aloud. */
export const stopSpeaking = () => globalThis.speechSynthesis?.cancel();
