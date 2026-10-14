"""vizqueryearth.Editor and draw(), driven without a browser.

The browser sends drawings by setting the drawing control's data; these tests
set it the same way.
"""

import json
import shutil
from pathlib import Path

import pytest
import queryearth as qe

import vizqueryearth as vq

EXAMPLE = Path(__file__).parent.parent / "examples" / "demo_rules.geojson"
DIMENSIONS = [qe.Labels("product"), qe.Labels("variable"), qe.Labels("model")]


def rectangle(west, south, east, north):
    ring = [[west, south], [west, north], [east, north], [east, south], [west, south]]
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


@pytest.fixture
def path(tmp_path):
    copy = tmp_path / "rules.geojson"
    shutil.copy(EXAMPLE, copy)
    return copy


def test_draw_reads_the_drawing_layer():
    d = vq.draw()
    assert d.shape is None and d.space is None
    d.control.data = [rectangle(165, 52, 200, 66)]
    assert d.box == {"west": 165, "width": 35, "south": 52, "north": 66}
    assert d.geometry is None
    assert qe.Scope(space=d.space).space is d.space
    d.control.data = []
    assert d.shape is None


def test_opening_shows_the_first_rule(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    assert ed.rules == ["DEMO001", "DEMO002", "DEMO003", "DEMO004"]
    assert ed._code.value == "DEMO001"
    assert ed._title.value.startswith("demo_ocean is too fresh")
    assert len(ed.control.data) == 1  # its shape is on the drawing layer


def test_saving_without_changes_rewrites_the_same_bytes(path):
    before = path.read_bytes()
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.select("DEMO003")
    ed.save()
    assert path.read_bytes() == before


def test_a_polar_cap_is_edited_on_the_map_and_keeps_the_pole(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.select("DEMO003")
    (shown,) = ed.control.data  # cut off at the map's edge
    lats = {p[1] for p in shown["geometry"]["coordinates"][0]}
    assert max(lats) < 86
    ed.control.data = [shown]  # as the browser sends it back after an edit
    ed.apply()
    box = ed.features[2]["properties"]["box"]
    assert box == {"west": -180, "width": 360, "south": 66.5, "north": 90}


def test_redrawing_a_shape_changes_only_that_rule(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.select("DEMO002")
    ed.control.data = [rectangle(160, 50, 205, 65)]  # as the browser would
    ed.apply()
    ed.save()
    after = json.loads(path.read_text())["features"]
    before = json.loads(EXAMPLE.read_text())["features"]
    assert after[1]["properties"]["box"] == {
        "west": 160,
        "width": 45,
        "south": 50,
        "north": 65,
    }
    assert after[0] == before[0] and after[2:] == before[2:]
    assert qe.Registry("check", dimensions=DIMENSIONS).load(path) == ed.rules


def test_a_drawn_polygon_replaces_a_box(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.select("DEMO002")
    ed.control.data = [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[170, 50], [200, 55], [190, 65], [170, 50]]],
            },
        }
    ]
    ed.save()  # applies first
    rule = json.loads(path.read_text())["features"][1]
    assert "box" not in rule["properties"]
    assert rule["geometry"]["type"] == "MultiPolygon"


def test_adding_a_rule_and_drawing_its_shape(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.add(
        "DEMO005",
        title="A new rule",
        message="Drawn in the editor.",
        dimensions={"product": ["demo_ocean"]},
    )
    ed.control.data = [rectangle(-10, 40, 5, 50)]
    ed.save()
    registry = qe.Registry("check", dimensions=DIMENSIONS)
    assert registry.load(path)[-1] == "DEMO005"
    found = registry.query(
        space=qe.space.point(0, 45), dimensions={"product": "demo_ocean"}
    )
    assert "DEMO005" in [f.code for f in found]


def test_new_rule_adds_the_next_code_at_once(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    assert ed.new() == "DEMO005"
    assert ed.rules[-1] == "DEMO005" and ed._code.value == "DEMO005"
    ed._title.value, ed._message.value = "Arctic rule", "North of 80N."
    ed.set_shape(vq.arctic(80))
    ed.save()
    rule = json.loads(path.read_text())["features"][-1]
    assert rule["id"] == "DEMO005" and rule["properties"]["title"] == "Arctic rule"
    assert rule["properties"]["box"]["south"] == 80
    assert ed.new() == "DEMO006"


def test_the_next_code_follows_the_file():
    from vizqueryearth.widgets import _next_code

    assert _next_code([]) == "RULE001"
    assert _next_code(["CRU001", "CRU009"]) == "CRU010"
    assert _next_code(["ERA5-014"]) == "ERA5-015"
    assert _next_code(["CRU001", "NWM0003"]) == "NWM0004"


def test_drawing_with_no_rule_selected_says_what_to_do(tmp_path):
    ed = vq.Editor(tmp_path / "empty.geojson")
    ed.control.data = [rectangle(0, 0, 10, 10)]
    assert "New rule" in ed.status.value
    assert ed.new() == "RULE001"


def test_a_duplicate_code_is_refused(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.select("DEMO002")
    ed._code.value = "DEMO001"
    with pytest.raises(ValueError, match="already in the file"):
        ed.apply()
    with pytest.raises(ValueError):
        ed.add("DEMO001")


def test_queryearth_refuses_a_bad_rule_and_nothing_is_written(path):
    before = path.read_bytes()
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.select("DEMO001")
    ed._code.value = "not a code"  # queryearth refuses the rule
    with pytest.raises(ValueError, match="rule code"):
        ed.save()
    assert path.read_bytes() == before
    assert "rule code" in ed.status.value


def test_undeclared_names_are_found_when_saving(path):
    # the file also uses "model"
    ed = vq.Editor(path, dimensions=[qe.Labels("product"), qe.Labels("variable")])
    with pytest.raises(qe.LoadError) as err:
        ed.save()
    assert any("model" in p for p in err.value.problems)


def test_removing_the_shape_makes_a_rule_global(path):
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    ed.select("DEMO001")
    ed.control.data = []  # everything removed on the map
    ed.apply()
    assert ed.features[0]["geometry"] is None


def test_a_new_file_is_created_on_save(tmp_path):
    path = tmp_path / "new.geojson"
    ed = vq.Editor(path, dimensions=DIMENSIONS)
    assert ed.rules == []
    ed.add("NEW001", title="T", message="M")
    ed.save()
    assert qe.Registry("check").load(path) == ["NEW001"]
