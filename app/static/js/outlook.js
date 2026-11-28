// "Next 5 days" on the Area overview (GET /api/outlook, app/outlook.py): for each day, the rain Google Weather expects,
// MetMalaysia's own forecast words, a MetMalaysia warning when one covers the area, and big-tide days, with a level
// from fixed rules set on past floods. The page asks for it only when the card scrolls into view (main.js), so a
// visit that never reaches it costs no Google call. It is not a flood warning, and the card says so.
import { h } from "./dom.js";
import { dateLocale, lang, t } from "./i18n.js";
import { newBadge } from "./news.js";
import { malaysiaToday } from "./tide.js";

const MET_PAGE = "https://www.met.gov.my/";
const LEVELS = ["high", "watch", "low"];
// MetMalaysia gives its words in Malay only: the English for its fixed list (developer.data.gov.my, 26 Nov 2026).
// A phrase not listed is shown as MetMalaysia wrote it.
const MET_WORDS = {
  "tiada hujan": "No rain", hujan: "Rain", "hujan di beberapa tempat": "Rain in places",
  "hujan di satu dua tempat": "Rain in one or two places", "ribut petir": "Thunderstorms",
  "ribut petir di beberapa tempat": "Thunderstorms in places", "ribut petir di satu dua tempat": "Thunderstorms in one or two places",
  berjerebu: "Hazy",
};
const MET_WHERE = { "di kawasan pantai": "along the coast", "di kawasan pedalaman": "inland" };
const MET_WHEN = {
  pagi: "morning", petang: "afternoon", malam: "night", "sepanjang hari": "all day", "pagi dan petang": "morning and afternoon",
  "pagi dan malam": "morning and night", "petang dan malam": "afternoon and night",
};

/** MetMalaysia's words for a day in the page's language: "Thunderstorms, afternoon and night". */
export function metWords(met, language = lang) {
  if (!met?.text) return "";
  if (language === "ms") return met.when ? `${met.text}, ${met.when.toLowerCase()}` : met.text;
  const text = met.text.toLowerCase();
  const where = Object.keys(MET_WHERE).find((tail) => text.endsWith(` ${tail}`));
  const base = where ? text.slice(0, -(where.length + 1)) : text;
  const words = MET_WORDS[base] ? `${MET_WORDS[base]}${where ? ` ${MET_WHERE[where]}` : ""}` : met.text;
  const when = met.when && (MET_WHEN[met.when.toLowerCase()] ?? met.when);
  return when ? `${words}, ${when}` : words;
}

