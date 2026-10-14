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
    ed = vq.Editor(path)
    assert ed.rules == ["DEMO001", "DEMO002", "DEMO003", "DEMO004"]
    assert ed._code.value == "DEMO001"
    assert ed._facet_inputs["product"].value == ["demo_ocean"]
    assert "demo_ocean" in ed._facet_inputs["product"].allowed_tags
    assert len(ed.control.data) == 1  # its shape is on the drawing layer


def test_saving_without_changes_rewrites_the_same_bytes(path):
    before = path.read_bytes()
    ed = vq.Editor(path)
    ed.select("DEMO003")
    ed.save()
    assert path.read_bytes() == before


def test_a_polar_cap_stays_off_the_drawing_layer(path):
    ed = vq.Editor(path)
    ed.select("DEMO003")
    assert ed.control.data == [] and ed._fixed.data["features"]


def test_redrawing_a_shape_changes_only_that_rule(path):
    ed = vq.Editor(path)
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
    assert qe.Registry("check").load(path) == ed.rules


def test_a_drawn_polygon_replaces_a_box(path):
    ed = vq.Editor(path)
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
    ed = vq.Editor(path)
    ed.add("DEMO005", title="A new rule", message="Drawn in the editor.")
    ed.control.data = [rectangle(-10, 40, 5, 50)]
    ed._facet_inputs["product"].value = ["demo_ocean"]
    ed.save()
    registry = qe.Registry("check")
    assert registry.load(path)[-1] == "DEMO005"
    found = registry.query(
        space=qe.space.point(0, 45), facets={"product": "demo_ocean"}
    )
    assert "DEMO005" in [f.code for f in found]


def test_a_new_rule_from_the_form(path):
    ed = vq.Editor(path)
    ed.new()
    ed._code.value, ed._title.value, ed._message.value = "DEMO006", "T", "M"
    ed.set_shape(vq.arctic(80))
    assert ed.apply() == "DEMO006"
    assert ed.features[-1]["id"] == "DEMO006"
    assert ed.features[-1]["properties"]["box"]["south"] == 80


def test_a_duplicate_code_is_refused(path):
    ed = vq.Editor(path)
    ed.select("DEMO002")
    ed._code.value = "DEMO001"
    with pytest.raises(ValueError, match="already in the file"):
        ed.apply()
    with pytest.raises(ValueError):
        ed.add("DEMO001")


def test_queryearth_refuses_a_bad_rule_and_nothing_is_written(path):
    before = path.read_bytes()
    ed = vq.Editor(path)
    ed.select("DEMO001")
    ed._kind.value = "suggestion"  # a suggestion needs suggestions
    with pytest.raises(ValueError, match="suggestion"):
        ed.save()
    assert path.read_bytes() == before
    assert "suggestion" in ed.status.value


def test_undeclared_names_are_found_when_saving(path):
    ed = vq.Editor(path, facets=["product", "variable"])  # the file also uses "model"
    with pytest.raises(qe.LoadError) as err:
        ed.save()
    assert any("model" in p for p in err.value.problems)


def test_vocabulary_adds_values_to_offer(path):
    ed = vq.Editor(path, vocabulary={"product": ["demo_atmos"]})
    assert "demo_atmos" in ed._facet_inputs["product"].allowed_tags
    ed._new_facet.value, ed._new_value.value = "variable", "uo"
    ed._add_value()
    assert "uo" in ed._facet_inputs["variable"].allowed_tags


def test_removing_the_shape_makes_a_rule_global(path):
    ed = vq.Editor(path)
    ed.select("DEMO001")
    ed.control.data = []  # everything removed on the map
    ed.apply()
    assert ed.features[0]["geometry"] is None


def test_a_new_file_is_created_on_save(tmp_path):
    path = tmp_path / "new.geojson"
    ed = vq.Editor(path)
    assert ed.rules == []
    ed.add("NEW001", title="T", message="M")
    ed.save()
    assert qe.Registry("check").load(path) == ["NEW001"]
