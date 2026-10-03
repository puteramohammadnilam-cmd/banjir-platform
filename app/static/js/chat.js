import * as api from "./api.js";
import { h, icon } from "./dom.js";
import { areaOf } from "./point.js";
import * as realVoice from "./voice.js";

const SUGGESTIONS = Object.freeze([
  "Kedai ni kena air tak kalau banjir besar?",
  "Berapa anggaran rugi kedai ni kalau banjir?",
  "Which businesses stay dry in a 100 year flood?",
  "Hujan lebat tak hari ni?",
  "Is this shop still open?",
]);
// A point is a 90 m square of the model, not a shop: no "is it open" (it has no Google Maps listing), and the area
// question only inside a listed area, which is what the AI sums up. The lists are constants, so the same list twice
// means the chips need no rebuilding.
const POINT_SUGGESTIONS = Object.freeze([
  "Kawasan ni kena air tak kalau banjir besar?",
  "Berapa anggaran rugi kalau banjir kat sini?",
  "How deep would the water be here in a 100 year flood?",
  "Hujan lebat tak hari ni?",
]);
const POINT_AREA_SUGGESTIONS = Object.freeze([
  ...POINT_SUGGESTIONS.slice(0, 3), "Which businesses in this area stay dry in a 100 year flood?", ...POINT_SUGGESTIONS.slice(3),
]);
export const NEWS_NOTE = "Flood news is available for the listed areas.";
const POINT_PLACEHOLDER = "Tanya apa-apa pasal banjir di lokasi ini";   // the question box says "kedai" (shop) for a business
const MAX_TURN_CHARS = 2000;   // the server rejects longer history turns
const GREETING = "Hai. Pilih kedai di peta, then ask me anything about the flood model there. I answer in Bahasa Melayu or English.";

/** The chips for the selected place: a business's, or a point's. `page` is the page's own area and `areas` the listed
 *  ones, to tell whether a point lies in one. */
export function chipsFor(place, page, areas) {
  if (!place?.is_point) return SUGGESTIONS;
  return areaOf(place, page, areas) ? POINT_AREA_SUGGESTIONS : POINT_SUGGESTIONS;
}

/** The area whose flood news the place can ask for, as {areaId, name}: a business's is the page's own area. null for a
 *  point in none of the listed areas, which has no news. */
export function newsFor(place, page, areas) {
  const area = place?.is_point ? areaOf(place, page, areas) : page;
  return area ? { areaId: area.id, name: area.name } : null;
}

/** Google's search suggestions must be shown as given. They are HTML from the Gemini API, so this is the one
 *  place that uses innerHTML: inside a shadow root to keep their styles apart, and inline scripts or handlers
 *  in them cannot run under the page's script-src 'self'. */
function suggestions(html) {
  const box = h("div", { class: "search-suggestions" });
  const root = box.attachShadow({ mode: "open" });
  root.innerHTML = html;
  for (const link of root.querySelectorAll("a")) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  return box;
}

function sources(list, html) {
  return [
    list.length > 0 && h("ul", { class: "sources" }, list.map((item) =>
      h("li", {}, h("a", { href: item.uri, target: "_blank", rel: "noopener noreferrer" }, item.title)))),
    html && suggestions(html),
  ];
}

/** Adds a message to the conversation and keeps the newest in view. */
function addMessage(messages, kind, text) {
  const item = h("li", { class: `msg-${kind}` }, text);
  messages.append(item);
  messages.scrollTop = messages.scrollHeight;
  return item;
}

/** One exchange: the user's words, a wait note while `call` runs, then `show` for what came back or the error in
 *  plain words. The control (a button) is off meanwhile, so a second exchange cannot start. */
async function exchange({ add, control, userText, waitText, call, show }) {
  add("user", userText);
  const waiting = add("wait", waitText);
  control.disabled = true;
  try {
    const result = await call();
    waiting.remove();
    show(result);
  } catch (error) {
    waiting.remove();
    add("error", error.message);
  } finally {
    control.disabled = false;
  }
}

const newsLabel = ({ name }) => `Latest flood news for ${name}`;

/** Shows the news button for an area {areaId, name}, or a note in its place when there is none. Returns the function to
 *  call with the area, or null. The note is made the first time it is needed, so a page that never shows it is as it was. */
function newsBlock(news) {
  let note = null;
  return (target) => {
    if (!target && !note) {
      note = h("p", { class: "muted small" }, NEWS_NOTE);
      news.after(note);
    }
    news.hidden = target === null;
    if (note) note.hidden = target !== null;
    if (target) news.replaceChildren(icon("search"), newsLabel(target));
  };
}

const showChips = (box, list, onPick) =>
  box.replaceChildren(...list.map((text) => h("button", { type: "button", class: "chip", onclick: () => onPick(text) }, text)));

/** Puts the flood news answer in the conversation, with its sources and Google's search suggestions. */
const newsAnswer = (add, messages) => (result) => {
  const item = add("model", result.answer);
  item.append(...sources(result.sources, result.search_html).filter(Boolean));
  messages.scrollTop = messages.scrollHeight;
};

/** Send the typed question on submit. What was typed stays while an answer is pending. */
function wireQuestionForm({ form, input, button, send }) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (button.disabled) return;
    const question = input.value;
    input.value = "";
    send(question);
  });
}

