import * as api from "./api.js";
import { h, icon } from "./dom.js";
import { lang, t } from "./i18n.js";
import { areaOf } from "./point.js";
import * as realVoice from "./voice.js";

// The chips, by kind of place. A point is a 90 m square of the model, not a shop: no "is it open" (it has no Google
// Maps listing), and the area question only inside a listed area, which is what the AI sums up. Each list is made once
// per language and frozen, so the same list twice means the chips need no rebuilding.
const CHIP_KEYS = Object.freeze({
  business: ["ask.chipShopWater", "ask.chipShopLoss", "ask.chipAreaDry", "ask.chipRain", "ask.chipOpen"],
  point: ["ask.chipPointWater", "ask.chipPointLoss", "ask.chipPointDepth", "ask.chipRain"],
  pointArea: ["ask.chipPointWater", "ask.chipPointLoss", "ask.chipPointDepth", "ask.chipPointAreaDry", "ask.chipRain"],
  area: ["ask.chipAreaDry", "ask.chipRain"],   // nothing picked yet: only what the area as a whole can answer
});
const NEEDS_MAPS = new Set(["ask.chipRain", "ask.chipOpen"]);   // Google Weather and the Maps listing share the Maps key
const chipSets = new Map();   // "language|maps" -> {business, point, pointArea, area}

function chipsIn(language, hasMaps) {
  const id = `${language}|${hasMaps}`;
  if (!chipSets.has(id)) {
    const usable = (key) => hasMaps || !NEEDS_MAPS.has(key);
    chipSets.set(id, Object.fromEntries(Object.entries(CHIP_KEYS).map(([kind, keys]) => [kind, Object.freeze(keys.filter(usable).map((key) => t(key)))])));
  }
  return chipSets.get(id);
}
export const NEWS_NOTE = t("ask.newsNote");
const MAX_TURN_CHARS = 2000;   // the server rejects longer history turns

/** The chips for the selected place: a business's, or a point's. `page` is the page's own area and `areas` the listed
 *  ones, to tell whether a point lies in one. Without the Maps key, the rain and "still open" questions are left out. */
export function chipsFor(place, page, areas, hasMaps = true) {
  const chips = chipsIn(lang, hasMaps);
  if (!place) return chips.area;
  if (!place.is_point) return chips.business;
  return areaOf(place, page, areas) ? chips.pointArea : chips.point;
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

/** Puts focus back on a control that was switched off and on, when switching it off dropped focus to the page. */
function restoreFocus(control) {
  const active = document.activeElement;
  if (active === control || active === document.body) control.focus();
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
    restoreFocus(control);
  }
}

const newsLabel = ({ name }) => t("ask.newsFor", { name });

/** The first message names what the questions are about: the shop, the point, or the area when nothing is picked. */
const greetingFor = (place, areaName) => (!place ? t("ask.greetingArea", { area: areaName })
  : place.is_point ? t("ask.greetingPoint") : t("ask.greetingShop", { name: place.name }));

/** With no AI key every control would only answer with an error, so they are all switched off. */
function switchOff(controls) {
  for (const control of controls) control.disabled = true;
}

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

const showChips = (box, list, onPick, isOff = false) =>
  box.replaceChildren(...list.map((text) => h("button", { type: "button", class: "chip", disabled: isOff, onclick: () => onPick(text) }, text)));

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
  speak: t("voice.speak"), stop: t("voice.stop"), listening: t("voice.listening"),
  wait: t("voice.wait"), stopReading: t("voice.stopReading"), blocked: t("voice.blocked"),
  unreadable: t("voice.unreadable"), note: t("voice.note"),
});

/** The microphone button: press to record, press again (or wait 30 s) to send. record() starts a recording
 *  ({stop, done}, voice.js startRecording); send(audio) asks the question; isBusy() says a typed question is still
 *  being answered. onRecording(isOn) is called when a recording starts or ends (or the microphone is being asked for), so
 *  the typed question can be switched off meanwhile. Its name is its visible words, Speak or Stop (WCAG 2.5.3);
 *  whether it is recording is also in aria-pressed. */
