"""The page's calls on a small rule file, through Session.call as the page makes them."""

import json

import pytest
import queryearth as qe

from vizqueryearth import Session

RULES = {
    "type": "FeatureCollection",
    "queryearth": "0.7",
    "features": [
        {
            "type": "Feature",
            "id": "REGION/GULF/GULF001",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-92, 27], [-87, 27], [-87, 30], [-92, 30], [-92, 27]]
                ],
            },
            "time": {"interval": ["1993-01-01", ".."]},
            "properties": {
                "code": "REGION/GULF/GULF001",
                "title": "glorys is too fresh off the Mississippi",
                "message": "Near the delta, glorys surface salinity runs low.",
                "level": "warning",
                "dimensions": {"product": ["glorys"]},
                "instruction": "Compare with observations.",
            },
        },
        {
            "type": "Feature",
            "id": "GRID/GRID001",
            "geometry": None,
            "time": None,
            "properties": {
                "code": "GRID/GRID001",
                "title": "Turn off GM at high resolution",
                "message": "Below 8 km eddies are partly resolved.",
                "level": "info",
                "dimensions": {"resolution": {"lt": 8, "unit": "km"}},
            },
        },
    ],
}
GULF = [{"geometry": {"type": "Polygon", "coordinates": [[[-95, 25], [-85, 25], [-85, 31], [-95, 25]]]}}]  # fmt: skip


def call(session, name, **arguments):
    """A call as the page makes it; its result, or the error as an exception."""
    out = json.loads(session.call(name, json.dumps(arguments)))
    if "error" in out:
        raise ValueError(out["error"])
    return out["ok"]


def opened(rules=RULES, **arguments):
    session = Session()
    call(session, "open", text=json.dumps(rules), **arguments)
    return session


def saved(session):
    return json.loads(call(session, "text"))


def codes(session):
    return [rule.code for rule in session.rules]


def test_a_file_saved_untouched_is_as_queryearth_wrote_it(tmp_path):
    path = tmp_path / "rules.geojson"
    path.write_text(json.dumps(RULES))
    dimensions = [qe.Labels("product"), qe.Axis("resolution", "km")]
    qe.Registry.from_file(path, dimensions=dimensions).to_file(path)
    session = Session()
    call(session, "open", text=path.read_text())
    assert call(session, "text") == path.read_text()


def test_the_state_has_each_rule_as_the_page_shows_it():
    state = call(opened(), "state")
    gulf, grid = state["rules"]
    assert gulf["category"] == "REGION/GULF" and grid["category"] == "GRID"
    assert gulf["time"] == {"start": "1993-01-01", "end": ""}
    assert gulf["dimensions"] == {"product": "glorys", "resolution": ""}
    assert grid["dimensions"] == {"product": "", "resolution": "<8"}
    assert gulf["properties"] == {"instruction": "Compare with observations."}
    assert json.loads(gulf["record"]) == RULES["features"][0]
    assert gulf["extent"] == [-92, 27, -87, 30] and grid["fill"] is None
    assert state["values"] == {"product": ["glorys"]}


def test_dimensions_are_inferred_from_the_rules_values():
    state = call(opened(), "state")
    assert state["dimensions"] == [
        {"name": "product", "kind": "labels"},
        {"name": "resolution", "kind": "axis", "unit": "km"},
    ]


def test_an_axis_whose_rules_give_no_unit_has_one_to_set():
    rules = json.loads(json.dumps(RULES))
    del rules["features"][1]["properties"]["dimensions"]["resolution"]["unit"]
    session = opened(rules)
    assert call(session, "state")["dimensions"][1]["unit"] == "unknown"
    state = call(
        session,
        "dimensions",
        dimensions=[
            {"name": "product", "kind": "labels"},
            {"name": "resolution", "kind": "axis", "unit": "km"},
        ],
    )
    assert state["dimensions"][1]["unit"] == "km"


def test_the_page_can_declare_a_dimension_no_rule_uses_yet():
    session = opened(dimensions=[{"name": "ice", "kind": "labels"}])
    names = [d["name"] for d in call(session, "state")["dimensions"]]
    assert names == ["ice", "product", "resolution"]


def test_a_dimension_a_rule_uses_cannot_be_removed():
    session = opened()
    only_product = [{"name": "product", "kind": "labels"}]
    with pytest.raises(ValueError, match="GRID/GRID001: resolution: undeclared"):
        call(session, "dimensions", dimensions=only_product)
    assert len(session.dimensions) == 2


def test_a_file_for_a_later_queryearth_leaves_the_open_file():
    session = opened()
    later = {"type": "FeatureCollection", "queryearth": "9.0", "features": []}
    with pytest.raises(ValueError, match="needs queryearth 9.0"):
        call(session, "open", text=json.dumps(later))
    assert codes(session) == ["REGION/GULF/GULF001", "GRID/GRID001"]


def test_a_rule_is_edited_and_saved():
    session = opened()
    call(
        session,
        "update",
        index=1,
        fields={
            "title": "GM off",
            "level": "warning",
            "time": ["2000-01-01", "2000-12-31"],
            "dimensions": {"resolution": "2-8", "product": "glorys, era5*"},
        },
    )
    rule = saved(session)["features"][1]
    assert rule["properties"]["title"] == "GM off"
    assert rule["properties"]["level"] == "warning"
    assert rule["time"] == {"interval": ["2000-01-01", "2000-12-31"]}
    assert rule["properties"]["dimensions"] == {
        "resolution": {"ge": 2, "lt": 8, "unit": "km"},
        "product": ["glorys", "era5*"],
    }
    assert saved(session)["queryearth"] == "0.7"


