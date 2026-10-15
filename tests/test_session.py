"""vizqueryearth.session: the JSON calls the web page makes on its rule file."""

import json
from pathlib import Path

import pytest
import queryearth as qe

from vizqueryearth.session import Session

DEMO = Path(__file__).parent.parent / "web" / "sites" / "demo" / "rules.geojson"
LABELS = [
    {"name": "product", "kind": "labels"},
    {"name": "variable", "kind": "labels"},
    {"name": "model", "kind": "labels"},
]
RESOLUTION = {"name": "resolution", "kind": "axis", "unit": "km"}
CODES = ["OCN001", "OCN002", "ICE001", "OCN003", "OBC001"]  # in file order
BERING = [[172, 56], [172, 63], [-168, 63], [-168, 56], [172, 56]]  # across 180


def call(session, what, **arguments):
    """One call as the page makes it: JSON text in, JSON text out."""
    return json.loads(session.call(what, json.dumps(arguments)))


def ok(session, what, **arguments):
    out = call(session, what, **arguments)
    assert "error" not in out, out["error"]
    return out["ok"]


def opened(text=None, **arguments):
    session = Session()
    ok(session, "open", text=text or DEMO.read_text(), **arguments)
    return session


def undeclared():
    """The demo rules without their "dimensions" member."""
    collection = json.loads(DEMO.read_text())
    del collection["dimensions"]
    return json.dumps(collection)


def drawn(*rings):
    return [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }
        for ring in rings
    ]


def rule(code, **properties):
    return {
        "type": "Feature",
        "id": code,
        "geometry": None,
        "time": None,
        "properties": {"code": code, "title": "T", "message": "M"} | properties,
    }


def collection(*features, dimensions=None):
    out = {"type": "FeatureCollection", "features": list(features)}
    if dimensions is not None:
        out["dimensions"] = dimensions
    return json.dumps(out)


# ---- opening --------------------------------------------------------------------
def test_open_reads_the_files_own_dimensions():
    state = ok(Session(), "open", text=DEMO.read_text(), name="demo.geojson")
    assert state["name"] == "demo.geojson"
    assert state["dimensions"] == LABELS
    assert state["problems"] == []
    assert [r["code"] for r in state["rules"]] == CODES
    # the file's own declaration wins over the page's
    state = ok(Session(), "open", text=DEMO.read_text(), dimensions=[RESOLUTION])
    assert state["dimensions"] == LABELS


def test_open_takes_the_pages_dimensions_or_guesses_them():
    axis = {"name": "model", "kind": "axis", "unit": "km"}
    state = ok(Session(), "open", text=undeclared(), dimensions=LABELS[:2] + [axis])
    assert state["dimensions"] == LABELS[:2] + [axis]
    assert any("ICE001" in p for p in state["problems"])  # model is not an axis
    assert state["rules"][2]["problem"] and state["rules"][0]["problem"] is None
    assert ok(Session(), "open", text=undeclared())["dimensions"] == LABELS


def test_open_refuses_what_is_not_a_rule_file():
    session = Session()
    for text in ('{"type": "Feature"}', "[1, 2]", "not json"):
        assert "error" in call(session, "open", text=text)
    out = call(session, "open", text=collection(dimensions=[{"name": "x"}]))
    assert "axis, labels or versions" in out["error"]


def test_a_file_for_a_later_queryearth_leaves_the_open_file():
    session = opened(name="demo.geojson")
    major, minor = map(int, qe.FORMAT.split("."))
    later = json.loads(DEMO.read_text()) | {"queryearth": f"{major}.{minor + 1}"}
    out = call(session, "open", text=json.dumps(later), name="later.geojson")
    assert out["error"].startswith(f"this file needs queryearth {major}.{minor + 1}")
    assert out["error"].endswith(f"which reads files up to {qe.FORMAT}")
    state = ok(session, "state")
    assert state["name"] == "demo.geojson" and len(state["rules"]) == 5


