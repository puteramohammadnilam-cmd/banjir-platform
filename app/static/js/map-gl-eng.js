// Engineer mode's drawing on the new map (map.html; engineer.js draws through it, NO_DRAWER there says how): the rain
// pools and a tool's picture as image layers under the streets and names, the clicked points joined by a line, and the
// map's clicks while a tool is on. Another base map clears every layer, so what is on show is kept here and drawn again
// (redraw). The same panel and words as the main page's engineer mode.

const MARK = "#f59e0b";

/** An image source's four corners, clockwise from the top left, for bounds [west, south, east, north]. */
export const imageCorners = ([west, south, east, north]) => [[west, north], [east, north], [east, south], [west, south]];

/** The clicked points ({lat, lng}) as GeoJSON: each a point, and a line through them once there are two. */
export function marksGeo(points) {
  const coords = points.map((p) => [p.lng, p.lat]);
  const dots = coords.map((coordinates) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates } }));
  const line = coords.length > 1 ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }] : [];
  return { type: "FeatureCollection", features: [...line, ...dots] };
}

function addImage(map, id, { url, bounds, opacity }, beforeId) {
  map.addSource(id, { type: "image", url, coordinates: imageCorners(bounds) });
  map.addLayer({ id, type: "raster", source: id,
    paint: { "raster-opacity": opacity, "raster-fade-duration": 0, "raster-resampling": "nearest" } }, beforeId);
}

function removeImage(map, id) {
  if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(id)) map.removeSource(id);
}

function drawMarks(map, id, points) {
  if (map.getSource(id)) return map.getSource(id).setData(marksGeo(points));
  map.addSource(id, { type: "geojson", data: marksGeo(points) });
  map.addLayer({ id: `${id}-line`, type: "line", source: id, filter: ["==", ["geometry-type"], "LineString"],
    paint: { "line-color": MARK, "line-width": 3 } });
  return map.addLayer({ id: `${id}-dot`, type: "circle", source: id, filter: ["==", ["geometry-type"], "Point"],
    paint: { "circle-radius": 5, "circle-color": "#fff", "circle-stroke-color": MARK, "circle-stroke-width": 2.5 } });
}

/** The drawer, its layers named `${prefix}-${key}` (the map's extra layers use one with its own prefix: map-gl-layers.js).
 *  getMap() gives the map once it is up; beforeId(map, key) the layer a picture goes under; hasOurLayers(map)
 *  whether the page's own layers are on the map's style yet (not while another base map loads: redraw() then adds it
 *  all); isAiming() whether the pin has the map's clicks; onToolChange() is told when a tool is picked or put down;
 *  onError(key) when a picture on show did not load.
 *  click(lngLat) hands a click to the tool that is on, and says whether one took it. */
export function glDrawer({ getMap, beforeId, hasOurLayers, isAiming = () => false, onToolChange = () => {}, onError = null, prefix = "mg-eng" }) {
  const layerId = (key) => `${prefix}-${key}`;
  const marksId = layerId("marks");
  const shown = {};   // by key: {url, bounds, opacity}
  let points = [];
  let tool = null;
  let isListening = false;
  const listen = (map) => {   // once: the map stays the same across base maps
    if (!onError || isListening) return;
    isListening = true;
    map.on("error", (event) => {
      const key = Object.keys(shown).find((name) => layerId(name) === event.sourceId);
      if (key) onError(key);
    });
  };
  const ready = () => {
    const map = getMap();
    // not map.isStyleLoaded(): that is false too while any tile or picture loads, and a drop then would leave it drawn
    return map && hasOurLayers(map) ? map : null;
  };
  return {
    isAiming,
    picture(key, url, bounds, opacity) {
      const map = ready();
      const isSame = shown[key]?.url === url && Boolean(map?.getLayer(layerId(key)));
      shown[key] = { url, bounds, opacity };
      if (!map || isSame) return;   // already drawn: not loaded again, and it keeps its place among the layers
      listen(map);
      removeImage(map, layerId(key));
      addImage(map, layerId(key), shown[key], beforeId(map, key));
    },
    drop(key) {
      if (key === "marks") return this.marks([]);   // the panel clears its points by this name too
      delete shown[key];
      const map = ready();
      return map && removeImage(map, layerId(key));
    },
    marks(next) {
      points = next;
      const map = ready();
      if (map) drawMarks(map, marksId, points);
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
      if (Object.keys(shown).length) listen(map);
      Object.entries(shown).forEach(([key, picture]) => addImage(map, layerId(key), picture, beforeId(map, key)));
      if (points.length) drawMarks(map, marksId, points);   // none drawn: nothing to bring back
    },
  };
}
