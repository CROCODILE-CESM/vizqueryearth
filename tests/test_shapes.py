"""vizqueryearth.shapes: drawn GeoJSON to queryearth shapes, and shapes to the globe."""

import random

import pytest
from queryearth import space as sp

from vizqueryearth import Shape, antarctic, arctic, from_drawn
from vizqueryearth.shapes import editable, fill, label_point, outline

BERING = {"west": 165, "width": 35, "south": 52, "north": 66}  # across the date line


def drawn(*rings):
    """What the drawing tool gives: longitudes from -180 to 180."""
    return [
        {
            "type": "Feature",
            "properties": {"mode": "polygon"},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }
        for ring in rings
    ]


def rectangle(west, south, east, north):
    return [[west, south], [west, north], [east, north], [east, south], [west, south]]


def features(geometries):
    return [{"type": "Feature", "properties": {}, "geometry": g} for g in geometries]


def test_an_empty_drawing_has_no_shape():
    assert from_drawn([]) is None
    assert from_drawn([{"type": "Feature", "geometry": None}]) is None


def test_a_rectangle_becomes_a_box():
    shape = from_drawn(drawn(rectangle(-98, 18, -80, 31)))
    assert shape.box == {"west": -98, "width": 18, "south": 18, "north": 31}
    assert shape.geometry is None


def test_a_rectangle_across_the_date_line_is_one_box():
    # drawn from 165E to 160W, the tool gives 165 and -160
    shape = from_drawn(drawn(rectangle(165, 52, -160, 66)))
    assert shape.box == BERING
    assert sp.meets(shape.space, sp.point(-170, 60))
    assert not sp.meets(shape.space, sp.point(0, 60))


@pytest.mark.parametrize(
    "west, east, box_west, width",
    [
        (170, -170, 170, 20),  # across the date line, drawn either way round
        (-170, 170, 170, 20),
        (-100, 100, 100, 160),  # 200 degrees one way is 160 the other
        (0, 180, 0, 180),  # exactly half way round: from the western corner
    ],
)
def test_a_rectangle_spans_the_short_way_round(west, east, box_west, width):
    box = from_drawn(drawn(rectangle(west, 0, east, 10))).box
    assert (box["west"], box["width"]) == (box_west, width)


def test_a_polygon_across_the_date_line_is_split_in_the_file():
    shape = from_drawn(drawn([[170, 50], [-160, 55], [-170, 65], [170, 50]]))
    assert shape.geometry["type"] == "MultiPolygon"
    west, east = sorted(
        sp.polygon({"type": "Polygon", "coordinates": p}).geometry.bounds
        for p in shape.geometry["coordinates"]
    )
    assert (west[0], west[2]) == (-180, -160) and (east[0], east[2]) == (170, 180)


def test_several_shapes_make_one_geometry():
    shape = from_drawn(drawn(rectangle(0, 0, 10, 10), rectangle(20, 0, 30, 10)))
    assert shape.box is None and shape.geometry["type"] == "MultiPolygon"
    assert len(editable(shape)) == 2


def test_a_rotated_or_irregular_quad_stays_a_polygon():
    shape = from_drawn(drawn([[0, 0], [10, 1], [10, 10], [0, 10], [0, 0]]))
    assert shape.box is None and shape.geometry["type"] == "Polygon"


def test_coordinates_are_rounded_to_six_decimals():
    shape = from_drawn(
        drawn([[0.123456789, 0], [10, 0], [5, 9.87654321], [0.123456789, 0]])
    )
    lons = {p[0] for p in shape.geometry["coordinates"][0]}
    lats = {p[1] for p in shape.geometry["coordinates"][0]}
    assert 0.123457 in lons and 9.876543 in lats


def test_whole_numbers_are_written_as_integers():
    box = from_drawn(drawn(rectangle(165.0, 52.0, -160.0, 66.0))).box
    assert all(type(v) is int for v in box.values())


def test_a_point_drawn_next_to_a_pole_is_on_it():
    assert from_drawn(drawn(rectangle(0, 70, 20, 89.7))).box["north"] == 90
    assert from_drawn(drawn(rectangle(0, -89.6, 20, -70))).box["south"] == -90
    assert from_drawn(drawn(rectangle(0, 70, 20, 89.4))).box["north"] == 89.4
    peak = from_drawn(drawn([[0, 80], [10, 89.6], [20, 80], [0, 80]]))
    assert max(p[1] for p in peak.geometry["coordinates"][0]) == 90


