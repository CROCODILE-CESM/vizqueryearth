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
CODES = ["OCN001", "OCN002", "ICE001", "OCN003", "OBC001"]  # in file order
GROUPS = {"OCN": "demo_ocean, the product", "ICE": "Sea ice", "OBC": "Open boundaries"}


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
    assert RuleFile.read(path, dimensions=DIMENSIONS).codes == CODES + ["OCN004"]
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
def test_new_adds_the_next_code_in_a_group():
    file = demo()
    index = file.new()  # the first group
    assert index == 5 and file.codes[index] == "OCN004"
    assert file.features[index]["id"] == "OCN004" and file.problem(index) is None
    file.new("OBC")
    assert file.codes[-1] == "OBC002"
    with pytest.raises(qe.UnknownNameError, match="undeclared group"):
        file.new("XYZ")
    empty = RuleFile()
    empty.new()
    assert empty.codes == ["RULE001"]


def test_numbers_are_not_given_twice():
    # a rule queryearth refuses keeps its number
    file = rules(rule("CRU001"), rule("CRU002", level="loud"))
    assert file.problem(1) is not None
    file.new()
    assert file.codes[-1] == "CRU003"


@pytest.mark.parametrize(
    "codes, expected",
    [
        (["CRU001", "CRU009"], "CRU010"),
        (["ERA5-014"], "ERA5-015"),
        (["CRU001", "NWM0003"], "NWM004"),  # the prefix of the last code
    ],
)
def test_the_next_code_follows_the_file(codes, expected):
    file = rules(*(rule(code) for code in codes))
    file.new()
    assert file.codes[-1] == expected


def test_add_checks_the_rule_with_queryearth():
    file = demo()
    index = file.add(
        "OCN010", "Added", "From Python.", dimensions={"product": ["demo_ocean"]}
    )
    assert file.features[index]["properties"] == {
        "code": "OCN010",
        "title": "Added",
        "message": "From Python.",
        "dimensions": {"product": ["demo_ocean"]},
    }
    with pytest.raises(ValueError, match="already in the file"):
        file.add("OCN001")
    with pytest.raises(ValueError, match="rule code"):
        file.add("not a code")
    with pytest.raises(qe.UnknownNameError):
        file.add("OCN011", dimensions={"resolution": {"lt": 10}})
    with pytest.raises(qe.UnknownNameError, match="undeclared group 'XYZ'"):
        file.add("XYZ001")
    assert len(file.features) == 6


# ---- editing rules --------------------------------------------------------------
def test_update_changes_the_fields_and_the_id_follows_the_code():
    file = demo()
    file.update(1, code=" OCN020 ", level="error", title="T2", message="M2")
    feature = file.features[1]
    props = feature["properties"]
    assert (props["code"], props["level"], props["title"], props["message"]) == (
        "OCN020",
        "error",
        "T2",
        "M2",
    )
    assert feature["id"] == "OCN020" and file.level(1) == "error"
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
        file.update(1, code="OCN001")
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
    file.set_shape(0, arctic(70))  # OCN001 had a geometry
    assert file.features[0]["geometry"] is None
    assert file.features[0]["properties"]["box"] == arctic(70).box
    assert file.shape(0) == arctic(70)
    ring = [[170, 50], [-160, 55], [-170, 65], [170, 50]]
    drawn = from_drawn(
        [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}}]
    )
    file.set_shape(1, drawn)  # OCN002 had a box
    assert "box" not in file.features[1]["properties"]
    assert file.features[1]["geometry"] == drawn.geometry
    file.set_shape(1, None)
    assert file.features[1]["geometry"] is None
    assert "box" not in file.features[1]["properties"] and file.shape(1) is None
    assert file.problems() == []


def test_delete_removes_a_rule():
    file = demo()
    file.delete(1)
    assert file.codes == ["OCN001", "ICE001", "OCN003", "OBC001"]


# ---- what queryearth says -------------------------------------------------------
def test_problems_name_what_queryearth_refuses():
    file = RuleFile.read(DEMO, dimensions=DIMENSIONS[:2])  # leaves out model
    (problem,) = file.problems()
    assert "ICE001" in problem and "model" in problem
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
    assert [f.code for f in found] == ["OCN002"]


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
    file.set_dimensions(DIMENSIONS[:2])  # model is still used by ICE001
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


