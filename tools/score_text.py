"""The words that go with the section flood risk score in indexes.json, and the build's printed report. Plain text."""
from __future__ import annotations

SOURCES = {
    "river_distance": "OpenStreetMap rivers and canals, lines and river water areas ((c) OpenStreetMap contributors, "
                      "ODbL), the ones app/data/dem was built with.",
    "drainage_density": "OpenStreetMap rivers, canals, streams, drains and ditches ((c) OpenStreetMap contributors, "
                        "ODbL): km of line within 1 km, per km2.",
    "elevation": "Copernicus DEM GLO-30, the lowest surface height of each 3 x 3 squares (about 90 m).",
    "land_cover": "ESA WorldCover 2021 (10 m, CC BY 4.0), each class rated and mixed by its share of the square.",
    "slope": "Copernicus DEM GLO-30, from the same lowest surface.",
    "road_distance": "OpenStreetMap vehicle roads, service ways left out ((c) OpenStreetMap contributors, ODbL).",
    "population_density": "WorldPop 2020 constrained population, 100 m (CC BY 4.0), summed over each section: "
                          "people per section.",
}
LAND_NAMES = {10: "tree cover", 20: "shrubland", 30: "grassland", 40: "cropland", 50: "built-up",
              60: "bare or sparse vegetation", 70: "snow and ice", 80: "permanent water", 90: "herbaceous wetland",
              95: "mangroves", 100: "moss and lichen"}

DEVIATIONS = [
    "Rainfall (weight 23) and economic loss (3) are left out: one rain record covers the whole city and no source "
    "gives losses by section. The other seven weights are divided by the 74 left.",
    "The paper's distance classes run to kilometres over a wider area; the distance classes here are ours, in metres "
    "for a city. Elevation, slope and population keep the paper's classes.",
    "The drainage density classes (breaks at 0.25, 0.5, 1 and 1.5 km per km2) are ours: the paper's, from a kernel "
    "density of the main rivers, do not carry over to mapped drains.",
    "Land cover is ESA WorldCover 2021 rated by us: built-up and water 5, bare ground, wetland and mangrove 4, "
    "grassland and cropland 3, shrubland 2, tree cover 1.",
    "Drainage density counts mapped drains and ditches; how much of the city's drainage is mapped differs from place "
    "to place, and a high density may mean a well drained area as easily as a wet one.",
    "Population is people per section as in the paper, but from WorldPop 2020 summed by section, not council "
    "figures; each square takes its section's rating. Under 1,000 rates 1 and the paper's four ranges 2 to 5.",
    "A section's value is the area-weighted mean of its 30 m squares, not the paper's hotspot analysis.",
]
CREDIT = ("Section score: WorldPop 2020 constrained (CC BY 4.0, doi:10.5258/SOTON/WP00660); OpenStreetMap rivers, "
          "drains and roads, (c) OpenStreetMap contributors, ODbL 1.0.")
CITATIONS = [
    "Leeonis, A. N., Ahmed, M. F., Halder, B., Mokhtar, M. B., Lim, C. K., Juneng, L. and Khirotdin, R. P. K. (2024). "
    "Mitigating flood risk at Shah Alam, Malaysia for sustainable development. Discover Sustainability 5: 352, "
    "doi:10.1007/s43621-024-00504-y (criteria and AHP weights).",
]


COARSE_WORDS = (("30 m squares", "92 m squares"), ("in metres for a city", "in metres for a city, kept for the state"),
                ("one rain record covers the whole city", "no rain record gives rain square by square"),
                ("the city's drainage", "the state's drainage"),
                ("averaging into the 1 arc-second grid", "averaging into the 3 arc-second grid"))
COARSE_ELEVATION = ("Copernicus DEM GLO-30, the lowest of the nine GLO-30 heights in each 92 m square (3 arc "
                    "seconds).")


def _coarse(text: str) -> str:
    for old, new in COARSE_WORDS:
        text = text.replace(old, new)
    return text


def score_method(step: int = 1) -> dict:
    """indexes.json `method.score` in words; `step` the squares' size in arc seconds (3: a state's 92 m squares)."""
    words = _coarse if step != 1 else (lambda text: text)
    return {
        "name": "Flood risk score (multi-criteria)",
        "summary": f"Each {92 if step != 1 else 30} m square of land is rated 1 to 5 on seven criteria (distance to a river, drainage "
                   "density, elevation, land cover, slope, distance to a road, population density); the ratings are "
                   "weighted as in Leeonis et al. (2024) and averaged over the section by area. 1 is the least "
                   "exposed, 5 the most.",
        "citations": list(CITATIONS),
        "deviations": [words(d) for d in DEVIATIONS],
        "credit": CREDIT,
    }


def criterion_extra(criterion: str, land_scores: dict[int, int], step: int = 1) -> dict:
    extra = {"source": COARSE_ELEVATION if step != 1 and criterion == "elevation" else SOURCES[criterion]}
    if criterion == "land_cover":
        extra["table"] = {LAND_NAMES[k]: v for k, v in land_scores.items()}
    return extra


def validation_doc(n: int, spearman: dict, hotspots: list[dict]) -> dict:
    """The comparison's figures and words; no hotspot source when no hotspots were named (a state's districts)."""
    found = {
        "wording": "Compared with past flood records and the river model; this does not validate either index.",
        "n": n,
        "history_counts": "Events in history.json naming the section (an event naming several sections counts for "
                          "each).",
        "wet_share": "Share of the section's 90 m squares wet at 1 in 50 years in the river model (sections.json).",
        "flash_metric": "Share of the section's land squares in the high or extreme class.",
        "spearman": spearman,
        "hotspots": hotspots,
        "hotspot_source": "Sections in the flood hotspot of Leeonis et al. (2024): Seksyen 36, 17, 18 and 16, and "
                          "Taman Seri Muda (Seksyen 25).",
        "rank_rule": "1 = highest of the n sections; ties share the best rank.",
    }
    if not hotspots:
        del found["hotspot_source"]
    return found


def report(doc: dict) -> str:
    """A plain summary for the terminal: the top ten sections each way, the city, and the comparisons."""
    rows = [(sid, s) for sid, s in doc["sections"].items() if s["flash"] is not None]
    by_flash = sorted(rows, key=lambda r: -(r[1]["flash"]["share"]["high"] + r[1]["flash"]["share"]["extreme"]))
    by_score = sorted(rows, key=lambda r: -r[1]["score"]["value"])
    lines = ["Top 10 by flash high + extreme share:"]
    lines += [f"  {sid}: {s['flash']['share']['high'] + s['flash']['share']['extreme']:.3f} (mean {s['flash']['mean']})"
              for sid, s in by_flash[:10]]
    lines += ["Top 10 by score:"]
    lines += [f"  {sid}: {s['score']['value']} {s['score']['class']}" for sid, s in by_score[:10]]
    lines += [f"City: {doc['city']}", f"Spearman: {doc['validation']['spearman']}",
              f"Hotspots: {doc['validation']['hotspots']}"]
    return "\n".join(lines)