# ---- the state ------------------------------------------------------------------
def test_the_state_has_what_the_page_shows():
    state = ok(opened(), "state")
    assert state["values"] == {
        "product": ["demo_ocean"],
        "variable": ["so", "thetao"],
        "model": ["demo_model"],
    }
    assert state["extent"] == [128, 18, 280, 90]  # the Arctic cap counts for latitude
    assert [state["rules"][i]["code"] for i in state["order"]] == [
        "OCN001",
        "OCN002",
        "OCN003",
        "ICE001",
        "OBC001",
    ]
    top = {"parent": "", "depth": 0}
    assert state["groups"] == [  # in the order declared
        {"prefix": "OCN", "title": "demo_ocean, the product", "rules": 3}
        | top
        | {"children": []},
        {"prefix": "DOMAIN", "title": "Domain design", "rules": 0}
        | top
        | {"children": ["ICE", "OBC"]},
        {"prefix": "ICE", "title": "Sea ice", "parent": "DOMAIN", "depth": 1}
        | {"children": [], "rules": 1},
        {"prefix": "OBC", "title": "Open boundaries", "parent": "DOMAIN", "depth": 1}
        | {"children": [], "rules": 1},
    ]
    assert state["tree"] == ["OCN", "DOMAIN", "ICE", "OBC"]
    assert [f["prefix"] for f in state["filters"]] == state["tree"]
    gulf, bering, arctic, early, edge = state["rules"]
    assert (gulf["group"], gulf["edge"]) == ("OCN", False)
    assert (edge["group"], edge["edge"]) == ("OBC", True)
    assert gulf["path"] == ["OCN"] and edge["path"] == ["DOMAIN", "OBC"]
    # what a rule's card shows besides its fields
    assert bering["instruction"].startswith("Compare demo_ocean with observations")
    assert bering["references"] == [
        {
            "title": "queryearth: writing rules",
            "url": "https://crocodile-cesm.github.io/queryearth/",
        }
    ]
    assert bering["evidence"][0]["quote"].startswith("Made up for this demo")
    assert (bering["status"], bering["confidence"]) == ("draft", "")
    assert gulf["instruction"] == "" and gulf["references"] == []
    assert gulf["index"] == 0 and gulf["level"] == "warning"
    assert gulf["declared_level"] == ""
    assert gulf["fill"]["type"] == "Polygon" and gulf["outline"]["type"] == "LineString"
    assert len(gulf["editable"]) == 1 and gulf["label"] == [-89, 22]
    assert gulf["extent"] == [-98, 18, -80, 31]
    assert gulf["dimensions"] == {
        "product": "demo_ocean",
        "variable": "so",
        "model": "",
    }
    assert gulf["time"] == {"start": "", "end": "", "months": [], "kept": ""}
    assert gulf["changes"] == []
    assert bering["fill"]["type"] == "MultiPolygon" and bering["editable"] is None
    assert bering["extent"] == [165, 52, 200, 66]
    assert arctic["editable"] is None and arctic["extent"] == [-180, 66.5, 180, 90]
    assert early["fill"] is None and early["extent"] is None
    assert (
        early["time"]["start"] == "1993-01-01" and early["time"]["end"] == "2003-12-31"
    )
    assert all(r["problem"] is None for r in state["rules"])


def test_other_forms_of_time_are_shown_as_kept():
    text = collection(
        rule("TIM001", time_start="2000-01-01", time_end="2001-01-01"),
        rule("TIM002") | {"time": {"date": "2000-01-01"}},
        rule(
            "TIM003", periods=[["2000-01-01", "2000-03-31"]], recurrence={"months": [1]}
        )
        | {"time": {"interval": ["2000-01-01", "2001-12-31"]}},
    )
    first, second, third = ok(opened(text), "state")["rules"]
    assert first["time"]["kept"] == 'time_start "2000-01-01"; time_end "2001-01-01"'
    assert second["time"]["kept"] == 'time {"date": "2000-01-01"}'
    assert third["time"] == {
        "start": "2000-01-01",
        "end": "2001-12-31",
        "months": [1],
        "kept": 'periods [["2000-01-01", "2000-03-31"]]',
    }


# ---- editing --------------------------------------------------------------------
def test_new_update_and_delete():
    session = opened()
    out = ok(session, "new")
    assert out["index"] == 5 and out["state"]["rules"][5]["code"] == "OCN004"
    state = ok(session, "update", index=5, fields={"title": "Mine", "level": "error"})
    assert (state["rules"][5]["title"], state["rules"][5]["level"]) == ("Mine", "error")
    assert call(session, "update", index=5, fields={"code": "OCN001"}) == {
        "error": "OCN001 is already in the file"
    }
    state = ok(session, "delete", index=0)
    codes = [r["code"] for r in state["rules"]]
    assert codes == CODES[1:] + ["OCN004"]


def test_a_new_rule_takes_the_next_code_in_its_group():
    session = opened()
    out = ok(session, "new", prefix="OBC")
    assert out["state"]["rules"][out["index"]]["code"] == "OBC002"
    assert "undeclared group" in call(session, "new", prefix="XYZ")["error"]
    bare = opened(collection(rule("ZED007"), rule("ABC001")))
    out = ok(bare, "new")  # no groups: the prefix of the last code
    assert out["state"]["rules"][out["index"]]["code"] == "ABC002"
    none = {"title": "", "parent": "", "depth": 0, "children": []}
    state = ok(bare, "state")
    assert state["filters"] == [{"prefix": "ABC"} | none, {"prefix": "ZED"} | none]
    assert state["rules"][0]["path"] == ["ZED"]


