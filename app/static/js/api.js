import { t } from "./i18n.js";

/** A failure the page can show as it is: the server's own words (in English: the API does not translate them), or that
 *  the server could not be reached (in the page's language). */
export class ApiError extends Error {}

async function call(path, payload) {
  const options = payload
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
    : undefined;
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(t("api.unreachable"));
  }
  // a reply that is not this app's JSON (a proxy's error page, say) came from somewhere: the connection is fine
  const body = await response.json().catch(() => {
    throw new ApiError(t("api.badAnswer"));
  });
  if (!body.success) throw new ApiError(body.error || t("api.generic"));
  return body.data;
}

const area = (id) => encodeURIComponent(id);

export const getAreas = () => call("/api/areas");
export const getAreaData = (id) => call(`/api/areas/${area(id)}/data`);
/** The default area's data, in the same shape: asked for at once when a link names no area, beside getAreas. */
export const getDefaultData = () => call("/api/data");
export const getStatus = () => call("/api/status");
export const getCoverage = () => call("/api/coverage");
/** A point goes in the body of a POST, never in a URL, so it stays out of server and proxy logs. The answer carries the
 *  flood squares around the point too (`blocks` and `cells`): a block asked for by its address would put the area in the
 *  URL, and so in every log, which is why there is no call for one. */
export const checkPoint = (payload) => call("/api/point", payload);
export const ask = (payload) => call("/api/ask", payload);
/** A spoken question: a WAV data: URL in the body; the answer carries the words Gemini heard. */
export const askVoice = (payload) => call("/api/voice", payload);
export const sendPhoto = (payload) => call("/api/photo", payload);
export const sendStock = (payload) => call("/api/stock", payload);
export const writePlan = (payload) => call("/api/plan", payload);
export const getRain = (areaId) => call(`/api/rain?area=${area(areaId)}`);
export const getPlace = (id) => call(`/api/place/${encodeURIComponent(id)}`);
export const getNews = (payload) => call("/api/news", payload);
export const estimate = (payload) => call("/api/estimate", payload);