function voiceButton({ record, send, add, isBusy, onRecording, prime }) {
  let recording = null;
  let isStarting = false;   // the browser may be asking for the microphone: a second press must not start another
  const mic = h("button", { type: "button", class: "btn btn-secondary mic", "aria-pressed": "false" });
  const show = (isOn) => {
    mic.setAttribute("aria-pressed", String(isOn));
    mic.replaceChildren(icon("mic"), isOn ? VOICE_WORDS.stop : VOICE_WORDS.speak);
  };
  show(false);
  mic.addEventListener("click", async () => {
    if (recording) return recording.stop();
    if (mic.disabled || isStarting) return undefined;
    if (isBusy()) return add("error", VOICE_WORDS.wait);
    prime?.();   // inside the click, for iOS
    isStarting = true;
    onRecording(true);
    try {
      recording = await record();
    } catch {
      onRecording(false);
      return add("error", VOICE_WORDS.blocked);
    } finally {
      isStarting = false;
    }
    show(true);
    const audio = await recording.done.catch(() => null);
    recording = null;
    show(false);
    onRecording(false);
    return audio ? send(audio) : add("error", VOICE_WORDS.unreadable);
  });
  return mic;
}

/** getPlaceRef gives the selected place's id (a business or a point) when a question is sent. areaId and areaName are
 *  the area the page shows (its id and short name from config, which change only with a new page); sectionId the
 *  section of a city the page shows, sent with each question and with the page's own news (null: none); areas are the listed
 *  areas, to tell which one a point lies in. render(place) is called as the selection changes and shows the chips, the
 *  question box's words and the flood news that fit it: until then, and for a business, the chat is the business chat.
 *  isReady is false when the build has no Gemini key: every control is then off. hasMaps is false without the Maps key. */
export function createChat({ messages, chips, form, input, news, getPlaceRef, areaId, sectionId = null, areaName, areas = [], voice = realVoice, isReady = true, hasMaps = true }) {
  let history = [];
  const scope = sectionId ? { area_id: areaId, section_id: sectionId } : { area_id: areaId };
  const button = form.querySelector("button");
  const page = { id: areaId, name: areaName };
  const showNews = newsBlock(news);
  let shown = { chips: chipsFor(null, page, areas, hasMaps), news: newsFor(null, page, areas) };
  let shownPlaceId;   // what the chips and the news button are built for
  const add = (kind, text) => addMessage(messages, kind, text);

  async function send(question) {
    if (button.disabled || !question.trim()) return;
    await exchange({
      add, control: button, userText: question, waitText: t("ask.checking"),
      call: () => api.ask({ question, place: getPlaceRef(), ...scope, history }),
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
      const { question, language, answer } = await api.askVoice({ audio, place: getPlaceRef(), ...scope, history });
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
      restoreFocus(mic);
    }
  }
  // While recording, the typed question is off: a question sent then would leave the Ask button busy when the recording
  // ends, and the recording would be dropped.
  const onRecording = (isOn) => {
    button.disabled = isOn;
    input.disabled = isOn;
  };
  const mic = isReady && voice.canRecord() ? voiceButton({ record: voice.startRecording, send: sendVoice, add, isBusy: () => button.disabled, onRecording, prime: voice.primeSpeech }) : null;
  if (mic) form.after(h("p", { class: "fineprint voice-note" }, VOICE_WORDS.note));
  if (mic) form.append(mic);

  async function sendNews() {
    const target = shown.news;
    if (news.disabled || !target) return;
    await exchange({
      add, control: news, userText: newsLabel(target), waitText: t("ask.searching"),
      call: () => api.getNews(target.areaId === areaId ? scope : { area_id: target.areaId }),
      show: newsAnswer(add, messages),
    });
  }

  showNews(shown.news);
  showChips(chips, shown.chips, send, !isReady);
  news.addEventListener("click", sendNews);
  wireQuestionForm({ form, input, button, send });
  input.placeholder = t("ask.placeholderShop");
  const greeting = isReady ? add("model", greetingFor(null, areaName)) : null;   // the AI-off notice says it all
  if (!isReady) switchOff([input, button, news]);
  return {
    render(place) {
      if (place?.id !== shownPlaceId) voice.stopSpeaking?.();   // an answer about another place is not read on
      shownPlaceId = place?.id;
      input.placeholder = t(!place ? "ask.placeholderArea" : place.is_point ? "ask.placeholderPoint" : "ask.placeholderShop");
      if (greeting) greeting.textContent = greetingFor(place, areaName);
      const next = { chips: chipsFor(place, page, areas, hasMaps), news: newsFor(place, page, areas) };
      if (next.chips !== shown.chips) showChips(chips, next.chips, send, !isReady);
      if (next.news?.areaId !== shown.news?.areaId) showNews(next.news);
      shown = next;
    },
  };
}