def listed(state):
    """The groups as the page sends them back."""
    return [
        {"prefix": g["prefix"], "title": g["title"], "parent": g["parent"]}
        for g in state["groups"]
    ]


def test_groups_are_declared_as_a_list():
    session = opened()
    groups = listed(ok(session, "state"))
    grid = {"prefix": "GRID", "title": "Grids", "parent": "DOMAIN"}
    state = ok(session, "groups", groups=groups + [grid])
    assert state["tree"] == ["OCN", "DOMAIN", "ICE", "OBC", "GRID"]
    written = json.loads(ok(session, "text"))["groups"]
    assert written["GRID"] == {"title": "Grids", "parent": "DOMAIN"}
    renamed = [g | {"title": "Ice"} if g["prefix"] == "ICE" else g for g in groups]
    state = ok(session, "groups", groups=renamed)  # and GRID removed
    assert state["groups"][2]["title"] == "Ice"
    out = call(session, "groups", groups=[g for g in groups if g["prefix"] != "OBC"])
    assert "rules still use OBC" in out["error"]
    out = call(session, "groups", groups=groups + [{"prefix": "x", "title": "X"}])
    assert "not a code prefix" in out["error"]
    out = call(session, "groups", groups=groups + [groups[0]])
    assert "one group" in out["error"]
    bare = opened(collection(rule("OBC001"), rule("ITF001")))
    out = call(bare, "groups", groups=[{"prefix": "OBC", "title": "Open boundaries"}])
    assert "add ITF too" in out["error"]


def test_a_group_moves_to_another_parent():
    session = opened()
    groups = listed(ok(session, "state"))
    moved = [g | {"parent": ""} if g["prefix"] == "OBC" else g for g in groups]
    state = ok(session, "groups", groups=moved)  # OBC to the top level
    assert state["tree"] == ["OCN", "DOMAIN", "ICE", "OBC"]
    assert next(r for r in state["rules"] if r["code"] == "OBC001")["path"] == ["OBC"]
    under = [g | {"parent": "OBC"} if g["prefix"] == "DOMAIN" else g for g in moved]
    state = ok(session, "groups", groups=under)  # DOMAIN into OBC, which moves up
    assert [g["prefix"] for g in state["groups"]] == ["OCN", "OBC", "DOMAIN", "ICE"]
    assert next(r for r in state["rules"] if r["code"] == "ICE001")["path"] == [
        "OBC",
        "DOMAIN",
        "ICE",
    ]
    loop = [g | {"parent": "ICE"} if g["prefix"] == "OBC" else g for g in listed(state)]
    assert "cannot sit in each other" in call(session, "groups", groups=loop)["error"]
    out = call(
        session, "groups", groups=[g for g in listed(state) if g["prefix"] != "DOMAIN"]
    )
    assert "DOMAIN has groups in it: ICE" in out["error"]


def test_the_edge_box_is_ticked_and_some_rules_have_an_extent():
    session = opened()
    state = ok(session, "update", index=0, fields={"edge": True})
    assert state["rules"][0]["edge"] and session.file.features[0]["properties"]["edge"]
    assert (
        "needs a space"
        in call(session, "update", index=3, fields={"edge": True})["error"]
    )
    assert ok(session, "extent", indexes=[1, 4]) == [128, 28, 200, 66]
    assert ok(session, "extent", indexes=[3]) is None


def test_time_and_months_are_edited():
    session = opened()
    state = ok(session, "update", index=0, fields={"time": ["2001-01-01", ""]})
    assert session.file.features[0]["time"] == {"interval": ["2001-01-01", ".."]}
    assert state["rules"][0]["time"]["start"] == "2001-01-01"
    state = ok(session, "update", index=0, fields={"months": [12, 1, 2]})
    assert session.file.features[0]["properties"]["recurrence"] == {
        "months": [12, 1, 2]
    }
    assert state["rules"][0]["time"]["months"] == [12, 1, 2]
    ok(session, "update", index=0, fields={"time": ["", ""], "months": []})
    assert session.file.features[0]["time"] is None
    assert "recurrence" not in session.file.features[0]["properties"]
    out = call(
        session, "update", index=0, fields={"time": ["2001-01-01", "2000-01-01"]}
    )
    assert "out of order" in out["error"]


