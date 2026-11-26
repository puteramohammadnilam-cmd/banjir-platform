OpenFreeMap base map styles for the new map preview (map.html, js/map-gl.js)

positron.json and dark.json are copies of https://tiles.openfreemap.org/styles/positron and /styles/dark, taken on
26 November 2026. They are kept here, not loaded from OpenFreeMap, because map-gl-data.js underRoads() puts our flood
water under the first building, road or name layer by its id: a change to the remote style could otherwise move the
water over the names without warning. The vector tiles, fonts and sprites still come from tiles.openfreemap.org
(allowed in the Content-Security-Policy in app/main.py).

OpenFreeMap is a free public service with no account, no key and no service level agreement; it may change or stop at
any time. The map shows its credit (OpenFreeMap, OpenMapTiles, OpenStreetMap contributors) from the tiles' own
attribution. Licences of the styles: see https://github.com/hyperknot/openfreemap-styles (the Positron and Dark
designs come from the OpenMapTiles styles). The map data is OpenStreetMap, ODbL.

To refresh: download the two URLs above again over these files and check map.html still draws the water under the
streets and names.
