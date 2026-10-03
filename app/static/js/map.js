/* global L */
import { SCENARIOS, band, bandColor } from "./dom.js";

const INK = "#14262b";
const SIGNAL = "#c8402a";
const CELL_OPACITY = 0.28;   // the squares are background: the shop dots carry the depth
const START_ZOOM = 15;
const TILES ="https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; OpenStreetMap contributors · flood depth: JRC v2.1 (CC BY 4.0)';

// Leaflet treats string tooltips as HTML. Names come from a public map, so pass a text node.
const label = (text) => document.createTextNode(text);

export function createMap(element, town, premises, onSelect) {
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

  const markers = premises.map((p) => ({
    p,
    marker: L.circleMarker([p.lat, p.lon], { fillOpacity: 1 })
      .bindTooltip(label(p.name))
      .on("click", () => onSelect(p.id))
      .addTo(map),
  }));

  let shownRp = null;
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
      for (const { p, marker } of markers) {
        const selected = p.id === selectedId;
        marker.setStyle({ radius: selected ? 10 : 6, color: selected ? SIGNAL : INK, weight: selected ? 4 : 1.5, fillColor: bandColor(p.depth_m[rp]) });
        if (selected) marker.bringToFront();
      }
    },
  };
}
