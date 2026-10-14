"""vizqueryearth.RuleFile: a rule file edited one rule at a time, checked by queryearth."""

import copy
import json
from pathlib import Path
from unittest import mock

import pytest
import queryearth as qe
from queryearth import space as sp

from vizqueryearth import RuleFile, arctic, from_drawn, guess_dimensions

DEMO = Path(__file__).parent.parent / "web" / "sites" / "demo" / "rules.geojson"
DIMENSIONS = [qe.Labels("product"), qe.Labels("variable"), qe.Labels("model")]
LABELS = [{"name": n, "kind": "labels"} for n in ("product", "variable", "model")]
CODES = ["DEMO001", "DEMO002", "DEMO003", "DEMO004"]


def demo():
    return RuleFile.read(DEMO, dimensions=DIMENSIONS)


def rule(code, **properties):
    """A record without a shape."""
    return {
        "type": "Feature",
        "id": code,
        "geometry": None,
        "time": None,
        "properties": {"code": code, "title": "T", "message": "M"} | properties,
    }


def rules(*features, **kwargs):
    return RuleFile({"type": "FeatureCollection", "features": list(features)}, **kwargs)


# ---- reading and writing --------------------------------------------------------
def test_reading_and_writing_back_changes_nothing(tmp_path):
    text = DEMO.read_text()
    assert demo().codes == CODES
    assert demo().text() == text
    assert RuleFile.from_text(text, dimensions=DIMENSIONS).text() == text
    path = tmp_path / "rules.geojson"
    demo().write(path)
    assert path.read_text() == text


def test_rules_not_edited_are_written_back_as_read():
    file = demo()
    file.update(1, title="Changed")
    after = json.loads(file.text())["features"]
    before = json.loads(DEMO.read_text())["features"]
    assert after[1]["properties"]["title"] == "Changed"
    assert after[0] == before[0] and after[2:] == before[2:]


def test_a_missing_file_reads_as_an_empty_one(tmp_path):
    file = RuleFile.read(tmp_path / "new.geojson")
    assert file.codes == [] and file.problems() == []


def test_only_a_feature_collection_is_a_rule_file():
    with pytest.raises(ValueError, match="FeatureCollection"):
        RuleFile({"type": "Feature", "properties": {}})


def test_write_replaces_the_file_in_one_step(tmp_path):
    path = tmp_path / "rules.geojson"
    path.write_text(DEMO.read_text())
    file = demo()
    file.new()
    with mock.patch("vizqueryearth.rulefile.os.replace", side_effect=OSError):
        with pytest.raises(OSError):
            file.write(path)
    assert path.read_text() == DEMO.read_text()  # untouched until the last step
    file.write(path)
    assert RuleFile.read(path, dimensions=DIMENSIONS).codes == CODES + ["DEMO005"]
    assert [p.name for p in tmp_path.iterdir()] == ["rules.geojson"]


def test_write_refuses_a_file_with_problems(tmp_path):
    path = tmp_path / "rules.geojson"
    path.write_text(DEMO.read_text())
    file = RuleFile.read(path, dimensions=[])  # what the rules use is not declared
    with pytest.raises(qe.LoadError):
        file.write(path)
    assert path.read_text() == DEMO.read_text()
    assert [p.name for p in tmp_path.iterdir()] == ["rules.geojson"]


# ---- adding rules ---------------------------------------------------------------
def test_new_adds_the_next_free_code():
    file = demo()
    index = file.new()
    assert index == 4 and file.codes[index] == "DEMO005"
    assert file.features[index]["id"] == "DEMO005" and file.problem(index) is None
    file.new()
    assert file.codes[-1] == "DEMO006"
    empty = RuleFile()
    empty.new()
    assert empty.codes == ["RULE001"]


@pytest.mark.parametrize(
    "codes, expected",
    [
        (["CRU001", "CRU009"], "CRU010"),
        (["ERA5-014"], "ERA5-015"),
        (["CRU001", "NWM0003"], "NWM0004"),
    ],
)
def test_the_next_code_follows_the_file(codes, expected):
    file = rules(*(rule(code) for code in codes))
    file.new()
    assert file.codes[-1] == expected


def test_add_checks_the_rule_with_queryearth():
    file = demo()
    index = file.add(
        "DEMO010", "Added", "From Python.", dimensions={"product": ["demo_ocean"]}
    )
    assert file.features[index]["properties"] == {
        "code": "DEMO010",
        "title": "Added",
        "message": "From Python.",
        "dimensions": {"product": ["demo_ocean"]},
    }
    with pytest.raises(ValueError, match="already in the file"):
        file.add("DEMO001")
    with pytest.raises(ValueError, match="rule code"):
        file.add("not a code")
    with pytest.raises(qe.UnknownNameError):
        file.add("DEMO011", dimensions={"resolution": {"lt": 10}})
    assert len(file.features) == 5


