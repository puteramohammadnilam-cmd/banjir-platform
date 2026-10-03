import * as api from "./api.js";
import { h } from "./dom.js";

const SUGGESTIONS = [
  "Kedai ni kena air tak kalau banjir besar?",
  "Berapa anggaran rugi kedai ni kalau banjir?",
  "Which businesses stay dry in a 100 year flood?",
  "Hujan lebat tak hari ni?",
  "Is this shop still open?",
];
const MAX_TURN_CHARS = 2000;   // the server rejects longer history turns
const GREETING = "Hai. Pilih kedai di peta, then ask me anything about the flood model there. I answer in Bahasa Melayu or English.";

export function createChat({ messages, chips, form, input, news, getSelectedId }) {
  let history = [];
  const button = form.querySelector("button");

  function add(kind, text) {
    const item = h("li", { class: `msg-${kind}` }, text);
    messages.append(item);
    messages.scrollTop = messages.scrollHeight;
    return item;
  }

  async function send(question) {
    if (button.disabled || !question.trim()) return;
    add("user", question);
    const waiting = add("wait", "Checking the flood data…");
    button.disabled = true;
    try {
      const { answer } = await api.ask({ question, business_id: getSelectedId(), history });
      history = [...history, { role: "user", text: question }, { role: "model", text: answer.slice(0, MAX_TURN_CHARS) }].slice(-10);
      waiting.remove();
      add("model", answer);
    } catch (error) {
      waiting.remove();
      add("error", error.message);
    } finally {
      button.disabled = false;
    }
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

  async function sendNews() {
    if (news.disabled) return;
    add("user", "Latest flood news for Taman Sri Muda");
    const waiting = add("wait", "Searching with Google…");
    news.disabled = true;
    try {
      const result = await api.getNews({});
      waiting.remove();
      const item = add("model", result.answer);
      item.append(...sources(result.sources, result.search_html).filter(Boolean));
      messages.scrollTop = messages.scrollHeight;
    } catch (error) {
      waiting.remove();
      add("error", error.message);
    } finally {
      news.disabled = false;
    }
  }

  news.addEventListener("click", sendNews);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (button.disabled) return;   // keep what was typed while an answer is pending
    const question = input.value;
    input.value = "";
    send(question);
  });
  chips.replaceChildren(...SUGGESTIONS.map((text) => h("button", { type: "button", class: "chip", onclick: () => send(text) }, text)));
  add("model", GREETING);
}
