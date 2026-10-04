"""Plain geometry on GeoJSON areas, standard library only: point in polygon, bounding box, area, simplification and
distance in metres.

Coordinates are GeoJSON order, (lon, lat) in degrees. A ring is a closed list of points (first equals last). A polygon is
a list of rings, the outer ring first and any holes after it. A geometry is a GeoJSON dict of type Polygon or
MultiPolygon. Nothing here changes what it is given; every result is a new object.

The edge rule: the boundary belongs to the area. A point exactly on an edge or a vertex of the outer ring is inside, and
so is a point on the edge of a hole (the hole's edge is part of the polygon's boundary). Only the open inside of a hole
is outside. A point on an edge two areas share therefore falls in both; `containing` gives it to the first in the list.

Area is on the sphere, from an equal-area cylindrical projection of the rings (the method the section fetch tool in
tools/ uses), so the two agree to the last digit. Simplification and distance work in local metres on an equirectangular
projection around the points concerned, good to a small fraction of a percent over a few tens of kilometres.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

EARTH_RADIUS_KM = 6371.0088
M_PER_DEG = EARTH_RADIUS_KM * 1000 * math.pi / 180   # one degree of latitude, in metres
EDGE_EPS = 1e-14          # square degrees: a cross product this small means the point is on the line
TIE_METRES = 1e-6         # two distances this close are a tie, and the first in the list wins
MAX_SIMPLIFY_TRIES = 6    # a simplified ring that crosses itself is retried at half the tolerance this many times

Point = Sequence[float]
Ring = Sequence[Point]
Polygon = Sequence[Ring]
BBox = tuple[float, float, float, float]   # west, south, east, north


# ---------- geometry shapes

def polygons_of(geometry: dict) -> list[Polygon]:
    """The polygons of a Polygon or MultiPolygon geometry, as a list; anything else is refused."""
    kind = geometry.get("type")
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"A Polygon or MultiPolygon is needed, got {kind!r}.")


def _same_kind(geometry: dict, polygons: list[list[list[Point]]]) -> dict:
    if geometry.get("type") == "Polygon":
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


# ---------- point in polygon

def _on_segment(x: float, y: float, a: Point, b: Point) -> bool:
    cross = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
    if abs(cross) > EDGE_EPS:
        return False
    return min(a[0], b[0]) <= x <= max(a[0], b[0]) and min(a[1], b[1]) <= y <= max(a[1], b[1])


def on_ring_edge(x: float, y: float, ring: Ring) -> bool:
    """True when the point lies on an edge or vertex of the ring."""
    return any(_on_segment(x, y, ring[i], ring[i + 1]) for i in range(len(ring) - 1))


def _ray_inside(x: float, y: float, ring: Ring) -> bool:
    """Ray casting to the right. Each edge counts when it spans the point's y by the half-open rule, so a ray through a
    vertex is counted once; on-edge points are not decided here."""
    inside = False
    for i in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[i][:2], ring[i + 1][:2]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_ring(x: float, y: float, ring: Ring) -> bool:
    """True when the point is inside the ring or on its edge."""
    return on_ring_edge(x, y, ring) or _ray_inside(x, y, ring)


def point_in_polygon(x: float, y: float, polygon: Polygon) -> bool:
    """Inside the outer ring and not in the open inside of a hole; the outer and hole edges both count as inside."""
    if not point_in_ring(x, y, polygon[0]):
        return False
    for hole in polygon[1:]:
        if not on_ring_edge(x, y, hole) and _ray_inside(x, y, hole):
            return False
    return True


def point_in_geometry(x: float, y: float, geometry: dict) -> bool:
    """True when the point is in any polygon of a Polygon or MultiPolygon geometry."""
    return any(point_in_polygon(x, y, polygon) for polygon in polygons_of(geometry))


# ---------- bounding box

def bbox(geometry: dict) -> BBox:
    """(west, south, east, north) of a geometry."""
    points = [p for polygon in polygons_of(geometry) for p in polygon[0]]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def in_bbox(x: float, y: float, box: BBox, margin_deg: float = 0.0) -> bool:
    """True when the point is in the box or on its edge, the box widened by margin_deg on every side."""
    return box[0] - margin_deg <= x <= box[2] + margin_deg and box[1] - margin_deg <= y <= box[3] + margin_deg


# ---------- area

def ring_area_km2(ring: Ring) -> float:
    """The area inside a ring on the sphere (shoelace on an equal-area cylindrical projection), always positive."""
    xs = [math.radians(p[0]) * EARTH_RADIUS_KM for p in ring]
    ys = [math.sin(math.radians(p[1])) * EARTH_RADIUS_KM for p in ring]
    twice = sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(ring) - 1))
    return abs(twice) / 2


def polygon_area_km2(polygon: Polygon) -> float:
    """The outer ring's area less the holes'."""
    return ring_area_km2(polygon[0]) - sum(ring_area_km2(hole) for hole in polygon[1:])


def geometry_area_km2(geometry: dict) -> float:
    return sum(polygon_area_km2(polygon) for polygon in polygons_of(geometry))


# ---------- local metres

def _metres(points: Iterable[Point], lon0: float, lat0: float) -> list[tuple[float, float]]:
    """Points as (east, north) metres from (lon0, lat0), on an equirectangular projection."""
    scale = math.cos(math.radians(lat0))
    return [((p[0] - lon0) * scale * M_PER_DEG, (p[1] - lat0) * M_PER_DEG) for p in points]


def _segment_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


# ---------- distance

def distance_to_ring_m(x: float, y: float, ring: Ring) -> float:
    """Metres from the point to the nearest edge of the ring, whether the point is inside it or outside."""
    flat = _metres(ring, x, y)
    return min(_segment_distance((0.0, 0.0), flat[i], flat[i + 1]) for i in range(len(flat) - 1))


def distance_to_polygon_edge_m(x: float, y: float, polygon: Polygon) -> float:
    """Metres to the nearest edge of the polygon, outer or hole, inside or outside."""
    return min(distance_to_ring_m(x, y, ring) for ring in polygon)


def distance_to_geometry_m(x: float, y: float, geometry: dict) -> float:
    """0 for a point in the area (edges included), else the metres to the nearest edge of any part."""
    if point_in_geometry(x, y, geometry):
        return 0.0
    return min(distance_to_polygon_edge_m(x, y, polygon) for polygon in polygons_of(geometry))


# ---------- containing and nearest

def _box_of(item: dict) -> BBox:
    return item.get("bbox") or bbox(item["geometry"])


def containing(x: float, y: float, items: Iterable[dict]) -> dict | None:
    """The first item (a dict with "geometry" and, if known, "bbox") whose area holds the point, else None."""
    for item in items:
        if in_bbox(x, y, _box_of(item)) and point_in_geometry(x, y, item["geometry"]):
            return item
    return None


def nearest_within(x: float, y: float, items: Iterable[dict], max_m: float) -> tuple[dict, float] | None:
    """The item whose area is nearest the point, as (item, metres), when that is no more than max_m; an item holding the
    point is 0 m away. The first item wins a tie. None when nothing is within reach."""
    margin = max_m / (M_PER_DEG * max(math.cos(math.radians(y)), 0.01))
    best: tuple[dict, float] | None = None
    for item in items:
        if not in_bbox(x, y, _box_of(item), margin):
            continue
        metres = distance_to_geometry_m(x, y, item["geometry"])
        if metres <= max_m and (best is None or metres < best[1] - TIE_METRES):
            best = (item, metres)
    return best


# ---------- simplification

def _orientation(a: Point, b: Point, c: Point) -> int:
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (value > 0) - (value < 0)


def _segments_meet(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1, o2, o3, o4 = _orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return any(o == 0 and _on_segment(p[0], p[1], s, e) for o, p, s, e in ((o1, c, a, b), (o2, d, a, b), (o3, a, c, d), (o4, b, c, d)))


def ring_self_intersects(ring: Ring) -> bool:
    """True when two edges that are not neighbours cross or touch. Quadratic, so for rings of a few hundred points."""
    edges = len(ring) - 1
    for i in range(edges):
        for j in range(i + 2, edges):
            if i == 0 and j == edges - 1:
                continue
            if _segments_meet(ring[i], ring[i + 1], ring[j], ring[j + 1]):
                return True
    return False


def _keep_chain(flat: list[tuple[float, float]], tolerance: float) -> set[int]:
    """Douglas-Peucker on an open chain: the indices kept, both ends always among them."""
    keep = {0, len(flat) - 1}
    stack = [(0, len(flat) - 1)]
    while stack:
        lo, hi = stack.pop()
        far, far_d = -1, tolerance
        for i in range(lo + 1, hi):
            d = _segment_distance(flat[i], flat[lo], flat[hi])
            if d > far_d:
                far, far_d = i, d
        if far >= 0:
            keep.add(far)
            stack.extend([(lo, far), (far, hi)])
    return keep


def _simplify_once(ring: Ring, tolerance_m: float) -> list[tuple[float, float]]:
    """One Douglas-Peucker pass over a closed ring, split at its first vertex and the vertex farthest from it, so
    neither anchor depends on where the ring happens to start. Fewer than three vertices left means the farthest one
    from the anchors' chord is added back. A ring that is all one line comes back unchanged."""
    points = [tuple(p[:2]) for p in ring[:-1]]
    lat0 = sum(p[1] for p in points) / len(points)
    lon0 = sum(p[0] for p in points) / len(points)
    flat = _metres(points, lon0, lat0)
    split = max(range(len(flat)), key=lambda i: math.hypot(flat[i][0] - flat[0][0], flat[i][1] - flat[0][1]))
    first, second = flat[: split + 1], flat[split:] + [flat[0]]
    keep = {i for i in _keep_chain(first, tolerance_m)} | {split + i for i in _keep_chain(second, tolerance_m)}
    keep.discard(len(flat))
    if len(keep) < 3:
        chord = (flat[0], flat[split])
        spare = max((i for i in range(len(flat)) if i not in keep), key=lambda i: _segment_distance(flat[i], *chord), default=None)
        if spare is None or _segment_distance(flat[spare], *chord) == 0:
            return [(p[0], p[1]) for p in ring]
        keep.add(spare)
    kept = [points[i] for i in sorted(keep)]
    return [*kept, kept[0]]


