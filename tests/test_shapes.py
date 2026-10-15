"""Shapes drawn on the globe, and what the globe shows of them."""

from queryearth import space as sp

from vizqueryearth import shapes


def polygon(*ring):
    return {"geometry": {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}}


def test_nothing_drawn_is_no_shape():
    assert shapes.drawn([]) is None


def test_a_rectangle_drawn_across_the_date_line_is_split_there():
    space = shapes.drawn([polygon([170, 50], [-170, 50], [-170, 60], [170, 60])])
    assert space.to_json()["type"] == "MultiPolygon"
    assert shapes.extent([space]) == [170, 50, 190, 60]


def test_drawn_points_are_rounded_and_next_to_a_pole_on_it():
    space = shapes.drawn([polygon([0.1234567, 80], [10, 80], [10, 89.7])])
    assert space.geometry.bounds == (0.123457, 80, 10, 90)


def test_the_outline_leaves_out_the_date_line_and_the_poles():
    arctic = shapes.on_globe(shapes.cap("north", 66.5))
    assert arctic["outline"]["type"] == "LineString"  # only the edge at 66.5
    assert {lat for _, lat in arctic["outline"]["coordinates"]} == {66.5}


def test_only_simple_shapes_have_corners_to_move():
    assert shapes.on_globe(sp.box(-10, 0, 10, 20))["editable"] is not None
    assert shapes.on_globe(sp.box(170, 0, -170, 20))["editable"] is None
    assert shapes.on_globe(shapes.cap("south", -60))["editable"] is None


def test_the_label_is_inside_the_largest_part():
    space = sp.polygon(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                [[[20, 0], [40, 0], [40, 20], [20, 20], [20, 0]]],
            ],
        }
    )
    lon, lat = shapes.on_globe(space)["label"]
    assert 20 < lon < 40 and 0 < lat < 20


def test_the_extent_of_a_polar_cap_goes_all_the_way_round():
    assert shapes.extent([shapes.cap("south", -60)]) == [-180, -90, 180, -60]
