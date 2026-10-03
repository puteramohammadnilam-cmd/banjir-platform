/* global L */
import { SCENARIOS, SCENARIO_LABEL, band, bandColor, depthText, depthWords, h } from "./dom.js";

const INK = "#0d1b2a";
const SELECTED = "#b94a1b";   // --accent in tokens.css
const CELL_OPACITY = 0.28;   // the squares are background: the shop dots carry the depth
const START_ZOOM = 15;
const FOCUS_ZOOM = 17;
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; OpenStreetMap contributors · flood depth: JRC v2.1 (CC BY 4.0)';

// Leaflet treats string tooltips as HTML. Names come from a public map, so pass a text node.
const label = (text) => document.createTextNode(text);

export function createMap(element, town, premises, { onSelect, onOpen }) {
  const [west, south, east, north] = town.view;
  const map = L.map(element, { scrollWheelZoom: false, maxBounds: [[south - 0.02, west - 0.02], [north + 0.02, east + 0.02]], minZoom: 14 });
  map.setView([(south + north) / 2, (west + east) / 2], START_ZOOM);
  L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);

  const size = town.cell_deg;
  const cells = town.cells.map(([cellSouth, cellWest, ...depths]) => ({
    depths,
    layer: L.rectangle([[cellSouth, cellWest], [cellSouth + size, cellWest + size]], { stroke: false, interactive: false }).addTo(map),
  }));

  for (const shelter of town.shelters) {
    L.marker([shelter.lat, shelter.lon], { icon: L.divIcon({ className: "shelter-pin", iconSize: [16, 14] }), keyboard: false })
      .bindTooltip(label(shelter.name), { permanent: true, direction: "right", className: "shelter-label", offset: [8, 0] })
      .addTo(map);
  }

  let shownRp = null;
  const popup = (p) => {
    const depth = p.depth_m[shownRp];
    return h("div", {},
      h("p", { class: "pop-name" }, p.name),
      h("p", { class: "pop-depth" }, band(depth) ? h("strong", {}, `${depthText(depth)}, ${depthWords(depth)}`) : "No water in the model",
        ` in a flood expected ${SCENARIO_LABEL[shownRp]}`),
      h("button", { type: "button", class: "btn btn-primary", onclick: () => { map.closePopup(); onOpen(p.id); } }, "Open details"));
  };
  const markers = new Map(premises.map((p) => [p.id, {
    p,
    marker: L.circleMarker([p.lat, p.lon], { fillOpacity: 1 })
      .bindTooltip(label(p.name))
      .bindPopup(() => popup(p))
      .on("click", () => onSelect(p.id))
      .addTo(map),
  }]));

  return {
    /** Colour the squares and the shop dots for one flood size, and ring the selected shop. */
    show(rp, selectedId) {
      if (rp !== shownRp) {
        const index = SCENARIOS.indexOf(rp);
        for (const { depths, layer } of cells) {
          layer.setStyle({ fillColor: bandColor(depths[index]), fillOpacity: band(depths[index]) ? CELL_OPACITY : 0 });
        }
        shownRp = rp;
      }
      for (const { p, marker } of markers.values()) {
        const selected = p.id === selectedId;
        marker.setStyle({ radius: selected ? 10 : 6, color: selected ? SELECTED : INK, weight: selected ? 4 : 1.5, fillColor: bandColor(p.depth_m[rp]) });
        if (selected) marker.bringToFront();
      }
    },
    /** Leaflet measures its box once; call this after the map's tab becomes visible. */
    refresh() {
      map.invalidateSize();
    },
    focus(id) {
      const entry = markers.get(id);
      if (!entry) return;
      map.setView(entry.marker.getLatLng(), FOCUS_ZOOM);
      entry.marker.openPopup();
    },
  };
}