# ---- editing rules --------------------------------------------------------------
def test_update_changes_the_fields_and_the_id_follows_the_code():
    file = demo()
    file.update(1, code=" DEMO020 ", level="error", title="T2", message="M2")
    feature = file.features[1]
    props = feature["properties"]
    assert (props["code"], props["level"], props["title"], props["message"]) == (
        "DEMO020",
        "error",
        "T2",
        "M2",
    )
    assert feature["id"] == "DEMO020" and file.level(1) == "error"
    file.update(1, level="")  # back to the default
    assert "level" not in file.features[1]["properties"]
    assert file.level(1) == "warning"


def test_an_id_that_is_not_the_code_is_kept():
    file = rules(rule("ABC001") | {"id": "first"})
    file.update(0, code="ABC002")
    assert file.features[0]["id"] == "first"


def test_a_refused_update_leaves_the_rule_as_it_was():
    file = demo()
    before = copy.deepcopy(file.features[1])
    with pytest.raises(ValueError, match="already in the file"):
        file.update(1, code="DEMO001")
    with pytest.raises(ValueError, match="are edited here"):
        file.update(1, box={})
    with pytest.raises(ValueError, match="rule code"):
        file.update(1, code="not a code")
    with pytest.raises(ValueError, match="level"):
        file.update(1, level="loud")
    assert file.features[1] == before


def test_time_replaces_the_rules_time_and_months_repeat_every_year():
    file = rules(
        rule("TIM001", time_start="2000-01-01", time_end="2001-01-01"),
        rule("TIM002", periods=[["2000-01-01", "2000-03-31"]])
        | {"time": {"interval": ["2000-01-01", "2001-12-31"]}},
    )
    file.update(0, time=["1990-01-01", ""])
    assert file.features[0]["time"] == {"interval": ["1990-01-01", ".."]}
    assert {"time_start", "time_end"}.isdisjoint(file.features[0]["properties"])
    file.update(1, months=[12, 1, 2])  # months alone keep the periods
    props = file.features[1]["properties"]
    assert props["recurrence"] == {"months": [12, 1, 2]} and "periods" in props
    file.update(1, time=[None, ""])  # always
    props = file.features[1]["properties"]
    assert file.features[1]["time"] is None and "periods" not in props
    assert props["recurrence"] == {"months": [12, 1, 2]}
    file.update(1, months=[])
    assert "recurrence" not in file.features[1]["properties"]
    before = copy.deepcopy(file.features)
    with pytest.raises(ValueError, match="out of order"):
        file.update(0, time=["2001-01-01", "2000-01-01"])
    with pytest.raises(ValueError, match="months"):
        file.update(0, months=[13])
    assert file.features == before


def test_dimensions_are_set_one_name_at_a_time():
    file = demo()
    file.update(0, dimensions={"variable": None, "model": ["demo_model"]})
    assert file.features[0]["properties"]["dimensions"] == {
        "product": ["demo_ocean"],
        "model": ["demo_model"],
    }
    file.update(0, dimensions={"product": [], "model": ""})
    assert "dimensions" not in file.features[0]["properties"]
    with pytest.raises(qe.UnknownNameError):
        file.update(0, dimensions={"resolution": {"lt": 10}})


def test_changes_make_the_default_level_info():
    file = demo()
    change = {"target": "MOM_input", "key": "DT", "value": 900, "rationale": "stable"}
    file.update(0, changes=[change])
    assert file.features[0]["properties"]["changes"] == [change]
    assert file.level(0) == "info"
    with pytest.raises(ValueError, match="target"):
        file.update(0, changes=[change | {"target": ""}])
    file.update(0, changes=[])
    assert "changes" not in file.features[0]["properties"]
    assert file.level(0) == "warning"


def test_set_shape_writes_a_box_or_a_geometry():
    file = demo()
    file.set_shape(0, arctic(70))  # DEMO001 had a geometry
    assert file.features[0]["geometry"] is None
    assert file.features[0]["properties"]["box"] == arctic(70).box
    assert file.shape(0) == arctic(70)
    ring = [[170, 50], [-160, 55], [-170, 65], [170, 50]]
    drawn = from_drawn(
        [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}}]
    )
    file.set_shape(1, drawn)  # DEMO002 had a box
    assert "box" not in file.features[1]["properties"]
    assert file.features[1]["geometry"] == drawn.geometry
    file.set_shape(1, None)
    assert file.features[1]["geometry"] is None
    assert "box" not in file.features[1]["properties"] and file.shape(1) is None
    assert file.problems() == []


def test_delete_removes_a_rule():
    file = demo()
    file.delete(1)
    assert file.codes == ["DEMO001", "DEMO003", "DEMO004"]


