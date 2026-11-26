// Engineer mode: a switch in the footer (or ?engineer=1), remembered in this browser, that opens a panel under the map
// with the "Rain pools" layer (where heavy rain collects, app/engineer.py) and tools on the app's own data: inspect a
// spot, a height profile, the basin draining through a spot, a bund or pond what-if, a grid of your own, and downloads.
// Nothing here calls Google. Off by default: it is for engineers and planners, not shop owners.
import * as api from "./api.js";
import { h, s } from "./dom.js";
import { lang, t } from "./i18n.js";
import { toolClaim } from "./map.js";
import { newBadge } from "./news.js";

const STORE = "myflood-engineer";
const TOOLS = ["off", "inspect", "profile", "basin", "bund", "pond"];
const CLASS_COLOURS = ["#a9b4ff", "#6c6ff0", "#3a2aa8"];
const CHANGE_M = 0.8;
const POOL_OPACITY = 0.8;
const CHART = { w: 640, h: 220, pad: 32 };

/** Whether engineer mode was asked for: ?engineer=1, or turned on before in this browser. */
export function isWanted(search = globalThis.location?.search ?? "", stored = globalThis.localStorage) {
  if (new URLSearchParams(search).get("engineer") === "1") return true;
  try {
    return stored?.getItem(STORE) === "1";
  } catch {
    return false;
  }
}

function remember(isOn) {
  try {
    globalThis.localStorage?.setItem(STORE, isOn ? "1" : "0");
  } catch { /* private mode: it is just not remembered */ }
}

const metres = (v) => (v == null ? t("eng.none") : t("eng.m", { m: Number(v).toFixed(2) }));
const triple = (values, keys) => keys.map((k) => (values?.[k] == null ? t("eng.none") : Number(values[k]).toFixed(2))).join(" / ");
const corners = (b) => [[b[1], b[0]], [b[3], b[2]]];

/** A small SVG chart of a profile: bare ground, standing water for the storm and the river model's 1 in 50 years water. */
export function profileChart(points, storm) {
  const ground = points.map((p) => p.ground_m);
  const pool = points.map((p, i) => (ground[i] != null && p.pool_m?.[storm] != null ? ground[i] + p.pool_m[storm] : null));
  const river = points.map((p, i) => (ground[i] != null && p.river_depth_m?.["50"] ? ground[i] + p.river_depth_m["50"] : null));
  const all = [...ground, ...pool, ...river].filter((v) => v != null);
  if (!all.length) return h("p", {}, t("eng.none"));
  const [lo, hi] = [Math.min(...all), Math.max(...all) + 0.5];
  const last = points.at(-1).d || 1;
  const x = (d) => CHART.pad + (d / last) * (CHART.w - 2 * CHART.pad);
  const y = (v) => CHART.h - CHART.pad - ((v - lo) / (hi - lo || 1)) * (CHART.h - 2 * CHART.pad);
  const path = (values) => values.map((v, i) => (v == null ? null : `${x(points[i].d).toFixed(1)},${y(v).toFixed(1)}`))
    .reduce((d, xy) => (xy ? `${d}${d.endsWith(" ") || !d ? "M" : "L"}${xy}` : `${d} `), "");
  return s("svg", { viewBox: `0 0 ${CHART.w} ${CHART.h}`, class: "eng-chart", role: "img", "aria-label": t("eng.profileKey", { mm: storm }) },
    s("path", { d: path(river), class: "eng-line river" }), s("path", { d: path(pool), class: "eng-line pool" }),
    s("path", { d: path(ground), class: "eng-line ground" }),
    s("text", { x: 4, y: 14, class: "eng-axis" }, `${hi.toFixed(1)} m`), s("text", { x: 4, y: CHART.h - 4, class: "eng-axis" }, `${lo.toFixed(1)} m`),
    s("text", { x: CHART.w - 4, y: CHART.h - 4, class: "eng-axis end" }, `${(last / 1000).toFixed(2)} km`));
}

function inspectView(found) {
  const row = (label, value) => [h("dt", {}, label), h("dd", {}, value)];
  return [h("h3", { class: "small-heading" }, t("eng.inspectTitle", { lat: found.lat, lon: found.lon })),
    h("dl", { class: "eng-values" },
      row(t("eng.river"), triple(found.river_depth_m, ["10", "20", "50"])),
      row(t("eng.pools"), triple(found.pool_m, ["40", "70", "100"])),
      row(t("eng.bare"), metres(found.bare_ground_m)),
      row(t("eng.surface"), metres(found.surface?.ground_m)),
      row(t("eng.aboveRiver"), metres(found.surface?.above_river_m)),
      row(t("eng.flash"), found.flash ? `${found.flash.score} (${found.flash.class})` : t("eng.none")))];
}

