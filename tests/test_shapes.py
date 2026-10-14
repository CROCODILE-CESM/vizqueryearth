"""vizqueryearth.shapes: drawn GeoJSON to queryearth shapes and back."""

import random

import pytest
from queryearth import space as sp

from vizqueryearth import Shape, antarctic, arctic, from_leaflet, to_leaflet


def drawn(*rings, kind="polygon"):
    """The drawing layer's data, as Leaflet-Geoman sends it."""
    return [
        {
            "type": "Feature",
            "properties": {"type": kind, "style": {}},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }
        for ring in rings
    ]


def rectangle(west, south, east, north):
    return [[west, south], [west, north], [east, north], [east, south], [west, south]]


def test_an_empty_layer_has_no_shape():
    assert from_leaflet([]) is None


def test_a_rectangle_becomes_a_box():
    shape = from_leaflet(drawn(rectangle(-98, 18, -80, 31), kind="rectangle"))
    assert shape.box == {"west": -98, "width": 18, "south": 18, "north": 31}
    assert shape.geometry is None


def test_a_rectangle_across_the_date_line_is_one_box():
    # Leaflet keeps longitudes continuous: 165E to 160W arrives as 165 to 200
    shape = from_leaflet(drawn(rectangle(165, 52, 200, 66)))
    assert shape.box == {"west": 165, "width": 35, "south": 52, "north": 66}
    assert sp.meets(shape.space, sp.point(-170, 60))
    assert not sp.meets(shape.space, sp.point(0, 60))


def test_a_drawing_on_a_world_copy_lands_in_the_same_place():
    assert from_leaflet(drawn(rectangle(525, 52, 560, 66))) == from_leaflet(
        drawn(rectangle(165, 52, 200, 66))
    )
    once = from_leaflet(drawn([[10, 0], [20, 0], [15, 10], [10, 0]]))
    assert from_leaflet(drawn([[-350, 0], [-340, 0], [-345, 10], [-350, 0]])) == once


def test_a_polygon_across_the_date_line_is_split_in_the_file():
    shape = from_leaflet(drawn([[170, 50], [200, 55], [190, 65], [170, 50]]))
    assert shape.geometry["type"] == "MultiPolygon"
    west, east = (
        sp.polygon({"type": "Polygon", "coordinates": p}).geometry.bounds
        for p in shape.geometry["coordinates"]
    )
    assert (west[0], west[2]) == (-180, -160) and (east[0], east[2]) == (170, 180)


def test_the_map_shows_a_split_shape_as_one():
    shape = from_leaflet(drawn([[170, 50], [200, 55], [190, 65], [170, 50]]))
    features = to_leaflet(shape)
    assert len(features) == 1
    lons = [p[0] for p in features[0]["geometry"]["coordinates"][0]]
    assert min(lons) == 170 and max(lons) == 200


def test_several_shapes_make_one_geometry():
    shape = from_leaflet(drawn(rectangle(0, 0, 10, 10), rectangle(20, 0, 30, 10)))
    assert shape.box is None and shape.geometry["type"] == "MultiPolygon"
    assert len(to_leaflet(shape)) == 2


def test_a_rotated_or_irregular_quad_stays_a_polygon():
    shape = from_leaflet(drawn([[0, 0], [10, 1], [10, 10], [0, 10], [0, 0]]))
    assert shape.box is None and shape.geometry["type"] == "Polygon"


def test_coordinates_are_rounded_to_six_decimals():
    shape = from_leaflet(
        drawn([[0.123456789, 0], [10, 0], [5, 9.87654321], [0.123456789, 0]])
    )
    lons = {p[0] for p in shape.geometry["coordinates"][0]}
    lats = {p[1] for p in shape.geometry["coordinates"][0]}
    assert 0.123457 in lons and 9.876543 in lats


def test_round_trips_through_the_map_change_nothing():
    random.seed(1)
    for _ in range(200):
        lon, lat = random.uniform(-200, 200), random.uniform(-70, 70)
        ring = [
            [lon + random.uniform(-40, 40), lat + random.uniform(-10, 10)]
            for _ in range(random.choice([3, 4, 6]))
        ]
        try:
            shape = from_leaflet(drawn(ring + ring[:1]))
        except ValueError:
            continue  # a ring queryearth refuses
        assert from_leaflet(to_leaflet(shape)) == shape


def test_polar_caps_are_boxes_beyond_the_map():
    cap = arctic(70)
    assert cap.box == {"west": -180, "width": 360, "south": 70, "north": 90}
    assert sp.meets(cap.space, sp.point(123, 90))
    (shown,) = to_leaflet(cap)
    lats = {p[1] for p in shown["geometry"]["coordinates"][0]}
    assert max(lats) == pytest.approx(85.0511)
    assert antarctic(-60).box["south"] == -90


def test_drawing_to_the_map_edge_reaches_the_pole():
    shape = from_leaflet(drawn(rectangle(-180, 66.5, 180, 85.0511)))
    assert shape == arctic(66.5)
    south = from_leaflet(drawn(rectangle(-180, -85.0511, 180, -60)))
    assert south == antarctic(-60)
    peak = from_leaflet(drawn([[0, 80], [10, 85.04], [20, 80], [0, 80]]))
    assert max(p[1] for p in peak.geometry["coordinates"][0]) == 90
    assert from_leaflet(to_leaflet(arctic(70))) == arctic(70)


def test_whole_numbers_are_written_as_integers():
    box = from_leaflet(drawn(rectangle(165.0, 52.0, 200.0, 66.0))).box
    assert all(type(v) is int for v in box.values())


def test_a_full_width_band_is_not_shifted():
    band = Shape(
        geometry={"type": "Polygon", "coordinates": [rectangle(-180, -10, 180, 10)]}
    )
    (shown,) = to_leaflet(band)
    lons = [p[0] for p in shown["geometry"]["coordinates"][0]]
    assert min(lons) == -180 and max(lons) == 180


def test_a_shape_queryearth_refuses_is_an_error():
    with pytest.raises(ValueError):
        Shape(box={"west": 0, "width": 0, "south": 0, "north": 10})
    with pytest.raises(ValueError):
        Shape()
