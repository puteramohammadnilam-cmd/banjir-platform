/* global L */
// Engineer mode's drawing on the main page's Leaflet map (engineer.js draws through it, NO_DRAWER there says how): the
// rain pools and a tool's picture as image overlays, the clicked points joined by a line, and the map's clicks while a
// tool is on. toolClaim tells the rest of the map (its shop dots, the city's sections) to leave those clicks alone.
import { toolClaim } from "./map.js";

const MARK = "#f59e0b";
const corners = (b) => [[b[1], b[0]], [b[3], b[2]]];   // [west, south, east, north] as Leaflet's two corners

/** The drawer for `mapApi`, the overview map (map.js); it starts drawing once that map is up. */
export function leafletDrawer(mapApi) {
  let leaflet = null;
  let isAiming = () => false;   // while the pin is being placed (pin.js), the map's clicks are the pin's
  let onClick = null;
  const shown = {};
  mapApi?.addOverlay?.(({ map, isAiming: aiming }) => {
    leaflet = map;
    isAiming = aiming ?? isAiming;
    map.on("click", (event) => onClick?.(event));
  });
  const drop = (key) => {
    shown[key]?.remove();
    shown[key] = null;
  };
  return {
    drop,
    isAiming: () => isAiming(),
    picture(key, url, bounds, opacity) {
      drop(key);
      if (leaflet && globalThis.L) shown[key] = L.imageOverlay(url, corners(bounds), { opacity, interactive: false }).addTo(leaflet);
    },
    marks(points) {
      drop("marks");
      if (!leaflet || !globalThis.L || !points.length) return;
      const latlngs = points.map((p) => [p.lat, p.lng]);
      shown.marks = L.layerGroup([L.polyline(latlngs, { color: MARK, weight: 3 }),
        ...latlngs.map((ll) => L.circleMarker(ll, { radius: 4, color: MARK }))]).addTo(leaflet);
    },
    setTool(isOn, handler) {
      toolClaim.active = isOn;
      toolClaim.onClick = handler;
      onClick = handler;
      leaflet?.getContainer().classList.toggle("eng-tool-on", isOn);
    },
  };
}