@pytest.mark.parametrize(
    "typed, written, shown",
    [
        ("<8", {"lt": 8}, "<8"),
        ("<= 8", {"le": 8}, "<=8"),
        (">2, <=8.5", {"gt": 2, "le": 8.5}, ">2, <=8.5"),
        (">=2 <8", {"ge": 2, "lt": 8}, "2-8"),
        ("2-8", {"ge": 2, "lt": 8}, "2-8"),
        ('[{"lt": 5}, {"gt": 50}]', [{"lt": 5}, {"gt": 50}], '[{"lt": 5}, {"gt": 50}]'),
    ],
)
def test_an_axis_is_typed_as_bounds_or_json(typed, written, shown):
    session = opened(collection(rule("RES001"), dimensions=[RESOLUTION]))
    state = ok(session, "update", index=0, fields={"dimensions": {"resolution": typed}})
    assert session.file.features[0]["properties"]["dimensions"] == {
        "resolution": written
    }
    assert state["rules"][0]["dimensions"] == {"resolution": shown}


def test_labels_and_versions_are_typed_as_names_or_json():
    dims = LABELS[:1] + [{"name": "version", "kind": "versions"}]
    session = opened(collection(rule("VER001"), dimensions=dims))
    fields = {"dimensions": {"product": "glorys, era5*", "version": "4.07, ERA5T"}}
    state = ok(session, "update", index=0, fields=fields)
    assert session.file.features[0]["properties"]["dimensions"] == {
        "product": ["glorys", "era5*"],
        "version": {"versions": ["4.07", "ERA5T"]},
    }
    assert state["rules"][0]["dimensions"] == {
        "product": "glorys, era5*",
        "version": "4.07, ERA5T",
    }
    fields = {"dimensions": {"version": '{"introduced": "4.00", "fixed": "4.09"}'}}
    state = ok(session, "update", index=0, fields=fields)
    shown = state["rules"][0]["dimensions"]["version"]
    assert json.loads(shown) == {"introduced": "4.00", "fixed": "4.09"}
    ok(session, "update", index=0, fields={"dimensions": {"product": " "}})
    assert "product" not in session.file.features[0]["properties"]["dimensions"]


def test_a_value_that_is_not_understood_is_an_error():
    session = opened(collection(rule("RES001"), dimensions=[RESOLUTION]))
    for typed in ("fine", "8", "{oops"):
        fields = {"dimensions": {"resolution": typed}}
        assert "error" in call(session, "update", index=0, fields=fields)
    fields = {"dimensions": {"resolution": "<8 km"}}
    assert "<=8" in call(session, "update", index=0, fields=fields)["error"]  # the hint
    assert "dimensions" not in session.file.features[0]["properties"]


def test_changes_are_edited_as_rows():
    session = opened()
    rows = [
        {"target": "MOM_input", "key": "DT", "value": "900", "rationale": "stable"},
        {"target": "ice", "key": "on", "value": "true", "rationale": ""},
        {"target": "case", "key": "model", "value": "CICE", "rationale": ""},
        {"target": "", "key": "", "value": "", "rationale": ""},  # a blank row
    ]
    state = ok(session, "update", index=0, fields={"changes": rows})
    assert session.file.features[0]["properties"]["changes"] == [
        {"target": "MOM_input", "key": "DT", "value": 900, "rationale": "stable"},
        {"target": "ice", "key": "on", "value": True},
        {"target": "case", "key": "model", "value": "CICE"},
    ]
    rule = state["rules"][0]
    assert rule["level"] == "info"  # the default with changes
    assert [c["value"] for c in rule["changes"]] == ["900", "true", '"CICE"']
    missing = [{"target": "MOM_input", "key": "DT", "value": "", "rationale": ""}]
    assert (
        "needs a value"
        in call(session, "update", index=0, fields={"changes": missing})["error"]
    )
    no_key = [{"target": "MOM_input", "key": "", "value": "1", "rationale": ""}]
    assert (
        "key" in call(session, "update", index=0, fields={"changes": no_key})["error"]
    )
    state = ok(session, "update", index=0, fields={"changes": []})
    assert "changes" not in session.file.features[0]["properties"]
    assert state["rules"][0]["level"] == "warning"


