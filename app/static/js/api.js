async function call(path, payload) {
  const options = payload
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
    : undefined;
  let body;
  try {
    const response = await fetch(path, options);
    body = await response.json();
  } catch {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  if (!body.success) throw new Error(body.error || "Something went wrong.");
  return body.data;
}

export const getData = () => call("/api/data");
export const getStatus = () => call("/api/status");
export const ask = (payload) => call("/api/ask", payload);
export const sendPhoto = (payload) => call("/api/photo", payload);
export const getRain = () => call("/api/rain");
export const getPlace = (id) => call(`/api/place/${encodeURIComponent(id)}`);
export const getNews = (payload) => call("/api/news", payload);
export const estimate = (payload) => call("/api/estimate", payload);