# ---- what queryearth says -------------------------------------------------------
def test_problems_name_what_queryearth_refuses():
    file = RuleFile.read(DEMO, dimensions=DIMENSIONS[:2])  # leaves out model
    (problem,) = file.problems()
    assert "DEMO003" in problem and "model" in problem
    assert "model" in file.problem(2) and file.problem(0) is None
    with pytest.raises(qe.LoadError):
        file.text()
    bad = rules(rule("BAD001", box={"west": 0, "width": 0, "south": 0, "north": 10}))
    assert "box" in bad.problem(0) and bad.shape(0) is None


def test_the_level_defaults_to_warning_or_info_with_changes():
    change = {"target": "MOM_input", "key": "DT", "value": 900}
    file = rules(
        rule("LVL001"),
        rule("LVL002", changes=[change]),
        rule("LVL003", level="error"),
        rule("LVL004", level="info"),
    )
    assert [file.level(i) for i in range(4)] == ["warning", "info", "error", "info"]
    assert file.problems() == []


def test_query_leaves_out_rules_queryearth_refuses():
    collection = json.loads(DEMO.read_text())
    collection["features"].append(rule("bad code"))  # would apply anywhere
    file = RuleFile(collection, dimensions=DIMENSIONS)
    assert file.problems()
    found = file.query(
        space=sp.point(-170, 60),
        dimensions={"product": "demo_ocean", "variable": "thetao"},
    )
    assert [f.code for f in found] == ["DEMO002"]


# ---- dimensions -----------------------------------------------------------------
def test_the_file_says_which_dimensions_its_rules_use():
    assert RuleFile.read(DEMO).dimensions == tuple(DIMENSIONS)
    assert RuleFile.read(DEMO).collection["dimensions"] == LABELS
    resolution = qe.Axis("resolution", "km")
    file = RuleFile.read(DEMO, dimensions=[resolution])  # the argument wins
    assert file.dimensions == (resolution,)
    assert file.collection["dimensions"] == [
        {"name": "resolution", "kind": "axis", "unit": "km"}
    ]
    bare = rules(rule("ABC001"))  # a file without the member gets one
    assert list(json.loads(bare.text())) == ["type", "dimensions", "features"]
    assert json.loads(bare.text())["dimensions"] == []
    # what queryearth reads from the file is what the file says
    assert qe.Registry.from_file(DEMO).describe()["dimensions"] == LABELS


def test_dimensions_are_given_as_objects_or_as_the_file_writes_them():
    spec = [
        {"name": "resolution", "kind": "axis", "unit": "km"},
        {"name": "product", "kind": "labels", "description": "a data product"},
        {"name": "version", "kind": "versions"},
    ]
    file = rules(dimensions=spec)
    assert [type(d) for d in file.dimensions] == [qe.Axis, qe.Labels, qe.Versions]
    assert file.collection["dimensions"] == spec
    file.set_dimensions([qe.Axis("resolution", "km")])
    assert file.collection["dimensions"] == spec[:1]
    for bad in (
        "product",
        [{"name": "depth", "kind": "axis"}],  # an axis needs a unit
        [{"name": "product", "kind": "labels", "unit": "km"}],
        [{"name": "colour", "kind": "colours"}],
        [qe.Labels("space")],
        [qe.Labels("product"), qe.Labels("product")],
    ):
        with pytest.raises(ValueError):
            file.set_dimensions(bad)
    assert file.collection["dimensions"] == spec[:1]


def test_set_dimensions_follows_into_the_file():
    file = demo()
    file.set_dimensions(DIMENSIONS + [qe.Axis("resolution", "km")])
    assert json.loads(file.text())["dimensions"][-1] == {
        "name": "resolution",
        "kind": "axis",
        "unit": "km",
    }
    file.set_dimensions(DIMENSIONS[:2])  # model is still used by DEMO003
    assert any("model" in p for p in file.problems())
    assert file.dimensions == tuple(DIMENSIONS[:2])


def test_dimensions_are_guessed_from_the_rules():
    file = rules(
        rule(
            "GES001",
            dimensions={"resolution": {"lt": 10, "unit": "km"}, "product": ["glorys"]},
        ),
        rule(
            "GES002",
            dimensions={
                "depth": [{"lt": 5}, {"gt": 50}],
                "version": {"introduced": "4.00", "fixed": "4.09"},
            },
        ),
        rule(
            "GES003",
            dimensions={
                "model": {"any_of": ["mom6"], "none_of": ["pop"]},
                "release": [{"versions": ["ERA5T"]}],
            },
        ),
    )
    guessed = guess_dimensions(file.collection)
    assert guessed == [
        {"name": "resolution", "kind": "axis", "unit": "km"},
        {"name": "product", "kind": "labels"},
        {"name": "depth", "kind": "axis", "unit": "unknown"},  # an axis needs one
        {"name": "version", "kind": "versions"},
        {"name": "model", "kind": "labels"},
        {"name": "release", "kind": "versions"},
    ]
    assert RuleFile(file.collection, dimensions=guessed).problems() == []
    assert guess_dimensions(json.loads(DEMO.read_text())) == LABELS
