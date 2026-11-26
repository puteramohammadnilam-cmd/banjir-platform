// What is new on the site: a small "NEW" label on the parts added on NEWS_DATE, and a "What's new" note at the top of
// the Area overview with a way to each, until NEW_UNTIL (a Malaysian date). The note can be closed ("Got it"), which
// this browser remembers; the labels stay until NEW_UNTIL. To announce the next update, change the three constants and
// the news.* words.
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { malaysiaToday } from "./tide.js";

export const NEWS_DATE = "2026-11-26";
export const NEW_UNTIL = "2026-12-10";
const SEEN_KEY = `myflood-news-${NEWS_DATE}`;

/** Whether the latest news is still new on the date `now` (Malaysian time). */
export const isFresh = (now = new Date()) => malaysiaToday(now) <= NEW_UNTIL;

/** The "NEW" label for a part added in the latest news; null once it is no longer new. */
export const newBadge = (now = new Date()) => (isFresh(now) ? h("span", { class: "badge-new" }, t("news.badge")) : null);

function seen(storage) {
  try {
    return storage?.getItem(SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

/** The "What's new" note in `section`: a notice floating over the page's corner (so it moves nothing as it appears),
 *  shown while the news is fresh and until "Got it" in this browser. onShowOutlook and onOpenEngineer take the visitor
 *  to each new part; after "Got it", focus goes to `focusAfter`. */
export function createNews(section, { onShowOutlook, onOpenEngineer, focusAfter = null, storage = globalThis.localStorage, now = new Date() } = {}) {
  if (!section) return null;
  const close = () => {
    try {
      storage?.setItem(SEEN_KEY, "1");
    } catch { /* private mode: the note comes back next visit */ }
    section.hidden = true;
    focusAfter?.focus?.({ preventScroll: true });
  };
  section.hidden = !isFresh(now) || seen(storage);
  if (section.hidden) return { close };
  const item = (title, words, action, onClick) => h("li", {}, h("strong", {}, title), " ", words, " ",
    onClick && h("button", { type: "button", class: "btn btn-link", onclick: onClick }, action));
  section.replaceChildren(
    h("p", { class: "whats-new-title" }, newBadge(now), " ", t("news.title")),
    h("ul", { class: "whats-new-list" },
      item(t("news.outlookTitle"), t("news.outlook"), t("news.show"), onShowOutlook),
      item(t("news.engineerTitle"), t("news.engineer"), t("news.open"), onOpenEngineer)),
    h("button", { type: "button", class: "btn btn-small whats-new-close", onclick: close }, t("news.gotIt")));
  return { close };
}