# ---- groups, order, edge rules and the file format --------------------------------
def test_the_file_is_written_as_queryearth_writes_one():
    file = demo()
    assert file.groups == GROUPS
    written = json.loads(file.text())
    assert list(written) == [
        "type",
        "conformsTo",  # other members stay where they were
        "queryearth",
        "groups",
        "dimensions",
        "features",
    ]
    assert written["queryearth"] == qe.FORMAT and written["groups"] == GROUPS
    registry = qe.Registry.from_file(DEMO)
    assert registry.groups == GROUPS
    collection = {"type": "FeatureCollection", "name": "mine"}
    bare = RuleFile(collection | {"features": [rule("ABC001")], "x_after": 1})
    assert list(json.loads(bare.text())) == [
        "type",
        "name",
        "queryearth",
        "dimensions",  # no groups member without groups
        "features",
        "x_after",
    ]


def test_a_file_for_a_later_queryearth_is_refused():
    collection = {"type": "FeatureCollection", "queryearth": "0.5", "features": []}
    with pytest.raises(qe.LoadError, match="needs queryearth 0.5 or later"):
        RuleFile(collection)
    with pytest.raises(qe.LoadError, match="release"):
        RuleFile(collection | {"queryearth": "soon"})
    older = RuleFile(collection | {"queryearth": "0.3"})
    assert json.loads(older.text())["queryearth"] == qe.FORMAT


def test_rules_are_ordered_by_group_then_number():
    assert [demo().codes[i] for i in demo().order()] == [
        "OCN001",
        "OCN002",
        "OCN003",
        "ICE001",
        "OBC001",
    ]
    codes = ["ZED002", "ABC010", "bad code", "ABC002", "ERA5-001"]
    file = rules(*map(rule, codes))
    assert [file.codes[i] for i in file.order()] == [
        "ABC002",
        "ABC010",
        "ERA5-001",
        "ZED002",
        "bad code",  # a code queryearth cannot read comes last
    ]
    file = rules(*map(rule, codes), groups={"ZED": "Zed", "ERA5": "ERA5"})
    assert [file.codes[i] for i in file.order()] == [
        "ZED002",
        "ERA5-001",
        "ABC002",  # not a group: refused, after the groups
        "ABC010",
        "bad code",
    ]
    assert "undeclared group 'ABC'" in file.problem(1)


def test_groups_are_kept_as_queryearth_reads_them():
    file = demo()
    file.set_groups(GROUPS | {"OCN": "The product", "GRID": "Grids"})
    assert json.loads(file.text())["groups"]["OCN"] == "The product"
    index = file.new("GRID")
    assert file.codes[index] == "GRID001"
    with pytest.raises(ValueError, match="rules still use OBC"):
        file.set_groups({k: v for k, v in GROUPS.items() if k != "OBC"})
    for bad in ({"obc": "lower case"}, {"NEW": " "}):
        with pytest.raises(ValueError):
            file.set_groups(file.groups | bad)
    assert list(file.groups) == ["OCN", "ICE", "OBC", "GRID"]


def test_the_first_groups_must_take_in_every_prefix():
    file = rules(rule("OBC001"), rule("ITF001"))
    with pytest.raises(ValueError, match="add ITF too"):
        file.set_groups({"OBC": "Open boundaries"})
    file.set_groups({p: p for p in file.prefixes()})
    assert file.groups == {"OBC": "OBC", "ITF": "ITF"} and file.problems() == []
    file.delete(1)
    file.set_groups({"OBC": "Open boundaries"})  # ITF has no rules left
    file.delete(0)
    file.set_groups({})
    assert "groups" not in json.loads(file.text())


def test_an_edge_rule_applies_where_a_domain_edge_crosses_it():
    file = demo()
    assert file.features[4]["properties"]["edge"] is True  # OBC001
    across = sp.box(120, 25, 140, 45)  # its east edge crosses OBC001's box
    around = sp.box(120, 20, 160, 50)  # all of the box, its edges outside
    assert "OBC001" in [f.code for f in file.query(space=across)]
    assert "OBC001" not in [f.code for f in file.query(space=around)]
    file.update(4, edge=False)
    assert "edge" not in file.features[4]["properties"]
    assert "OBC001" in [f.code for f in file.query(space=around)]
    file.update(0, edge=True)
    assert file.features[0]["properties"]["edge"] is True
    with pytest.raises(ValueError, match="needs a space"):
        file.update(3, edge=True)  # OCN003 has no shape
    with pytest.raises(ValueError, match="needs a space"):
        file.set_shape(0, None)
    with pytest.raises(ValueError, match="true or false"):
        file.update(0, edge="yes")
