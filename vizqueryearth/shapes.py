"""Shapes drawn on the globe, as queryearth reads and writes them.

The drawing tool gives longitudes from -180 to 180, so a shape drawn across the
date line has an edge that jumps, for example from 170 to -170. queryearth takes
every edge the short way round and splits the shape at ±180, so a drawn ring
goes to queryearth as it is, and queryearth decides what the shape is. Rule
files get the split form, which other GeoJSON tools also read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import shapely
import shapely.geometry
from queryearth import space as sp
from queryearth.rules import box_of

__all__ = [
    "Shape",
    "antarctic",
    "arctic",
    "editable",
    "extent",
    "fill",
    "from_drawn",
    "label_point",
    "outline",
]

DIGITS = 6  # decimals kept, about 0.1 m; matches what the file gets
POLE = 89.5  # a point drawn this close to a pole is taken to be on it
_SEAMS = shapely.MultiLineString(
    [[(-180, -90), (-180, 90)], [(180, -90), (180, 90)]]
    + [[(-180, 90), (180, 90)], [(-180, -90), (180, -90)]]
).buffer(1e-7)


@dataclass(frozen=True, eq=False)
class Shape:
    """A rule's shape: a GeoJSON geometry or a record box, never both.

    geometry is a Polygon or MultiPolygon as queryearth writes it, split at
    ±180; box is a record's {west, width, south, north}.
    """

    geometry: dict[str, Any] | None = None
    box: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if (self.geometry is None) == (self.box is None):
            raise ValueError("a shape is a geometry or a box")
        space = sp.polygon(self.geometry) if self.box is None else box_of(self.box)
        object.__setattr__(self, "_space", space)  # queryearth checks it here

    @classmethod
    def of(cls, feature: Mapping[str, Any]) -> Shape | None:
        """A record's shape as it is in the file, or None when it has none."""
        box = (feature.get("properties") or {}).get("box")
        if box is not None:
            return cls(box=box)
        if feature.get("geometry") is not None:
            return cls(geometry=feature["geometry"])
        return None

    @property
    def space(self) -> sp.Space:
        """The shape as queryearth reads it from a record."""
        return self._space

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Shape):
            return NotImplemented
        return (self.geometry, self.box) == (other.geometry, other.box)

    def __repr__(self) -> str:
        if self.box is not None:
            return f"Shape(box={self.box})"
        return f"Shape(geometry={self.geometry['type']})"


def arctic(south: float = 66.5) -> Shape:
    """Everything north of a latitude, as a full-width box."""
    return Shape(box={"west": -180, "width": 360, "south": _number(south), "north": 90})


def antarctic(north: float = -60.0) -> Shape:
    """Everything south of a latitude, as a full-width box."""
    return Shape(
        box={"west": -180, "width": 360, "south": -90, "north": _number(north)}
    )


def from_drawn(features: Iterable[Mapping[str, Any]]) -> Shape | None:
    """The shape of everything drawn, or None when nothing is.

    One axis-aligned rectangle becomes a box; anything else becomes one
    geometry, the union of the polygons drawn.
    """
    polygons = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "Polygon":
            polygons.append(geometry["coordinates"])
        elif geometry.get("type") == "MultiPolygon":
            polygons.extend(geometry["coordinates"])
    if not polygons:
        return None
    polygons = [[_rounded_ring(ring) for ring in polygon] for polygon in polygons]
    if len(polygons) == 1 and len(polygons[0]) == 1:
        box = _box(polygons[0][0])
        if box is not None:
            return Shape(box=box)
    drawn = {"type": "MultiPolygon", "coordinates": polygons}
    return Shape(geometry=_written(sp.polygon(drawn).geometry))


def fill(shape: Shape) -> dict[str, Any]:
    """The area to show on the globe: the shape split at ±180."""
    return _mapping(shape.space.geometry)


def outline(shape: Shape) -> dict[str, Any] | None:
    """The edges to draw: the shape's boundary without the cuts at ±180 and the
    edges along a pole, which are not edges on a globe."""
    lines = shapely.difference(shapely.boundary(shape.space.geometry), _SEAMS)
    return None if lines.is_empty else _mapping(lines)


