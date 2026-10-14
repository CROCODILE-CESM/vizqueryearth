"""The web page's link to Python: one Session per page, called with JSON text.

The page runs this module in the browser through Pyodide and calls
Session.call(name, arguments) for everything that needs queryearth: opening a
file, editing a rule, giving it a drawn shape, declaring dimensions, writing
the file and answering queries. Every call returns JSON text: {"ok": result}
or {"error": message}. Values typed on the page, such as "<8" for an axis or
"900" for a change, are read here, so the page itself never interprets them.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

import queryearth as qe
from queryearth.dimensions import describe_dimension

from vizqueryearth import shapes
from vizqueryearth.rulefile import ERRORS, RuleFile, guess_dimensions

_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_RANGE = re.compile(rf"\s*({_NUMBER})\s*(?:\.\.|to|–|-)\s*({_NUMBER})\s*")
_BOUND = re.compile(rf"(<=|>=|≤|≥|<|>)\s*({_NUMBER})")
_OPS = {"<": "lt", "<=": "le", "≤": "le", ">": "gt", ">=": "ge", "≥": "ge"}
_SIGNS = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
AXIS_HINT = "<8, <=8, >2, >=2, or 2-8 (from 2 up to, not including, 8)"


class Session:
    """The rule file a page is showing, and the calls the page makes on it."""

    def __init__(self) -> None:
        self.file = RuleFile()
        self.name = "rules.geojson"

    def call(self, name: str, arguments: str = "{}") -> str:
        """Run one call; its arguments and result are JSON text."""
        method = getattr(self, f"do_{name}", None)
        if method is None:
            return json.dumps({"error": f"no call named {name!r}"})
        try:
            result = method(**json.loads(arguments))
        except qe.LoadError as err:
            return json.dumps({"error": "; ".join(err.problems)})
        except ERRORS as err:
            return json.dumps({"error": str(err).strip("'\"")})
        return json.dumps({"ok": result})

    # ---- calls -------------------------------------------------------------------
    def do_open(
        self, text: str, name: str = "rules.geojson", dimensions: Any = None
    ) -> dict[str, Any]:
        """Read a rule file. The file's own "dimensions" member declares its
        dimensions; without one, dimensions is the page's description of them,
        or None to guess them from the rules."""
        collection = json.loads(text)
        if not isinstance(collection, Mapping):
            raise ValueError("a rule file is a GeoJSON FeatureCollection")
        spec = collection.get("dimensions")
        if spec is None:
            spec = (
                dimensions if dimensions is not None else guess_dimensions(collection)
            )
        self.file = RuleFile(collection, dimensions=spec)
        self.name = name
        return self.do_state()

    def do_state(self) -> dict[str, Any]:
        """Everything the page shows: the rules, their shapes and any problems."""
        found = [self.file.shape(i) for i in range(len(self.file.features))]
        return {
            "name": self.name,
            "dimensions": [describe_dimension(d) for d in self.file.dimensions],
            "values": self._values(),
            "problems": self.file.problems(),
            "extent": shapes.extent(s for s in found if s is not None),
            "rules": [self._rule(i, shape) for i, shape in enumerate(found)],
        }

    def do_update(self, index: int, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Change a rule's fields as the page gives them: text for code, level,
        title and message; [start, end] for time; a list of months; the text
        typed for each dimension; and rows of changes, each value as JSON."""
        given = dict(fields)
        if "dimensions" in given:
            kinds = self._kinds()
            given["dimensions"] = {
                name: _dimension_value(kinds.get(name), text)
                for name, text in given["dimensions"].items()
            }
        if "changes" in given:
            given["changes"] = [
                _change(row)
                for row in given["changes"]
                if any(str(v).strip() for v in row.values())
            ]
        self.file.update(index, **given)
        return self.do_state()

    def do_dimensions(self, dimensions: list[Mapping[str, str]]) -> dict[str, Any]:
        """Declare the dimensions the rules use, as [{name, kind, unit}]."""
        self.file.set_dimensions(dimensions)
        return self.do_state()

    def do_draw(self, index: int, features: list[dict[str, Any]]) -> dict[str, Any]:
        """Give a rule the shape drawn on the globe."""
        self.file.set_shape(index, shapes.from_drawn(features))
        return self.do_state()

    def do_cap(self, index: int, pole: str, latitude: float) -> dict[str, Any]:
        """Give a rule a polar cap: everything poleward of a latitude."""
        cap = shapes.arctic(latitude) if pole == "north" else shapes.antarctic(latitude)
        self.file.set_shape(index, cap)
        return self.do_state()

    def do_clear(self, index: int) -> dict[str, Any]:
        self.file.set_shape(index, None)
        return self.do_state()

    def do_new(self) -> dict[str, Any]:
        index = self.file.new()
        return {"state": self.do_state(), "index": index}

    def do_delete(self, index: int) -> dict[str, Any]:
        self.file.delete(index)
        return self.do_state()

    def do_text(self) -> str:
        """The file to download, checked by queryearth."""
        return self.file.text()

    def do_area(self, features: list[dict[str, Any]]) -> dict[str, Any] | None:
        """How a drawn query area reads: its fill and outline on the globe."""
        shape = shapes.from_drawn(features)
        if shape is None:
            return None
        return {
            "fill": shapes.fill(shape),
            "outline": shapes.outline(shape),
            "km2": round(shape.space.area_km2),
        }

    def do_query(
        self,
        area: list[dict[str, Any]] | None = None,
        start: str = "",
        end: str = "",
        values: Mapping[str, str] | None = None,
        include_conditional: bool = False,
    ) -> dict[str, Any]:
        """Which rules apply to an area, a time and values on the other dimensions."""
        fields: dict[str, Any] = {"include_conditional": include_conditional}
        shape = shapes.from_drawn(area or [])
        if shape is not None:
            fields["space"] = shape.space
        if start or end:
            fields["time"] = qe.interval(start or "..", end or "..")
        given = {}
        kinds = self._kinds()
        for name, text in (values or {}).items():
            if text.strip():
                given[name] = _query_value(kinds.get(name, "labels"), text)
        if given:
            fields["dimensions"] = given
        findings = self.file.query(**fields)
        return {
            "report": qe.report(findings),
            "findings": [_finding(f) for f in findings],
        }

    # ---- helpers -----------------------------------------------------------------
    def _kinds(self) -> dict[str, str]:
        described = (describe_dimension(d) for d in self.file.dimensions)
        return {d["name"]: d["kind"] for d in described}

    def _rule(self, index: int, shape: shapes.Shape | None) -> dict[str, Any]:
        """What the page shows of one rule, with every value as it is edited."""
        feature = self.file.features[index]
        props = feature.get("properties") or {}
        kinds = self._kinds()
        given = props.get("dimensions")
        given = given if isinstance(given, Mapping) else {}
        dims = {
            name: _dimension_text(kind, given[name]) if name in given else ""
            for name, kind in kinds.items()
        }
        for name in given.keys() - kinds.keys():  # undeclared: a problem to clear
            dims[name] = _dimension_text(None, given[name])
        changes = props.get("changes")
        return {
            "index": index,
            "code": props.get("code", ""),
            "title": props.get("title", ""),
            "message": props.get("message", ""),
            "level": self.file.level(index),
            "declared_level": props.get("level") or "",
            "time": _time(feature),
            "dimensions": dims,
            "changes": [
                _change_text(c)
                for c in (changes if isinstance(changes, list) else [])
                if isinstance(c, Mapping)
            ],
            "fill": None if shape is None else shapes.fill(shape),
            "outline": None if shape is None else shapes.outline(shape),
            "label": None if shape is None else shapes.label_point(shape),
            "editable": None if shape is None else shapes.editable(shape),
            "extent": None if shape is None else shapes.extent([shape]),
            "problem": self.file.problem(index),
        }

    def _values(self) -> dict[str, list[str]]:
        """The names the rules give on each label dimension, to suggest in
        queries; patterns such as era5* and any_of/none_of mappings are left out."""
        registry = self.file.accepted()
        return {
            d.name: sorted(
                v
                for v in registry.values(d.name)
                if isinstance(v, str) and not set(v) & set("*?[")
            )
            for d in self.file.dimensions
            if isinstance(d, qe.Labels)
        }