def test_empty_fields_remove_a_rules_time_and_values():
    session = opened()
    fields = {"time": ["", ""], "dimensions": {"product": ""}}
    call(session, "update", index=0, fields=fields)
    rule = saved(session)["features"][0]
    assert rule["time"] is None and "dimensions" not in rule["properties"]


def test_axis_bounds_are_typed_as_signs():
    session = opened()
    fields = {"dimensions": {"resolution": ">2, <=10"}}
    call(session, "update", index=1, fields=fields)
    assert session.rules[1].scope["resolution"] == {"gt": 2, "le": 10, "unit": "km"}
    assert call(session, "state")["rules"][1]["dimensions"]["resolution"] == ">2, <=10"


def test_a_refused_edit_leaves_the_rule_as_it_was():
    session = opened()
    with pytest.raises(ValueError, match="level is one of"):
        call(session, "update", index=0, fields={"level": "loud"})
    with pytest.raises(ValueError, match="already a rule here"):
        call(session, "update", index=0, fields={"code": "GRID/GRID001"})
    assert session.rules[0].code == "REGION/GULF/GULF001"
    assert session.rules[0].level == "warning"


def test_other_properties_are_kept():
    session = opened()
    call(session, "update", index=0, fields={"title": "Fresh"})
    props = saved(session)["features"][0]["properties"]
    assert props["instruction"] == "Compare with observations."


def test_a_new_rule_takes_the_next_number_in_its_category():
    session = opened()
    out = call(session, "new", category="REGION/GULF")
    assert out["index"] == 2 and codes(session)[2] == "REGION/GULF/GULF002"
    call(session, "new", category="REGION/ITF")
    call(session, "new")
    assert codes(session)[3:] == ["REGION/ITF/ITF001", "RULE001"]


def test_moving_a_rule_renames_its_codes_path():
    session = opened()
    out = call(session, "move", index=1, category="REGION/GULF")
    assert (out["was"], out["code"]) == ("GRID/GRID001", "REGION/GULF/GRID001")
    call(session, "move", index=1, category="")
    assert codes(session)[1] == "GRID001"


def test_renaming_a_category_rewrites_the_codes_under_it():
    session = opened()
    call(session, "rename", category="REGION", to="AREAS/REGION")
    assert codes(session) == ["AREAS/REGION/GULF/GULF001", "GRID/GRID001"]
    call(session, "rename", category="AREAS/REGION/GULF", to="GULF")
    assert codes(session)[0] == "GULF/GULF001"


def test_a_category_cannot_move_into_itself():
    session = opened()
    with pytest.raises(ValueError, match="REGION cannot sit in itself"):
        call(session, "rename", category="REGION", to="REGION/GULF/REGION")
    assert codes(session)[0] == "REGION/GULF/GULF001"


def test_a_drawn_shape_or_a_polar_cap_becomes_the_rules_geometry():
    session = opened()
    call(session, "draw", index=1, features=GULF)
    assert saved(session)["features"][1]["geometry"]["type"] == "Polygon"
    call(session, "cap", index=1, pole="north", latitude=66.5)
    assert call(session, "state")["rules"][1]["extent"] == [-180, 66.5, 180, 90]
    call(session, "clear", index=1)
    assert saved(session)["features"][1]["geometry"] is None


def test_a_query_gives_the_rules_that_apply():
    session = opened()
    gulf = {"area": GULF, "start": "2020-01-01", "end": "2020-12-31"}
    assert call(session, "query", **gulf) == []  # no product given
    assert call(session, "query", **gulf, values={"product": "glorys"}) == [0]
    assert call(session, "query", values={"resolution": "5-9"}) == [1]
    assert call(session, "query", values={"resolution": "9"}) == []


def test_a_queryearth_0_6_file_opens_with_path_codes():
    old = {
        "type": "FeatureCollection",
        "queryearth": "0.6",
        "categories": {"DOMAIN": "Domain design", "OBC": {"title": "Open boundaries", "parent": "DOMAIN"}},  # fmt: skip
        "dimensions": [{"name": "model", "kind": "labels"}],
        "features": [
            {
                "type": "Feature",
                "id": "OBC001",
                "geometry": None,
                "properties": {
                    "code": "OBC001",
                    "title": "A strong current",
                    "message": "Give the boundary a sponge.",
                    "box": {"west": 170, "width": 20, "south": 50, "north": 60},
                    "changes": [
                        {"target": "MOM_input", "key": "SPONGE", "value": True}
                    ],
                },
            }
        ],
    }
    session = opened(old)
    rule = saved(session)["features"][0]
    assert rule["properties"]["code"] == "DOMAIN/OBC/OBC001"
    assert rule["properties"]["level"] == "info"  # a rule with changes was info
    assert rule["geometry"]["type"] == "MultiPolygon"  # the box, across the date line
    assert call(session, "state")["dimensions"] == [{"name": "model", "kind": "labels"}]


def test_a_queryearth_0_5_file_names_its_categories_groups():
    old = json.loads(json.dumps(RULES))
    old["queryearth"], old["groups"] = "0.5", {"GULF": "Gulf of Mexico"}
    old["features"][0]["properties"]["code"] = "GULF001"
    assert codes(opened(old))[0] == "GULF/GULF001"


def test_an_old_edge_rule_is_refused_naming_it():
    old = json.loads(json.dumps(RULES))
    old["features"][0]["properties"]["edge"] = True
    with pytest.raises(ValueError, match=r"feature 0: REGION/GULF/GULF001: \['edge'\]"):
        opened(old)