def test_dimensions_are_declared_and_written_in_the_file():
    session = opened()
    state = ok(session, "dimensions", dimensions=LABELS + [RESOLUTION])
    assert state["dimensions"] == LABELS + [RESOLUTION]
    assert json.loads(ok(session, "text"))["dimensions"] == LABELS + [RESOLUTION]
    state = ok(session, "dimensions", dimensions=LABELS[:2])  # model is still used
    assert any("model" in p for p in state["problems"])
    assert "error" in call(session, "text")
    out = call(session, "dimensions", dimensions=[LABELS[0], LABELS[0]])
    assert "already declared" in out["error"]
    assert ok(session, "state")["dimensions"] == LABELS[:2]


# ---- shapes ---------------------------------------------------------------------
def test_drawing_a_rectangle_across_the_date_line_gives_a_box():
    session = opened()
    ring = [[170, 50], [170, 60], [-170, 60], [-170, 50], [170, 50]]
    state = ok(session, "draw", index=0, features=drawn(ring))
    feature = session.file.features[0]
    assert feature["properties"]["box"] == {
        "west": 170,
        "width": 20,
        "south": 50,
        "north": 60,
    }
    assert feature["geometry"] is None
    assert state["rules"][0]["fill"]["type"] == "MultiPolygon"
    assert state["rules"][0]["extent"] == [170, 50, 190, 60]


def test_drawing_a_polygon_across_the_date_line_gives_a_split_geometry():
    session = opened()
    ring = [[170, 50], [-160, 55], [-170, 65], [170, 50]]
    state = ok(session, "draw", index=1, features=drawn(ring))
    feature = session.file.features[1]
    assert "box" not in feature["properties"]
    assert feature["geometry"]["type"] == "MultiPolygon"
    assert state["rules"][1]["fill"]["type"] == "MultiPolygon"
    assert state["rules"][1]["editable"] is None


def test_polar_caps_and_clearing_a_shape():
    session = opened()
    ok(session, "cap", index=0, pole="north", latitude=70)
    assert session.file.features[0]["properties"]["box"] == {
        "west": -180,
        "width": 360,
        "south": 70,
        "north": 90,
    }
    ok(session, "cap", index=0, pole="south", latitude=-60)
    box = session.file.features[0]["properties"]["box"]
    assert (box["south"], box["north"]) == (-90, -60)
    state = ok(session, "clear", index=0)
    assert state["rules"][0]["fill"] is None
    assert "box" not in session.file.features[0]["properties"]


def test_text_is_the_file_checked_by_queryearth():
    session = opened()
    assert ok(session, "text") == DEMO.read_text()
    bad = opened(undeclared(), dimensions=LABELS[:2])
    assert "model" in call(bad, "text")["error"]


# ---- checking an area -----------------------------------------------------------
def test_a_drawn_area_is_shown_as_queryearth_reads_it():
    session = Session()
    area = ok(session, "area", features=drawn(BERING))
    assert area["fill"]["type"] == "MultiPolygon"
    assert area["outline"]["type"] == "MultiLineString"
    assert 500_000 < area["km2"] < 1_000_000
    assert ok(session, "area", features=[]) is None


def test_a_query_with_an_area_dates_and_labels():
    session = opened()
    winter = {"area": drawn(BERING), "start": "2001-01-01", "end": "2001-03-31"}
    values = {"product": "demo_ocean", "variable": "thetao"}
    out = ok(session, "query", **winter, values=values)
    (finding,) = out["findings"]
    assert finding["code"] == "OCN002" and finding["level"] == "warning"
    assert finding["area_fraction"] == 1.0 and finding["conditional_on"] == []
    assert "OCN002" in out["report"]
    values = {"product": "demo_ocean", "variable": ""}
    out = ok(session, "query", **winter, values=values, include_conditional=True)
    found = {f["code"]: f["conditional_on"] for f in out["findings"]}
    assert found["OCN003"] == ["variable"]
    later = {"start": "2001-01-01", "end": "2001-12-31"}  # no area: anywhere
    values = {"product": "other, demo_ocean", "variable": "so"}
    out = ok(session, "query", **later, values=values)
    assert [f["code"] for f in out["findings"]] == ["OCN003"]


def test_axis_query_values_are_a_number_or_a_range():
    text = collection(
        rule("RES001", dimensions={"resolution": {"lt": 10, "unit": "km"}}),
        dimensions=[RESOLUTION],
    )
    session = opened(text)

    def codes(value):
        out = ok(session, "query", values={"resolution": value})
        return [f["code"] for f in out["findings"]]

    assert codes("8") == ["RES001"]
    assert codes("5-10") == ["RES001"]
    assert codes("12 - 20") == []
    assert codes("20") == []
    out = call(session, "query", values={"resolution": "fine"})
    assert "not a number" in out["error"]


def test_an_unknown_call_is_an_error():
    assert call(Session(), "nope") == {"error": "no call named 'nope'"}