function compareView(found) {
  const rows = [["eng.wet", "wet_squares", (v) => String(v)], ["eng.deepest", "deepest_m", metres],
    ["eng.volume", "water_m3", (v) => t("eng.m3", { v: Number(v).toLocaleString() })]];
  return [h("h3", { class: "small-heading" }, t("eng.whatifTitle", { kind: t(`eng.kind.${found.kind}`), storm: found.storm_mm,
    squares: found.squares_changed, m: found.change_m })),
  h("table", { class: "eng-table" }, h("tr", {}, h("th", {}), h("th", {}, t("eng.before")), h("th", {}, t("eng.after"))),
    rows.map(([key, field, show]) => h("tr", {}, h("th", {}, t(key)), h("td", {}, show(found.before[field])), h("td", {}, show(found.after[field]))))),
  h("p", { class: "fineprint" }, t("eng.whatifKey"))];
}

function layerKey(layer) {
  const a = layer.assumptions;
  const c = layer.check;
  return [h("ul", { class: "eng-key" }, CLASS_COLOURS.map((colour, i) => h("li", {}, h("span", { class: "swatch", style: `background:${colour}` }), t(`eng.class${i + 1}`)))),
    h("p", { class: "fineprint" }, t("eng.layerNote", { drains: a.drains_mm, runoff: Math.round(a.runoff * 100), burn: a.burn_m })),
    c && h("p", { class: "fineprint" }, t("eng.check", { mm: c.storm_mm, auc: c.auc, low: c.baseline_low_ground_auc, pct: c.hotspot_percentile, lowPct: c.baseline_low_ground_hotspot_percentile })),
    h("p", { class: "fineprint" }, layer.credit)];
}

