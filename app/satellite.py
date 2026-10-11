"""Esri World Imagery for the 3D page's satellite photo, through an ArcGIS Location Platform API key.

Set ARCGIS_API_KEY in .env (README, "Satellite photo on the 3D page"). Unlike GOOGLE_MAPS_API_KEY this key does reach
the browser: the map asks Esri for each tile itself, with the key in the tile URL, as Esri's own MapLibre tutorial does
("Display multiple basemap layers"). So it must be a key made for that: a "Public application" key with only the
basemap tiles privilege, restricted to this site's address. Without it the 3D page shows the OpenStreetMap street map
and no satellite switch.

Terms that shape this file (read 11 October 2026): the Location Platform subscription comes with a commercial
deployment licence; its free tier is 2,000,000 basemap tiles a month, and tile requests to ibasemaps-api.arcgis.com
count towards it; with pay-as-you-go off (the default for a new account) a service past its free tier stops until the
next billing cycle instead of being billed. Esri asks for "Powered by Esri" and the imagery's sources on the map.
"""
from __future__ import annotations

import os
import urllib.parse

KEY_NAME = "ARCGIS_API_KEY"
SERVICE = "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer"
# ponytail: World Imagery's sources as Esri's attribution page gives its copyrightText (read 11 October 2026). Esri asks
# apps to read it from the service; do that, from the browser with the key, if the list starts to change.
SOURCES = ("Source: Esri, Vantor, GeoEye, Earthstar Geographics, CNES/Airbus DS, USDA, USGS, AeroGRID, IGN, "
           "and the GIS User Community")
ATTRIBUTION = f'Powered by <a href="https://www.esri.com">Esri</a> | {SOURCES}'


def _key() -> str:
    return os.environ.get(KEY_NAME, "").strip()


def is_configured() -> bool:
    return bool(_key())


def imagery() -> dict | None:
    """The tile URL template, key included, and the credit the map shows under it; None without a key."""
    key = _key()
    if not key:
        return None
    return {"tiles": f"{SERVICE}/tile/{{z}}/{{y}}/{{x}}?token={urllib.parse.quote(key, safe='')}",
            "attribution": ATTRIBUTION}