# ---- values as the page shows and types them ------------------------------------
def _number(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() else value


def _number_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _query_value(kind: str, text: str) -> Any:
    """A query value typed on the page: a number or a range for an axis, such as
    8 or 5-10; a comma-separated list of names otherwise."""
    if kind == "axis":
        match = _RANGE.fullmatch(text)
        if match:
            return (float(match.group(1)), float(match.group(2)))
        try:
            return float(text)
        except ValueError:
            raise ValueError(
                f"{text!r} is not a number or a range such as 5-10"
            ) from None
    return _names(text)


def _names(text: str) -> list[str]:
    return [v.strip() for v in text.split(",") if v.strip()]


def _dimension_value(kind: str | None, text: str) -> Any:
    """A rule's value on a dimension, as typed in its form; None when empty.

    JSON text ({...}, [...] or "...") is taken as written. Otherwise labels are
    names separated by commas, versions likewise, and an axis takes bounds such
    as <8 or >=2, several separated by commas, or a range 2-8 (from 2 up to,
    not including, 8)."""
    text = text.strip()
    if not text:
        return None
    if text[0] in '{["':
        try:
            return json.loads(text)
        except ValueError:
            raise ValueError(f"{text!r} is not valid JSON") from None
    if kind == "versions":
        return {"versions": _names(text)}
    if kind != "axis":
        return _names(text)
    match = _RANGE.fullmatch(text)
    if match:
        return {"ge": _number(match.group(1)), "lt": _number(match.group(2))}
    value = {}
    for part in re.split(r"\s*(?:,|\band\b)\s*|\s+(?=[<>≤≥])", text):
        bound = _BOUND.fullmatch(part.strip())
        if bound is None:
            raise ValueError(f"{text!r} is not a range: write {AXIS_HINT}, or JSON")
        value[_OPS[bound.group(1)]] = _number(bound.group(2))
    return value


def _dimension_text(kind: str | None, value: Any) -> str:
    """A rule's value on a dimension, as its form shows it: the short forms that
    _dimension_value reads where they say the same, JSON otherwise."""
    if kind == "labels" and isinstance(value, str):
        return value
    if kind == "labels" and _strings(value):
        return ", ".join(value)
    if kind == "versions" and isinstance(value, Mapping) and set(value) == {"versions"}:
        if _strings(value["versions"]):
            return ", ".join(value["versions"])
    if kind == "axis" and isinstance(value, Mapping) and value:
        bounds = {k: v for k, v in value.items() if k != "unit"}
        numbers = all(isinstance(v, (int, float)) for v in bounds.values())
        if bounds and set(bounds) <= set(_SIGNS) and numbers:
            if set(bounds) == {"ge", "lt"}:
                return f"{_number_text(bounds['ge'])}-{_number_text(bounds['lt'])}"
            return ", ".join(
                f"{_SIGNS[k]}{_number_text(bounds[k])}" for k in _SIGNS if k in bounds
            )
    return json.dumps(value)


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _change(row: Mapping[str, Any]) -> dict[str, Any]:
    """A change from its row on the page; the value is JSON, or else plain text."""
    target = str(row.get("target") or "").strip()
    key = str(row.get("key") or "").strip()
    text = str(row.get("value") or "").strip()
    if not text:
        raise ValueError(
            f"the change to {key or 'a key'} needs a value: JSON, such as true, "
            '900 or "CICE"'
        )
    try:
        value = json.loads(text)
    except ValueError:
        value = text  # plain text is a string
    change = {"target": target, "key": key, "value": value}
    rationale = str(row.get("rationale") or "").strip()
    if rationale:
        change["rationale"] = rationale
    return change


def _change_text(change: Mapping[str, Any]) -> dict[str, str]:
    return {
        "target": str(change.get("target", "")),
        "key": str(change.get("key", "")),
        "value": json.dumps(change.get("value")),
        "rationale": str(change.get("rationale") or ""),
    }


def _time(feature: Mapping[str, Any]) -> dict[str, Any]:
    """A rule's time as its form shows it: the dates of an interval, the months,
    and, as text, any other time it has, which editing the dates replaces."""
    member = feature.get("time")
    props = feature.get("properties") or {}
    kept = {k: props[k] for k in ("periods", "time_start", "time_end") if k in props}
    start = end = ""
    pair = member.get("interval") if isinstance(member, Mapping) else None
    plain = isinstance(pair, list) and len(pair) == 2 and len(member) == 1
    if plain and all(
        isinstance(v, str) and (v == ".." or _DATE.fullmatch(v)) for v in pair
    ):
        start, end = ("" if v == ".." else v for v in pair)
    elif member is not None:
        kept = {"time": member} | kept
    recurrence = props.get("recurrence")
    months = recurrence.get("months") if isinstance(recurrence, Mapping) else None
    return {
        "start": start,
        "end": end,
        "months": (
            [m for m in months if isinstance(m, int)]
            if isinstance(months, list)
            else []
        ),
        "kept": "; ".join(f"{k} {json.dumps(v)}" for k, v in kept.items()),
    }


def _finding(finding: qe.Finding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "level": logging.getLevelName(finding.level).lower(),
        "title": finding.title,
        "message": finding.message,
        "changes": [
            {
                "target": c.target,
                "key": c.key,
                "value": c.value,
                "rationale": c.rationale,
            }
            for c in finding.changes
        ],
        "conditional_on": list(finding.conditional_on),
        "area_fraction": finding.area_fraction,
        "text": str(finding),
    }