export const VOICE_WORDS = Object.freeze({
  speak: "Speak", stop: "Stop", label: "Record a question", listening: "Listening to your question…",
  wait: "Please wait for the answer, then ask again.", stopReading: "Stop reading",
  blocked: "The microphone is blocked or not there. Type your question instead.",
  unreadable: "That recording could not be read. Please try again.",
  note: "Speak: your recording goes to Google Gemini to write down the question, and is not saved by this tool.",
});

/** The microphone button: press to record, press again (or wait 30 s) to send. record() starts a recording
 *  ({stop, done}, voice.js startRecording); send(audio) asks the question; isBusy() says a typed question is still
 *  being answered. Its name stays "Record a question"; whether it is recording is in aria-pressed. */
function voiceButton({ record, send, add, isBusy }) {
  let recording = null;
  let isStarting = false;   // the browser may be asking for the microphone: a second press must not start another
  const mic = h("button", { type: "button", class: "btn btn-secondary mic", "aria-pressed": "false", "aria-label": VOICE_WORDS.label });
  const show = (isOn) => {
    mic.setAttribute("aria-pressed", String(isOn));
    mic.replaceChildren(icon("mic"), isOn ? VOICE_WORDS.stop : VOICE_WORDS.speak);
  };
  show(false);
  mic.addEventListener("click", async () => {
    if (recording) return recording.stop();
    if (mic.disabled || isStarting) return undefined;
    if (isBusy()) return add("error", VOICE_WORDS.wait);
    isStarting = true;
    try {
      recording = await record();
    } catch {
      return add("error", VOICE_WORDS.blocked);
    } finally {
      isStarting = false;
    }
    show(true);
    const audio = await recording.done.catch(() => null);
    recording = null;
    show(false);
    return audio ? send(audio) : add("error", VOICE_WORDS.unreadable);
  });
  return mic;
}

/** getPlaceRef gives the selected place's id (a business or a point) when a question is sent. areaId and areaName are
 *  the area the page shows (its id and short name from config, which change only with a new page); areas are the listed
 *  areas, to tell which one a point lies in. render(place) is called as the selection changes and shows the chips, the
 *  question box's words and the flood news that fit it: until then, and for a business, the chat is the business chat. */
export function createChat({ messages, chips, form, input, news, getPlaceRef, areaId, areaName, areas = [], voice = realVoice }) {
  let history = [];
  const button = form.querySelector("button");
  const page = { id: areaId, name: areaName };
  const showNews = newsBlock(news);
  const businessPlaceholder = input.placeholder;   // as index.html has it
  let shown = { chips: SUGGESTIONS, news: newsFor(null, page, areas) };
  let shownPlaceId;   // what the chips and the news button are built for
  const add = (kind, text) => addMessage(messages, kind, text);

  async function send(question) {
    if (button.disabled || !question.trim()) return;
    await exchange({
      add, control: button, userText: question, waitText: "Checking the flood data…",
      call: () => api.ask({ question, place: getPlaceRef(), area_id: areaId, history }),
      show: ({ answer }) => {
        remember(question, answer);
        add("model", answer);
      },
    });
  }

  const remember = (question, answer) => {
    history = [...history, { role: "user", text: question }, { role: "model", text: answer.slice(0, MAX_TURN_CHARS) }].slice(-10);
  };

  /** A spoken question: the words heard go in the conversation as the user's, then the answer, read aloud. */
  async function sendVoice(audio) {
    if (button.disabled) return;
    const waiting = add("wait", VOICE_WORDS.listening);
    button.disabled = true;
    mic.disabled = true;
    try {
      const { question, language, answer } = await api.askVoice({ audio, place: getPlaceRef(), area_id: areaId, history });
      waiting.remove();
      add("user", question);
      add("model", answer).append(h("button", { type: "button", class: "btn btn-secondary stop-reading", onclick: voice.stopSpeaking }, VOICE_WORDS.stopReading));
      remember(question, answer);
      voice.speak(answer, language);
    } catch (error) {
      waiting.remove();
      add("error", error.message);
    } finally {
      button.disabled = false;
      mic.disabled = false;
    }
  }
  const mic = voice.canRecord() ? voiceButton({ record: voice.startRecording, send: sendVoice, add, isBusy: () => button.disabled }) : null;
  if (mic) form.after(h("p", { class: "fineprint voice-note" }, VOICE_WORDS.note));
  if (mic) form.append(mic);

  async function sendNews() {
    const target = shown.news;
    if (news.disabled || !target) return;
    await exchange({
      add, control: news, userText: newsLabel(target), waitText: "Searching with Google…",
      call: () => api.getNews({ area_id: target.areaId }),
      show: newsAnswer(add, messages),
    });
  }

  showNews(shown.news);
  showChips(chips, shown.chips, send);
  news.addEventListener("click", sendNews);
  wireQuestionForm({ form, input, button, send });
  add("model", GREETING);
  return {
    render(place) {
      if (place?.id !== shownPlaceId) voice.stopSpeaking?.();   // an answer about another place is not read on
      shownPlaceId = place?.id;
      input.placeholder = place?.is_point ? POINT_PLACEHOLDER : businessPlaceholder;
      const next = { chips: chipsFor(place, page, areas), news: newsFor(place, page, areas) };
      if (next.chips !== shown.chips) showChips(chips, next.chips, send);
      if (next.news?.areaId !== shown.news?.areaId) showNews(next.news);
      shown = next;
    },
  };
}