def simplify_ring(ring: Ring, tolerance_m: float) -> list[tuple[float, float]]:
    """A ring with fewer points, none of the dropped ones more than tolerance_m from the new outline. The result is
    closed with at least four points (three corners), never collapses, and does not cross itself: if a pass would
    cross, the tolerance is halved and it is tried again, and the ring comes back unchanged if it still crosses."""
    if tolerance_m <= 0 or len(ring) <= 4:
        return [(p[0], p[1]) for p in ring]
    tolerance = tolerance_m
    for _ in range(MAX_SIMPLIFY_TRIES):
        simple = _simplify_once(ring, tolerance)
        if not ring_self_intersects(simple):
            return simple
        tolerance /= 2
    return [(p[0], p[1]) for p in ring]


def _extent_m(ring: Ring) -> float:
    """The longer side of the ring's bounding box, in metres."""
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    lat = (min(ys) + max(ys)) / 2
    return max((max(xs) - min(xs)) * math.cos(math.radians(lat)), max(ys) - min(ys)) * M_PER_DEG


def simplify_polygon(polygon: Polygon, tolerance_m: float) -> list[list[tuple[float, float]]]:
    """Every ring simplified. A hole smaller than the tolerance in both directions is dropped; the outer ring stays."""
    rings = [simplify_ring(polygon[0], tolerance_m)]
    rings += [simplify_ring(hole, tolerance_m) for hole in polygon[1:] if _extent_m(hole) >= tolerance_m]
    return rings


def simplify_geometry(geometry: dict, tolerance_m: float) -> dict:
    """The same kind of geometry with simplified rings. Every part is kept, so a speck of a part becomes a small
    triangle rather than vanishing."""
    return _same_kind(geometry, [simplify_polygon(polygon, tolerance_m) for polygon in polygons_of(geometry)])