def test_polar_caps_are_full_width_boxes():
    cap = arctic(70)
    assert cap.box == {"west": -180, "width": 360, "south": 70, "north": 90}
    assert sp.meets(cap.space, sp.point(123, 90))
    south = antarctic(-60).box
    assert (south["width"], south["south"], south["north"]) == (360, -90, -60)


def test_the_fill_is_split_at_the_date_line():
    assert fill(Shape(box=BERING))["type"] == "MultiPolygon"
    plain = from_drawn(drawn(rectangle(10, 0, 20, 10)))
    assert fill(plain) == {
        "type": "Polygon",
        "coordinates": [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]],
    }


def test_the_outline_leaves_out_the_date_line_and_the_poles():
    lines = outline(Shape(box=BERING))["coordinates"]
    assert len(lines) == 2  # one open line on each side of the date line
    for line in lines:
        assert abs(line[0][0]) == 180 and abs(line[-1][0]) == 180
        assert all(abs(p[0]) < 180 for p in line[1:-1])
    assert outline(arctic(70)) == {
        "type": "LineString",
        "coordinates": [[-180, 70], [180, 70]],
    }
    band = Shape(
        geometry={"type": "Polygon", "coordinates": [rectangle(-180, -10, 180, 10)]}
    )
    lats = {p[1] for line in outline(band)["coordinates"] for p in line}
    assert lats == {-10, 10}


def test_only_simple_shapes_are_edited_corner_by_corner():
    plain = from_drawn(drawn(rectangle(10, 0, 20, 10)))
    assert editable(plain) == [fill(plain)]
    assert editable(Shape(box=BERING)) is None  # crosses the date line
    assert editable(arctic(70)) is None  # reaches the pole
    across = from_drawn(drawn([[170, 50], [-160, 55], [-170, 65], [170, 50]]))
    assert editable(across) is None
    holed = Shape(
        geometry={
            "type": "Polygon",
            "coordinates": [rectangle(0, 0, 20, 20), rectangle(5, 5, 10, 10)[::-1]],
        }
    )
    assert editable(holed) is None


def test_the_label_is_inside_the_largest_part():
    lon, lat = label_point(Shape(box=BERING))
    assert -180 < lon < -160 and 52 < lat < 66  # the western part is wider
    assert label_point(arctic(70))[1] > 70


def test_corner_edits_round_trip_unchanged():
    random.seed(1)
    tried = 0
    for _ in range(200):
        lon, lat = random.uniform(-180, 180), random.uniform(-70, 70)
        ring = [
            [
                (lon + random.uniform(-40, 40) + 180) % 360 - 180,
                lat + random.uniform(-10, 10),
            ]
            for _ in range(random.choice([3, 4, 6]))
        ]
        try:
            shape = from_drawn(drawn(ring + ring[:1]))
        except ValueError:
            continue  # a ring queryearth refuses
        parts = editable(shape)
        if parts is None:
            continue  # crosses the date line: redrawn, not edited
        tried += 1
        assert from_drawn(features(parts)) == shape
    assert tried > 100
    box = from_drawn(drawn(rectangle(-60.5, -30.25, -10, 5)))
    assert from_drawn(features(editable(box))) == box


def test_a_shape_comes_from_a_record():
    box = {"west": 0, "width": 10, "south": 0, "north": 10}
    assert Shape.of({"geometry": None, "properties": {"box": box}}) == Shape(box=box)
    geometry = {"type": "Polygon", "coordinates": [rectangle(0, 0, 10, 10)]}
    assert Shape.of({"geometry": geometry, "properties": {}}).geometry == geometry
    assert Shape.of({"geometry": None, "properties": {}}) is None


def test_a_shape_queryearth_refuses_is_an_error():
    with pytest.raises(ValueError):
        Shape(box={"west": 0, "width": 0, "south": 0, "north": 10})
    with pytest.raises(ValueError):
        Shape()
    with pytest.raises(ValueError):
        Shape(
            geometry={"type": "Polygon", "coordinates": [rectangle(0, 0, 1, 1)]},
            box={"west": 0, "width": 1, "south": 0, "north": 1},
        )