def editable(shape: Shape) -> list[dict[str, Any]] | None:
    """The polygons to hand to the drawing tool to move their corners, or None
    when the shape has holes, crosses ±180 or reaches a pole: redraw those."""
    geometry = shape.space.geometry
    parts = list(getattr(geometry, "geoms", [geometry]))
    if any(p.interiors for p in parts) or any(p.intersects(_SEAMS) for p in parts):
        return None
    return [_mapping(p) for p in parts]


def extent(shapes: Iterable[Shape]) -> list[float] | None:
    """[west, south, east, north] around shapes, or None when there are none.

    Longitudes go the short way round, so east is past 180 when the shapes cross
    the date line: [165, 52, 200, 66] for the Bering Sea. A part that goes all
    the way round, such as a polar cap, counts only for latitude, unless no
    other part does; the extent is then [-180, south, 180, north].
    """
    spans, round_the_world = [], False
    south, north = 90.0, -90.0
    for shape in shapes:
        geometry = shape.space.geometry
        for part in getattr(geometry, "geoms", [geometry]):
            w, s, e, n = part.bounds
            south, north = min(south, s), max(north, n)
            if e - w >= 360 - 1e-9:
                round_the_world = True
            else:
                spans.append((w, e))
    if not spans:
        return [-180, _number(south), 180, _number(north)] if round_the_world else None
    spans.sort()
    gap, west, reach = 0.0, spans[0][0], spans[0][1]
    for w, e in spans[1:] + [(spans[0][0] + 360, reach)]:
        if w - reach > gap:  # the widest stretch of longitude without a part
            gap, west = w - reach, w
        reach = max(reach, e)
    west = (west + 180) % 360 - 180
    return [_number(west), _number(south), _number(west + 360 - gap), _number(north)]


def label_point(shape: Shape) -> list[float]:
    """Where to put the rule's code: inside its largest part."""
    geometry = shape.space.geometry
    largest = max(getattr(geometry, "geoms", [geometry]), key=lambda p: p.area)
    point = largest.point_on_surface()
    return [_number(point.x), _number(point.y)]


def _number(value: float) -> float | int:
    """A coordinate rounded to DIGITS decimals; a whole number as an int."""
    value = round(float(value), DIGITS) + 0.0  # no -0.0
    return int(value) if value.is_integer() else value


def _rounded_ring(ring: list[list[float]]) -> list[list[float]]:
    """A drawn ring, rounded, with points next to a pole taken to the pole."""
    return [[_number(lon), _number(_to_pole(lat))] for lon, lat in ring]


def _to_pole(lat: float) -> float:
    return 90.0 if lat >= POLE else -90.0 if lat <= -POLE else lat


def _box(ring: list[list[float]]) -> dict[str, float] | None:
    """The record box of an axis-aligned rectangle, or None for any other ring.
    Like queryearth's edges, a rectangle spans the short way round, so one drawn
    from 170 to -170 crosses the date line."""
    corners = {tuple(p) for p in ring}
    lons, lats = {p[0] for p in corners}, {p[1] for p in corners}
    if len(corners) != 4 or len(lons) != 2 or len(lats) != 2:
        return None
    a, b = sorted(lons)
    west, width = (a, b - a) if b - a <= 180 else (b, 360 - (b - a))
    west = _number((west + 180.0) % 360.0 - 180.0)
    return {
        "west": west,
        "width": _number(width),
        "south": min(lats),
        "north": max(lats),
    }


def _written(geometry: shapely.Geometry) -> dict[str, Any]:
    """A geometry as Rule.to_feature writes it: edges no longer than 180 degrees,
    so a reader cannot take them the short way round, then normalised."""
    geometry = shapely.segmentize(geometry, 180.0)
    return _mapping(shapely.orient_polygons(shapely.normalize(geometry)))


def _mapping(geometry: shapely.Geometry) -> dict[str, Any]:
    """GeoJSON for a geometry, with coordinates rounded as _number does."""

    def rounded(value: Any) -> Any:
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], float):
            return [_number(v) for v in value]
        if isinstance(value, (list, tuple)):
            return [rounded(v) for v in value]
        return value

    mapping = shapely.geometry.mapping(geometry)
    return {"type": mapping["type"], "coordinates": rounded(mapping["coordinates"])}
