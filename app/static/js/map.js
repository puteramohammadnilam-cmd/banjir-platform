/* global L */
import { BAND_COLORS, SCENARIOS, band } from "./dom.js";

const INK = "#14262b";
const PAPER = "#fbf8f1";
const SIGNAL = "#c8402a";
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

  const markers = new Map(premises.map((p) => {
    const marker = L.circleMarker([p.lat, p.lon], { radius: 7, weight: 2, fillOpacity: 1 })
      .bindTooltip(label(p.name))
      .on("click", () => onSelect(p.id))
      .addTo(map);
    return [p.id, { marker, isEatery: p.sector === "eatery" }];
  }));

  return {
    setScenario(rp) {
      const index = SCENARIOS.indexOf(rp);
      for (const { depths, layer } of cells) {
        const level = band(depths[index]);
        layer.setStyle({ fillColor: BAND_COLORS[level - 1] ?? "transparent", fillOpacity: level ? 0.5 : 0 });
      }
    },
    setSelected(id) {
      for (const [markerId, { marker, isEatery }] of markers) {
        const selected = markerId === id;
        marker.setStyle({
          radius: selected ? 11 : 7,
          color: selected ? SIGNAL : isEatery ? PAPER : INK,
          fillColor: isEatery ? INK : PAPER,
          weight: selected ? 4 : 2,
        });
        if (selected) marker.bringToFront();
      }
    },
  };
}
