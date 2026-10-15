"""Shapes drawn on the globe, and what the globe shows of a rule's space.

The drawing tool gives longitudes from -180 to 180, so a shape drawn across the
date line has an edge that jumps, for example from 170 to -170. queryearth takes
every edge the short way round and splits the shape at ±180, so a drawing goes
to queryearth as it is, and queryearth decides what the shape is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import shapely
from queryearth import space as sp

DIGITS = 6  # decimals kept of a drawn point, about 0.1 m
POLE = 89.5  # a point drawn this close to a pole is taken to be on it
_SEAMS = shapely.MultiLineString(
    [[(-180, -90), (-180, 90)], [(180, -90), (180, 90)]]
    + [[(-180, 90), (180, 90)], [(-180, -90), (180, -90)]]
).buffer(1e-7)


def drawn(features: Iterable[Mapping[str, Any]]) -> sp.Space | None:
    """The space of everything drawn, the union of its polygons, or None when
    nothing is. Points are rounded, and those next to a pole taken to it."""
    polygons = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "Polygon":
            polygons.append(geometry["coordinates"])
        elif geometry.get("type") == "MultiPolygon":
            polygons.extend(geometry["coordinates"])
    if not polygons:
        return None
    rounded = [[[_point(p) for p in ring] for ring in poly] for poly in polygons]
    return sp.polygon({"type": "MultiPolygon", "coordinates": rounded})


def cap(pole: str, latitude: float) -> sp.Space:
    """Everything poleward of a latitude, around the "north" or "south" pole."""
    if pole == "north":
        return sp.box(-180, latitude, 180, 90)
    return sp.box(-180, -90, 180, latitude)


def on_globe(space: sp.Space) -> dict[str, Any]:
    """What the globe shows of a rule's space: its fill; its outline, without
    the cuts at ±180 and the edges along a pole, which are not edges on a
    globe; where its label goes; the polygons whose corners can be moved, or
    None when it has holes, crosses ±180 or reaches a pole; and its extent."""
    geometry = space.geometry
    parts = list(getattr(geometry, "geoms", [geometry]))
    lines = shapely.difference(shapely.boundary(geometry), _SEAMS)
    simple = not any(p.interiors or p.intersects(_SEAMS) for p in parts)
    label = max(parts, key=lambda p: p.area).point_on_surface()
    return {
        "fill": space.to_json(),
        "outline": None if lines.is_empty else shapely.geometry.mapping(lines),
        "label": [label.x, label.y],
        "editable": [shapely.geometry.mapping(p) for p in parts] if simple else None,
        "extent": extent([space]),
    }


def extent(spaces: Iterable[sp.Space]) -> list[float] | None:
    """[west, south, east, north] around spaces, or None when there are none.

    Longitudes go the short way round, so east is past 180 when the spaces
    cross the date line: [165, 52, 200, 66] for the Bering Sea. A part that goes
    all the way round, such as a polar cap, counts only for latitude, unless no
    other part does; the extent is then [-180, south, 180, north].
    """
    spans, round_the_world = [], False
    south, north = 90.0, -90.0
    for space in spaces:
        for part in getattr(space.geometry, "geoms", [space.geometry]):
            w, s, e, n = part.bounds
            south, north = min(south, s), max(north, n)
            if e - w >= 360 - 1e-9:
                round_the_world = True
            else:
                spans.append((w, e))
    if not spans:
        return [-180, south, 180, north] if round_the_world else None
    spans.sort()
    gap, west, reach = 0.0, spans[0][0], spans[0][1]
    for w, e in spans[1:] + [(spans[0][0] + 360, reach)]:
        if w - reach > gap:  # the widest stretch of longitude without a part
            gap, west = w - reach, w
        reach = max(reach, e)
    west = (west + 180) % 360 - 180
    return [west, south, west + 360 - gap, north]


def _point(point: list[float]) -> list[float]:
    """A drawn point rounded to DIGITS decimals, on the pole when next to it."""
    lon, lat = (round(float(v), DIGITS) + 0.0 for v in point[:2])  # no -0.0
    return [lon, 90.0 if lat >= POLE else -90.0 if lat <= -POLE else lat]
