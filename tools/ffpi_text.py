"""The words that go with the flash flood potential index: its credit line and method (shah-alam_ffpi.json) and
app/data/indexes/SOURCES.txt. Plain text, no HTML; the page shows them as given."""
from __future__ import annotations

from collections.abc import Sequence

CREDIT = ("Flash flood potential: ESA WorldCover 2021 and its Sentinel-2 NDVI composite (contains modified Copernicus "
          "Sentinel data (2021) processed by ESA WorldCover consortium, CC BY 4.0), SoilGrids 2.0 (ISRIC, CC BY 4.0) "
          "and Copernicus DEM GLO-30 ((c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided "
          "under COPERNICUS by the European Union and ESA); method after Smith (2003) as used by Mohd Yassin et al. "
          "(2023).")

FACTORS = {
    "M": "Slope: from the Copernicus GLO-30 surface after taking the lowest height of each 3 x 3 squares (about 90 m) "
         "to drop most roofs and trees. 3 % or less rates 1, each further 3 % one more, above 27 % rates 10 (the "
         "paper's table leaves 27-30 % out; its 3 % steps are continued).",
    "L": "Land cover: ESA WorldCover 2021 (10 m) in each square, rated with the paper's table: water 1, wetland and "
         "mangrove 2, tree cover 3 (plantations included), shrubland 5, grassland and cropland 6, bare ground 7. "
         "A square at least a fifth built-up rates by its built-up share, as the US land cover database the table "
         "comes from sorts developed land: 80 % or more 10, 50-79 % 9, 20-49 % 8; under a fifth, built-up pixels "
         "count as developed open space (7) and the square takes the mean.",
    "S": "Soil: SoilGrids 2.0 sand, silt and clay in the top 15 cm, sorted into a USDA texture class and rated with "
         "the paper's table (silty clay, which the table leaves out, rates 9 like clay). SoilGrids has no value under "
         "towns; there the square's built-up share counts as impervious (10) and the rest takes the nearest "
         "SoilGrids value.",
    "V": "Vegetation: the share of ground under plants from the 2021 Sentinel-2 NDVI composite (median), "
         "((NDVI - 0.2) / (0.86 - 0.2)) squared, averaged over the square. 90-100 % rates 1, each 10 % less one more, "
         "under 10 % rates 10.",
}

CITATIONS = [
    "Smith, G. (2003). Flash flood potential: determining the hydrologic response of FFMP basins to heavy rain by "
    "analyzing their physiographic characteristics. NOAA National Weather Service, Colorado Basin River Forecast "
    "Center.",
    "Mohd Yassin, N. A., Adnan, N. A. and Md Sadek, E. S. S. (2023). Analysis of Flash Flood Potential Index (FFPI) "
    "and scenarios assessment in Shah Alam using GIS approach. Planning Malaysia 21(2).",
    "Carlson, T. N. and Ripley, D. A. (1997). On the relation between NDVI, fractional vegetation cover, and leaf "
    "area index. Remote Sensing of Environment 62(3): 241-252.",
    "Horn, B. K. P. (1981). Hill shading and the reflectance map. Proceedings of the IEEE 69(1): 14-47.",
]

DEVIATIONS = [
    "Land cover is ESA WorldCover 2021, not the US land cover database the rating table was written for; developed "
    "intensity comes from each square's built-up share.",
    "Slopes of 27-30 %, which the paper leaves unrated, rate 10.",
    "Silty clay, missing from the soil table, rates 9 like clay.",
    "Where SoilGrids has no value (under towns), the built-up share counts as impervious and the rest takes the "
    "nearest SoilGrids value.",
    "Vegetation cover comes from NDVI (Carlson and Ripley's scaled NDVI squared), not from a mapped percentage.",
    "The surface model includes roofs and trees; taking the lowest height of each 3 x 3 squares before the slope "
    "removes most of them, not all.",
    "The paper names four classes but not their limits. Its Scenario 2 scores of 5 to 6 read as medium, so medium "
    "here is 4.5 to under 6.5 (5 and 6 once rounded); low is below 4.5, high from 6.5 and extreme from 8.5.",
]


def method() -> dict:
    """shah-alam_ffpi.json `method`."""
    return {
        "name": "Flash Flood Potential Index (FFPI)",
        "formula": "(1.5 M + L + S + 0.5 V) / 4",
        "summary": "Each 30 m square is rated 1 to 10 for slope (M), land cover (L), soil (S) and bare ground (V); the "
                   "four are weighted as in the paper's Scenario 2 and rounded to 0.1. Higher means water runs off "
                   "faster and gathers sooner after heavy rain. The classes follow the paper's reading of scores of "
                   "5 to 6 as medium: low below 4.5, medium from 4.5, high from 6.5, extreme from 8.5.",
        "factors": dict(FACTORS),
        "classes": "Four classes, as the paper names them; it gives no limits but reads Scenario 2 scores of 5 to 6 "
                   "as medium, so medium runs from 4.5 to under 6.5 (5 and 6 once rounded): low below 4.5, medium "
                   "from 4.5, high from 6.5, extreme from 8.5. A score on a limit is in the class above.",
        "citations": list(CITATIONS),
        "deviations": list(DEVIATIONS),
        "not": "A susceptibility to flash floods, not a water depth and not a chance of flooding. Drains, their size "
               "and upkeep, which decide most town flash floods, are not in it.",
    }


def sources_text(log: Sequence[dict], outputs: Sequence[str], date: str) -> str:
    """app/data/indexes/SOURCES.txt from the fetch log and the output lines (name, bytes, SHA-256)."""
    lines = [
        "Flash flood potential index (FFPI) in this folder", "=" * 50, "",
        "app/indexes.py reads these files. They are small, so they are kept in git. To make them again, from",
        "11_Platform_Draft (BANJIR_RAW_DIR pointing at ../05_Raw_Data_Sources):", "",
        "  .venv/bin/python tools/fetch_indexes.py worldcover   # and ndvi, soilgrids, worldpop, drains",
        "  .venv/bin/python tools/build_ffpi.py",
        "  .venv/bin/python tools/build_section_scores.py", "",
        "The fetch step is needed once; the build reads only the saved files listed below and gives the same bytes",
        f"each time (inputs fetched {date}). The method is in tools/build_ffpi.py's docstring and in",
        "shah-alam_ffpi.json; the section figures' in tools/build_section_scores.py.", "",
        "Outputs", "-------", *outputs, "",
        "Other inputs: app/data/dem/shah-alam_surface.tif (Copernicus GLO-30, see app/data/dem/SOURCES.txt) and the",
        "city outline, shah_alam/mbsa_sections/city_outline.geojson ((c) OpenStreetMap contributors, ODbL).", "",
        "Downloaded inputs (in ../05_Raw_Data_Sources/shah_alam/indexes, listed in its SOURCES.md)", "-" * 60,
    ]
    for entry in log:
        lines += [f"{entry['file']}: {entry['bytes']} bytes, SHA-256 {entry['sha256']}, fetched {entry['date']}",
                  f"  {entry['url']}"]
    lines += ["", "Credit", "------", CREDIT, "",
              "Licences: ESA WorldCover map and NDVI composite CC BY 4.0; SoilGrids 2.0 CC BY 4.0; WorldPop CC BY 4.0;",
              "OpenStreetMap ODbL 1.0; Copernicus DEM GLO-30 under the Copernicus DEM licence (any use, with the credit).",
              "The rating tables are the published method's; no text or figure of the papers is copied.", ""]
    return "\n".join(lines)
