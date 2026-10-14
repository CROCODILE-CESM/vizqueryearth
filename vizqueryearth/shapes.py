"""Shapes drawn on a Leaflet map, as queryearth reads and writes them.

Leaflet keeps longitudes continuous: a box drawn across the date line from 165E
to 160W arrives as 165 to 200, and one drawn on a world copy may be shifted by
any multiple of 360. queryearth reads all of these and splits them at ±180, so a
drawn ring goes to queryearth as it is, and queryearth decides what the shape
is. Rule files get the split form, which other GeoJSON tools also read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import shapely
import shapely.affinity
import shapely.geometry
from queryearth import space as sp
from queryearth.rules import box_of

__all__ = ["Shape", "from_leaflet", "to_leaflet", "arctic", "antarctic", "MAP_LAT"]

DIGITS = 6  # decimals kept, about 0.1 m; matches what the file gets
MAP_LAT = 85.0511  # Leaflet's Web Mercator map ends at this latitude
_EDGE = 180.0 - 1e-9


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

    @property
    def space(self) -> sp.Space:
        """The shape as queryearth reads it from a record."""
        return self._space

    @property
    def editable(self) -> bool:
        """False when the shape reaches past the map's edge near a pole."""
        south, north = self.space.geometry.bounds[1::2]
        return -MAP_LAT <= south and north <= MAP_LAT

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
    return Shape(box={"west": -180, "width": 360, "south": south, "north": 90})


def antarctic(north: float = -60.0) -> Shape:
    """Everything south of a latitude, as a full-width box."""
    return Shape(box={"west": -180, "width": 360, "south": -90, "north": north})


def from_leaflet(features: Iterable[Mapping[str, Any]]) -> Shape | None:
    """The shape of everything on the drawing layer, or None when it is empty.

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


def to_leaflet(shape: Shape) -> list[dict[str, Any]]:
    """GeoJSON features to put on the map, one per polygon.

    Pieces split at ±180 are joined again, so a shape across the date line is
    shown and edited as one; parts beyond the map's edge near a pole are cut off.
    """
    if shape.box is not None:
        b = shape.box
        west, east = b["west"], b["west"] + b["width"]
        ring = [(west, b["south"]), (east, b["south"]), (east, b["north"])]
        ring += [(west, b["north"]), (west, b["south"])]
        geometry = shapely.Polygon(ring)
    else:
        geometry = _joined(shape.space.geometry)
    geometry = shapely.clip_by_rect(geometry, -540.0, -MAP_LAT, 540.0, MAP_LAT)
    return [
        {"type": "Feature", "properties": {}, "geometry": _mapping(part)}
        for part in getattr(geometry, "geoms", [geometry])
        if not part.is_empty
    ]


def _rounded_ring(ring: list[list[float]]) -> list[list[float]]:
    return [[round(float(lon), DIGITS), round(float(lat), DIGITS)] for lon, lat in ring]


def _box(ring: list[list[float]]) -> dict[str, float] | None:
    """The record box of an axis-aligned rectangle, or None for any other ring."""
    corners = {tuple(p) for p in ring}
    lons, lats = {p[0] for p in corners}, {p[1] for p in corners}
    if len(corners) != 4 or len(lons) != 2 or len(lats) != 2:
        return None
    west, east = min(lons), max(lons)
    width = min(round(east - west, DIGITS), 360.0)
    west = -180.0 if width == 360.0 else round((west + 180.0) % 360.0 - 180.0, DIGITS)
    return {"west": west, "width": width, "south": min(lats), "north": max(lats)}


def _written(geometry: shapely.Geometry) -> dict[str, Any]:
    """A geometry as Rule.to_feature writes it: edges no longer than 180 degrees,
    so a reader cannot take them the short way round, then normalised."""
    geometry = shapely.segmentize(geometry, 180.0)
    return _mapping(shapely.orient_polygons(shapely.normalize(geometry)))


def _joined(geometry: shapely.Geometry) -> shapely.Geometry:
    """Rejoin the pieces of a shape that queryearth split at ±180."""
    parts = list(getattr(geometry, "geoms", [geometry]))
    bounds = [p.bounds for p in parts]
    east = any(b[2] >= _EDGE and b[0] > -_EDGE for b in bounds)
    if not east:
        return geometry
    shifted = [
        shapely.affinity.translate(p, 360.0) if b[0] <= -_EDGE and b[2] < _EDGE else p
        for p, b in zip(parts, bounds)
    ]
    return shapely.union_all(shifted)


def _mapping(geometry: shapely.Geometry) -> dict[str, Any]:
    """GeoJSON for a geometry, with coordinates rounded to six decimals."""

    def rounded(value: Any) -> Any:
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], float):
            return [round(v, 6) + 0.0 for v in value]
        if isinstance(value, (list, tuple)):
            return [rounded(v) for v in value]
        return value

    mapping = shapely.geometry.mapping(geometry)
    return {"type": mapping["type"], "coordinates": rounded(mapping["coordinates"])}