/** The switch and the panel. `mapApi` is the overview map (map.js); `area` the page's area with its `layers`. */
export function createEngineer({ section, button, mapApi, area, sectionId = null, wanted = isWanted() }) {
  if (!section || !button) return null;
  let leaflet = null;
  mapApi?.addOverlay?.(({ map }) => { leaflet = map; });
  const layer = area?.layers?.rain_pools ?? null;
  const st = { isOn: wanted, storm: layer?.storms?.includes(70) ? 70 : layer?.storms?.[0], isLayerOn: false, tool: "off", points: [] };
  const overlays = { pools: null, result: null, marks: null };
  const result = h("div", { class: "eng-result", "aria-live": "polite" });
  const say = (...nodes) => result.replaceChildren(...nodes.flat().filter(Boolean));
  const fail = (error) => say(h("p", { class: "alert alert-inline", role: "alert" }, t("eng.failed", { why: error.message })));
  const drop = (key) => { overlays[key]?.remove(); overlays[key] = null; };
  const picture = (key, url, bounds, opacity = POOL_OPACITY) => {
    drop(key);
    if (leaflet && globalThis.L) overlays[key] = globalThis.L.imageOverlay(url, corners(bounds), { opacity, interactive: false }).addTo(leaflet);
  };
  const showPools = () => (st.isOn && st.isLayerOn && layer ? picture("pools", layer.url.replace("{mm}", st.storm), layer.bounds) : drop("pools"));
  const markPoints = () => {
    drop("marks");
    if (!leaflet || !globalThis.L || !st.points.length) return;
    const latlngs = st.points.map((p) => [p.lat, p.lng]);
    overlays.marks = globalThis.L.layerGroup([globalThis.L.polyline(latlngs, { color: "#f59e0b", weight: 3 }),
      ...latlngs.map((ll) => globalThis.L.circleMarker(ll, { radius: 4, color: "#f59e0b" }))]).addTo(leaflet);
  };
  let latest = 0;   // a slower, older answer must not replace a newer one
  const run = async (work, show) => {
    const mine = ++latest;
    say(h("p", { class: "muted" }, t("eng.working")));
    try {
      const found = await work();
      if (mine === latest) say(show(found));
    } catch (error) {
      if (mine === latest) fail(error);
    }
  };
  const onClick = (event) => {
    if (!st.isOn || st.tool === "off") return;
    const at = event.latlng;
    if (st.tool === "inspect") return run(() => api.engInspect(area.id, at.lat, at.lng), inspectView);
    if (st.tool === "basin") {
      return run(() => api.engBasin(area.id, at.lat, at.lng), (found) => {
        picture("result", found.png, found.bounds, 0.6);
        return [h("h3", { class: "small-heading" }, t("eng.basinTitle", { km2: found.area_km2, squares: found.squares })),
          found.snapped_m > 0 && h("p", { class: "fineprint" }, t("eng.snapped", { m: found.snapped_m }))];
      });
    }
    st.points = st.tool === "profile" && st.points.length >= 2 ? [at] : [...st.points, at];
    markPoints();
    if (st.tool === "profile" && st.points.length === 2) {
      const [a, b] = st.points;
      run(() => api.engProfile(area.id, a, b), (found) => [h("h3", { class: "small-heading" }, t("eng.profileTitle", { km: (found.length_m / 1000).toFixed(2) })),
        profileChart(found.points, String(st.storm)), h("p", { class: "fineprint" }, t("eng.profileKey", { mm: st.storm }))]);
    }
  };
  const runWhatif = () => (st.points.length < 2 ? say(h("p", { class: "muted" }, t(`eng.hint.${st.tool}`))) : run(() => api.engWhatif({ area_id: area.id, storm_mm: st.storm, kind: st.tool, points: st.points.map((p) => [p.lat, p.lng]) }),
    (found) => {
      picture("result", found.png, found.bounds, 0.8);
      return compareView(found);
    }));
  const clear = () => {
    st.points = [];
    drop("marks");
    drop("result");
    say();
  };
  const onUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    run(async () => api.engUpload({ asc: await file.text(), storm_mm: st.storm }), (found) => [
      h("h3", { class: "small-heading" }, t("eng.uploadTitle", { rows: found.rows, cols: found.cols, cell: found.cell_m })),
      h("img", { src: found.png, alt: t("eng.layer"), class: "eng-upload-picture" }),
      compareView({ kind: "pond", storm_mm: found.storm_mm, squares_changed: 0, change_m: 0, before: found, after: found }).slice(1, 2)]);
  };
  const toolChoice = () => h("fieldset", { class: "metric-choice eng-tools" }, h("legend", {}, t("eng.tools")),
    TOOLS.map((tool) => h("label", {}, h("input", { type: "radio", name: "eng-tool", value: tool, checked: st.tool === tool,
      onchange: () => { st.tool = tool; clear(); draw(); } }), t(`eng.tool.${tool}`, { m: CHANGE_M }))));
  const stormChoice = () => h("label", { class: "eng-storm" }, t("eng.storm"), " ",
    h("select", { onchange: (e) => { st.storm = Number(e.target.value); drop("result"); say(); showPools(); draw(); } },
      (layer?.storms ?? [40, 70, 100]).map((mm) => h("option", { value: mm, selected: mm === st.storm }, t("eng.stormMm", { mm })))));
  const params = `area=${encodeURIComponent(area.id)}`;
  const draw = () => {
    toolClaim.active = st.isOn && st.tool !== "off";
    toolClaim.onClick = onClick;
    leaflet?.getContainer().classList.toggle("eng-tool-on", toolClaim.active);
    section.hidden = !st.isOn;
    button.setAttribute("aria-pressed", String(st.isOn));
    if (!st.isOn) return;
    section.replaceChildren(...[   // replaceChildren would show a false (the Run row for other tools) as text
      h("div", { class: "eng-head" }, h("h2", { id: "engineer-heading" }, t("eng.heading"), newBadge()),
        h("button", { type: "button", class: "btn btn-link", onclick: () => toggle(false) }, t("eng.close"))),
      h("p", { class: "muted" }, t("eng.lead")),
      layer ? h("div", { class: "eng-layer" },
        h("label", {}, h("input", { type: "checkbox", checked: st.isLayerOn, onchange: (e) => { st.isLayerOn = e.target.checked; showPools(); } }), " ", t("eng.layer"), newBadge()),
        stormChoice(), ...layerKey(layer)) : h("p", {}, t("eng.layerNone")),
      toolChoice(), h("p", { class: "muted small" }, t(`eng.hint.${st.tool}`)),
      (st.tool === "bund" || st.tool === "pond") && h("p", { class: "eng-actions" },
        h("button", { type: "button", class: "btn", onclick: runWhatif, disabled: !layer }, t("eng.run")), " ",
        h("button", { type: "button", class: "btn btn-link", onclick: clear }, t("eng.clear"))),
      result,
      h("h3", { class: "small-heading" }, t("eng.upload")), h("p", { class: "muted small" }, t("eng.uploadLead")),
      h("label", { class: "btn btn-link" }, t("eng.uploadFile"), h("input", { type: "file", accept: ".asc,text/plain", class: "visually-hidden", onchange: onUpload })),
      h("h3", { class: "small-heading" }, t("eng.exports")),
      h("ul", { class: "eng-downloads" },
        h("li", {}, h("a", { href: `/api/eng/export.csv?${params}${sectionId ? `&section=${encodeURIComponent(sectionId)}` : ""}`, download: "" }, t("eng.csv"))),
        layer && h("li", {}, h("a", { href: `/api/eng/rain-pools-${st.storm}.tif?${params}`, download: "" }, t("eng.tif", { mm: st.storm })))),
      h("p", { class: "fineprint" }, t("eng.licence")), h("p", { class: "fineprint" }, t("eng.noVelocity"))].filter(Boolean));
  };
  const toggle = (isOn) => {
    st.isOn = isOn;
    remember(isOn);
    if (!isOn) { clear(); st.isLayerOn = false; showPools(); }
    draw();
    if (isOn) section.scrollIntoView?.({ block: "nearest" });
  };
  button.addEventListener("click", () => toggle(!st.isOn));
  const badge = newBadge();
  if (badge && button.parentNode) button.after(badge);
  mapApi?.addOverlay?.(({ map }) => map.on("click", onClick));
  draw();
  return { toggle, state: st, lang };
}