/** "Today", "Tomorrow" or "Sat 28 Nov", for a Malaysian date. */
export function dayName(iso, now = new Date()) {
  const today = malaysiaToday(now);
  const tomorrow = malaysiaToday(new Date(now.getTime() + 86_400_000));
  if (iso === today) return t("outlook.today");
  if (iso === tomorrow) return t("outlook.tomorrow");
  return new Date(`${iso}T12:00:00+08:00`).toLocaleDateString(dateLocale(), { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kuala_Lumpur" });
}

/** The worst day: the highest level, the most rain among those; null when no day has a level. */
export function worstDay(days) {
  for (const level of LEVELS) {
    const found = days.filter((d) => d.level === level);
    if (found.length) return found.reduce((a, b) => ((b.rain_mm ?? -1) > (a.rain_mm ?? -1) ? b : a));
  }
  return null;
}

/** "1 in 6": how often a day this wet had a recorded flood, from the counts the server sends. */
const oneIn = (days, floods) => Math.max(1, Math.round(days / Math.max(1, floods)));

function headline(found, now) {
  const { thresholds: th } = found;
  if (!found.levels) {
    const wettest = found.days.reduce((a, b) => ((b.rain_mm ?? -1) > (a.rain_mm ?? -1) ? b : a), found.days[0]);
    if (!wettest || wettest.rain_mm == null) return null;
    return wettest.rain_mm < 1 ? t("outlook.headDry") : t("outlook.headRain", { day: dayName(wettest.date, now), mm: Math.round(wettest.rain_mm) });
  }
  const worst = worstDay(found.days);
  if (!worst) return null;
  const day = dayName(worst.date, now);
  const past = { place: th.set_from, since: th.since };
  if (worst.level === "low") return t("outlook.headLow", { watch: th.watch_mm });
  if (worst.level === "high" && !(worst.rain_mm >= th.high_mm)) return t("outlook.headWarned", { day });
  return worst.level === "high"
    ? t("outlook.headHigh", { day, mm: Math.round(worst.rain_mm), ...past, n: oneIn(th.high_days, th.high_floods) })
    : t("outlook.headWatch", { day, mm: Math.round(worst.rain_mm), ...past, n: oneIn(th.watch_days, th.watch_floods) });
}

const levelChip = (level) => h("span", { class: `outlook-level level-${level ?? "none"}` }, t(level ? `outlook.level.${level}` : "outlook.level.none"));

/** Google expects rain worth a level, while MetMalaysia says none: the card says they disagree rather than pick one. */
const disagree = (day) => (day.level === "watch" || day.level === "high") && /^tiada hujan/i.test(day.met?.text ?? "");

function dayRow(day, now, hasLevels) {
  const rain = day.rain_mm == null ? "–" : t("outlook.rain", { mm: Math.round(day.rain_mm), pct: day.chance_pct });
  const marks = [disagree(day) && t("outlook.disagree"), day.warned && t("outlook.warned"), day.big_tide && t("outlook.bigTide")].filter(Boolean);
  return h("li", { class: hasLevels ? "" : "no-level" }, [
    h("span", { class: "outlook-day" }, dayName(day.date, now)),
    hasLevels && levelChip(day.level),
    h("span", { class: "outlook-rain" }, rain),
    h("span", { class: "outlook-met muted small" }, [metWords(day.met), ...marks].filter(Boolean).join(" · ")),
  ]);
}

const untilText = (iso) => new Date(`${iso}+08:00`).toLocaleString(dateLocale(), { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kuala_Lumpur" });

function warningLine(w) {
  const title = (lang === "ms" ? w.title_ms : w.title_en) || w.title_en;
  return h("p", { class: "outlook-warning" }, t("outlook.warning", { title, until: untilText(w.valid_to) }));
}

const RAIN_NOTE = { capped: "outlook.capped", capped_day: "outlook.cappedDay", down: "outlook.down", off: "outlook.off" };
const TREND = { rising: "outlook.trend.rising", easing: "outlook.trend.easing" };   // steady says nothing

function body(found, now) {
  const head = headline(found, now);
  const th = found.thresholds;
  const notes = [RAIN_NOTE[found.rain], found.met === "down" && "outlook.metDown"].filter(Boolean);
  return [
    head && h("p", { class: "outlook-headline" }, [head, TREND[found.trend] ? ` ${t(TREND[found.trend])}` : ""]),
    ...found.warnings.map(warningLine),
    h("ul", { class: "outlook-days" }, found.days.map((d) => dayRow(d, now, found.levels))),
    ...notes.map((key) => h("p", { class: "muted small" }, t(key))),
    h("p", { class: "muted small" }, found.levels
      ? t("outlook.how", { watch: th.watch_mm, high: th.high_mm, place: th.set_from, since: th.since, caught: th.watch_floods, floods: th.floods })
      : t("outlook.noLevels", { place: th.set_from })),
    h("p", { class: "muted small" }, found.at ? t("outlook.sourcesAt", { place: found.at }) : t("outlook.sources")),
    found.arus && h("p", { class: "small" }, h("a", { href: found.arus, target: "_blank", rel: "noopener noreferrer" }, t("outlook.arus")),
      " ", h("span", { class: "fineprint" }, t("outlook.arusNote"))),
    h("p", { class: "fineprint" }, [t("outlook.notWarning"), " ",
      h("a", { href: MET_PAGE, target: "_blank", rel: "noopener noreferrer" }, t("outlook.metLink"))]),
  ].filter(Boolean);
}

/** Milliseconds until the next midnight in Malaysia (UTC+8, no summer time). */
const untilMidnight = (now) => 86_400_000 - ((now.getTime() + 8 * 3_600_000) % 86_400_000);

/** The card in `section`; set(state) draws it: {busy} "Checking…", {data} (the answer's `outlook`), {error}. It is
 *  shown from the start, so the page can tell when it scrolls into view. */
export function createOutlook(section, now = () => new Date()) {
  let shown;
  const heading = () => h("h2", { class: "small-heading", id: "outlook-heading" }, t("outlook.heading"), newBadge());
  section.replaceChildren(heading(), h("p", { class: "muted" }, t("outlook.checking")));   // until the first answer
  let timer = null;
  // A page left open past midnight: "Today" would be yesterday, so the card says to reload instead.
  const draw = (found) => {
    const at = now();
    clearTimeout(timer);
    if (found.days[0]?.date !== malaysiaToday(at)) return section.replaceChildren(heading(), h("p", { class: "muted" }, t("outlook.stale")));
    section.replaceChildren(heading(), ...body(found, at));
    timer = setTimeout(() => draw(found), untilMidnight(at) + 1000);
    timer.unref?.();   // Node (tests): a pending redraw must not keep the process alive
  };
  return {
    set(state) {
      if (state === shown) return;
      shown = state;
      if (state?.data) draw(state.data);
      else section.replaceChildren(heading(), h("p", { class: "muted" }, t(state?.error ? "outlook.failed" : "outlook.checking")));
    },
  };
}
