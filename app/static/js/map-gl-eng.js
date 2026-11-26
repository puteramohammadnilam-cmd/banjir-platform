// Engineer mode's drawing on the new map (map.html; engineer.js draws through it, NO_DRAWER there says how): the rain
// pools and a tool's picture as image layers under the streets and names, the clicked points joined by a line, and the
// map's clicks while a tool is on. Another base map clears every layer, so what is on show is kept here and drawn again
// (redraw). The same panel and words as the main page's engineer mode.

const MARK = "#f59e0b";
const MARKS = "mg-eng-marks";
const layerId = (key) => `mg-eng-${key}`;

/** An image source's four corners, clockwise from the top left, for bounds [west, south, east, north]. */
export const imageCorners = ([west, south, east, north]) => [[west, north], [east, north], [east, south], [west, south]];

/** The clicked points ({lat, lng}) as GeoJSON: each a point, and a line through them once there are two. */
export function marksGeo(points) {
  const coords = points.map((p) => [p.lng, p.lat]);
  const dots = coords.map((coordinates) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates } }));
  const line = coords.length > 1 ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }] : [];
  return { type: "FeatureCollection", features: [...line, ...dots] };
}

function addImage(map, key, { url, bounds, opacity }, beforeId) {
  map.addSource(layerId(key), { type: "image", url, coordinates: imageCorners(bounds) });
  map.addLayer({ id: layerId(key), type: "raster", source: layerId(key),
    paint: { "raster-opacity": opacity, "raster-fade-duration": 0, "raster-resampling": "nearest" } }, beforeId);
}

function removeImage(map, key) {
  if (map.getLayer(layerId(key))) map.removeLayer(layerId(key));
  if (map.getSource(layerId(key))) map.removeSource(layerId(key));
}

function drawMarks(map, points) {
  if (map.getSource(MARKS)) return map.getSource(MARKS).setData(marksGeo(points));
  map.addSource(MARKS, { type: "geojson", data: marksGeo(points) });
  map.addLayer({ id: `${MARKS}-line`, type: "line", source: MARKS, filter: ["==", ["geometry-type"], "LineString"],
    paint: { "line-color": MARK, "line-width": 3 } });
  return map.addLayer({ id: `${MARKS}-dot`, type: "circle", source: MARKS, filter: ["==", ["geometry-type"], "Point"],
    paint: { "circle-radius": 5, "circle-color": "#fff", "circle-stroke-color": MARK, "circle-stroke-width": 2.5 } });
}

/** The drawer. getMap() gives the map once it is up; beforeId(map) the layer the pictures go under; hasOurLayers(map)
 *  whether the page's own layers are on the map's style yet (not while another base map loads: redraw() then adds it
 *  all); isAiming() whether the pin has the map's clicks; onToolChange() is told when a tool is picked or put down.
 *  click(lngLat) hands a click to the tool that is on, and says whether one took it. */
export function glDrawer({ getMap, beforeId, hasOurLayers, isAiming = () => false, onToolChange = () => {} }) {
  const shown = {};   // by key: {url, bounds, opacity}
  let points = [];
  let tool = null;
  const ready = () => {
    const map = getMap();
    // not map.isStyleLoaded(): that is false too while any tile or picture loads, and a drop then would leave it drawn
    return map && hasOurLayers(map) ? map : null;
  };
  return {
    isAiming,
    picture(key, url, bounds, opacity) {
      shown[key] = { url, bounds, opacity };
      const map = ready();
      if (!map) return;
      removeImage(map, key);
      addImage(map, key, shown[key], beforeId(map));
    },
    drop(key) {
      if (key === "marks") return this.marks([]);   // the panel clears its points by this name too
      delete shown[key];
      const map = ready();
      return map && removeImage(map, key);
    },
    marks(next) {
      points = next;
      const map = ready();
      if (map) drawMarks(map, points);
    },
    setTool(isOn, onClick) {
      tool = isOn ? onClick : null;
      onToolChange();
    },
    isToolOn: () => tool !== null,
    click(lngLat) {
      if (!tool) return false;
      tool({ latlng: { lat: lngLat.lat, lng: lngLat.lng } });
      return true;
    },
    /** After a base map change: the pictures and the marks again, over the new map's layers. */
    redraw(map) {
      Object.entries(shown).forEach(([key, picture]) => addImage(map, key, picture, beforeId(map)));
      drawMarks(map, points);
    },
  };
}
