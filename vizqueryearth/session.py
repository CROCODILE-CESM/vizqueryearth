"""The web page's link to Python: one Session per page, called with JSON text.

The page runs this module in the browser through Pyodide and calls
Session.call(name, arguments) for everything that touches the rules: opening a
file, editing, moving and drawing rules, declaring dimensions, writing the file
and answering queries. Every call returns JSON text, {"ok": result} or
{"error": message}. queryearth checks every edit before it is kept, so the rules
held here are always ones it reads. Values typed on the page, such as "<8" for an
axis, are read here too, so the page itself never interprets them.
"""

from __future__ import annotations

import dataclasses
import json
import re
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import queryearth as qe
from queryearth import space as sp

from vizqueryearth import shapes

UNKNOWN = "unknown"  # the unit of an axis whose rules give none, until one is set
BOUNDS = {"gt", "ge", "lt", "le"}
_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_RANGE = re.compile(rf"\s*({_NUMBER})\s*(?:\.\.|to|–|-)\s*({_NUMBER})\s*")
_BOUND = re.compile(rf"(<=|>=|≤|≥|<|>)\s*({_NUMBER})")
_OPS = {"<": "lt", "<=": "le", "≤": "le", ">": "gt", ">=": "ge", "≥": "ge"}
_SIGNS = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}
AXIS_HINT = "<8, <=8, >2, >=2, or 2-8 (from 2 up to, not including, 8)"
_OLD_CODE = re.compile(r"([A-Z][A-Z0-9]*?)-?[0-9]{3,4}")  # before 0.7: OBC001


class Session:
    """The rules a page shows, the dimensions they use, and the page's calls."""

    def __init__(self) -> None:
        self.name = "rules.geojson"
        self.dimensions: list[qe.Dimension] = []
        self.rules: list[qe.Rule] = []

    def call(self, name: str, arguments: str = "{}") -> str:
        """Run one call; its arguments and result are JSON text."""
        method = getattr(self, f"do_{name}", None)
        if method is None:
            return json.dumps({"error": f"no call named {name!r}"})
        try:
            result = method(**json.loads(arguments))
        except (ValueError, TypeError, KeyError) as err:
            return json.dumps({"error": str(err).strip("'\"")})
        return json.dumps({"ok": result})

    # ---- opening and saving ------------------------------------------------------
    def do_open(
        self, text: str, name: str = "rules.geojson", dimensions: Any = None
    ) -> dict[str, Any]:
        """Read a rule file with queryearth. Its dimensions are those the page
        gives, as [{name, kind, unit}], then those a file from before
        queryearth 0.7 declares, then those inferred from the rules. A file
        queryearth refuses leaves the open file as it was."""
        data, declared = upgrade(json.loads(text))
        found = infer(data.get("features") or [], [*(dimensions or []), *declared])
        found = [_dimension(d) for d in found]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, Path(name).name or "rules.geojson")
            path.write_text(json.dumps(data), encoding="utf-8")
            try:
                registry = qe.Registry.from_file(path, dimensions=found)
            except ValueError as err:
                raise ValueError(str(err).removeprefix(f"{path.name}: ")) from None
        self.name, self.rules, self.dimensions = name, registry.rules, found
        return self.do_state()

    def do_text(self) -> str:
        """The rule file, as queryearth writes it."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "rules.geojson")
            self._keep().to_file(path)
            return path.read_text(encoding="utf-8")

    def do_state(self) -> dict[str, Any]:
        """Everything the page shows: the dimensions and the rules."""
        spaces = [_space(rule) for rule in self.rules]
        labels = [d.name for d in self.dimensions if isinstance(d, qe.Labels)]
        return {
            "name": self.name,
            "dimensions": [_described(d) for d in self.dimensions],
            # the names the rules give on each labels dimension, to suggest
            "values": {name: self._names(name) for name in labels},
            "extent": shapes.extent(s for s in spaces if s is not None),
            "rules": [self._rule(i, space) for i, space in enumerate(spaces)],
        }

    # ---- editing -----------------------------------------------------------------
    def do_update(self, index: int, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Change a rule's fields as the page gives them: text for code, title,
        message and level; [start, end] for time, with "" for an open end; and
        the text typed for each dimension, "" for none."""
        rule = self.rules[index]
        changed = {
            k: fields[k] for k in ("code", "title", "message", "level") if k in fields
        }
        if "code" in changed:
            changed["code"] = changed["code"].strip()
        scope = dict(rule.scope)
        if "time" in fields:
            start, end = (value or ".." for value in fields["time"])
            scope["time"] = None if start == end == ".." else {"interval": [start, end]}
        declared = {d.name: d for d in self.dimensions}
        for name, text in fields.get("dimensions", {}).items():
            if name not in declared:
                raise ValueError(f"{name} is not a dimension")
            scope[name] = _value(declared[name], text)
        scope = {k: v for k, v in scope.items() if v is not None}
        self._replace(index, dataclasses.replace(rule, **changed, scope=scope))
        return self.do_state()

    def do_new(self, category: str = "") -> dict[str, Any]:
        """Add a rule to a category, "" for none, with the next number after the
        last part of the category's path: DOMAIN/OBC/OBC006 after
        DOMAIN/OBC/OBC005, or RULE001 at the top. Returns its position."""
        stem = category.rpartition("/")[2] or "RULE"
        prefix = f"{category}/{stem}" if category else stem
        numbered = (
            re.fullmatch(re.escape(prefix) + r"(\d+)", r.code) for r in self.rules
        )
        number = max((int(m[1]) for m in numbered if m), default=0) + 1
        rule = qe.Rule(
            f"{prefix}{number:03d}", "New rule", "Say what this rule is about."
        )
        self._keep([*self.rules, rule])
        return {"state": self.do_state(), "index": len(self.rules) - 1}

    def do_delete(self, index: int) -> dict[str, Any]:
        self._keep(self.rules[:index] + self.rules[index + 1 :])
        return self.do_state()

    def do_move(self, index: int, category: str) -> dict[str, Any]:
        """Move a rule to a category, "" for none: its code takes that path and
        keeps its last part, so REGION/ITF/ITF003 moved to DOMAIN/OBC becomes
        DOMAIN/OBC/ITF003. Returns the old code and the new one."""
        rule = self.rules[index]
        code = "/".join(filter(None, [category, rule.code.rpartition("/")[2]]))
        if code == rule.code:
            raise ValueError(f"{rule.code} is in {category or 'no category'} already")
        self._replace(index, dataclasses.replace(rule, code=code))
        return {"state": self.do_state(), "was": rule.code, "code": code}

    def do_rename(self, category: str, to: str) -> dict[str, Any]:
        """Rename or move a category: every code under it takes the new path,
        so DOMAIN/OBC/OBC001 becomes REGION/OBC/OBC001 when DOMAIN/OBC becomes
        REGION/OBC."""
        if to.startswith(category + "/"):
            raise ValueError(f"{category} cannot sit in itself")
        size = len(category) + 1
        self._keep(
            [
                (
                    dataclasses.replace(r, code=f"{to}/{r.code[size:]}")
                    if r.code.startswith(category + "/")
                    else r
                )
                for r in self.rules
            ]
        )
        return self.do_state()

    def do_dimensions(self, dimensions: list[Mapping[str, str]]) -> dict[str, Any]:
        """Declare the dimensions, as [{name, kind, unit}]; queryearth refuses a
        change that a rule's value does not fit, such as removing one in use."""
        self._keep(dimensions=[_dimension(d) for d in dimensions])
        return self.do_state()

    # ---- shapes ------------------------------------------------------------------
    def do_draw(self, index: int, features: list[dict[str, Any]]) -> dict[str, Any]:
        """Give a rule the shape drawn on the globe."""
        return self._shape(index, shapes.drawn(features))

    def do_cap(self, index: int, pole: str, latitude: float) -> dict[str, Any]:
        """Give a rule everything poleward of a latitude."""
        return self._shape(index, shapes.cap(pole, latitude))

    def do_clear(self, index: int) -> dict[str, Any]:
        return self._shape(index, None)

    def do_area(self, features: list[dict[str, Any]]) -> dict[str, Any] | None:
        """How a drawn query area reads: what the globe shows of it."""
        space = shapes.drawn(features)
        return None if space is None else shapes.on_globe(space)

    def do_extent(self, indexes: list[int]) -> list[float] | None:
        """The extent of some rules' shapes, for the globe to turn to them."""
        found = (_space(self.rules[i]) for i in indexes)
        return shapes.extent(s for s in found if s is not None)

    # ---- checking ----------------------------------------------------------------
    def do_query(
        self,
        area: list[dict[str, Any]] | None = None,
        start: str = "",
        end: str = "",
        values: Mapping[str, str] | None = None,
    ) -> list[int]:
        """The positions of the rules that apply to an area, dates and the
        values typed for the other dimensions, in queryearth's order."""
        query: dict[str, Any] = {"space": shapes.drawn(area or [])}
        if start or end:
            query["time"] = qe.interval(start or "..", end or "..")
        declared = {d.name: d for d in self.dimensions}
        for name, text in (values or {}).items():
            if text.strip():
                query[name] = _query_value(declared.get(name), text)
        where = {rule.code: i for i, rule in enumerate(self.rules)}
        return [where[rule.code] for rule in self._keep().query(**query)]

    # ---- helpers -----------------------------------------------------------------
    def _keep(
        self,
        rules: Iterable[qe.Rule] | None = None,
        dimensions: Iterable[qe.Dimension] | None = None,
    ) -> qe.Registry:
        """Check rules and dimensions with queryearth, then keep them; the
        Registry that holds them."""
        rules = list(self.rules if rules is None else rules)
        dimensions = list(self.dimensions if dimensions is None else dimensions)
        registry = qe.Registry(dimensions)
        for rule in rules:
            registry.add(rule)
        self.rules, self.dimensions = rules, dimensions
        return registry

    def _replace(self, index: int, rule: qe.Rule) -> None:
        self._keep(self.rules[:index] + [rule] + self.rules[index + 1 :])

    def _shape(self, index: int, space: sp.Space | None) -> dict[str, Any]:
        rule = self.rules[index]
        scope = {k: v for k, v in rule.scope.items() if k != "space"}
        if space is not None:
            scope["space"] = space
        self._replace(index, dataclasses.replace(rule, scope=scope))
        return self.do_state()

    def _names(self, name: str) -> list[str]:
        given = (r.scope.get(name) for r in self.rules)
        names = {n for v in given for n in ([v] if isinstance(v, str) else v or [])}
        return sorted(n for n in names if not set(n) & set("*?["))

    def _rule(self, index: int, space: sp.Space | None) -> dict[str, Any]:
        """What the page shows of one rule, with each value as it is edited."""
        rule = self.rules[index]
        time = rule.scope.get("time")
        wire = qe.TimeDimension().parse_rule(time).to_wire() if time else ("..", "..")
        start, end = ("" if v == ".." else v for v in wire)
        values = {d.name: _text(d, rule.scope.get(d.name)) for d in self.dimensions}
        on_globe = dict.fromkeys(("fill", "outline", "label", "editable", "extent"))
        return {
            "index": index,
            "code": rule.code,
            "category": rule.category or "",
            "title": rule.title,
            "message": rule.message,
            "level": rule.level,
            "time": {"start": start, "end": end},
            "dimensions": values,
            "properties": rule.properties,  # such as an instruction, or references
            "record": json.dumps(rule.to_feature(), indent=2, ensure_ascii=False),
        } | (on_globe if space is None else shapes.on_globe(space))


# ---- old files and dimensions --------------------------------------------------
def upgrade(data: Any) -> tuple[Any, list[dict[str, str]]]:
    """A rule file from before queryearth 0.7 in the 0.7 form, and the labels
    and axis dimensions it declared.

    A code whose prefix the file declares as a category ("groups" before 0.6)
    takes the category's path: OBC001, in OBC in DOMAIN, becomes
    DOMAIN/OBC/OBC001. A record's box becomes its geometry, and a rule without
    a level but with changes, which was info, says so. queryearth refuses what
    does not map, such as an edge rule, naming the rule.
    """
    if not isinstance(data, dict):
        return data, []
    categories = data.pop("categories", None) or data.pop("groups", None) or {}
    declared = data.pop("dimensions", None) or []
    for feature in data.get("features") or []:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            continue
        found = _OLD_CODE.fullmatch(str(props.get("code")))
        path, prefix = [], found and found[1]
        while prefix in categories and prefix not in path:
            path.insert(0, prefix)
            parent = categories[prefix]
            prefix = parent.get("parent") if isinstance(parent, dict) else None
        if path:
            props["code"] = "/".join([*path, props["code"]])
        if isinstance(box := props.pop("box", None), dict):
            east = box["west"] + box["width"]
            space = sp.box(box["west"], box["south"], east, box["north"])
            feature["geometry"] = space.to_json()
        if "level" not in props and props.get("changes"):
            props["level"] = "info"
    kinds = ("labels", "axis")
    return data, [d for d in declared if isinstance(d, dict) and d.get("kind") in kinds]


def infer(
    features: Iterable[Any], declared: Iterable[Mapping[str, str]] = ()
) -> list[dict[str, str]]:
    """The dimensions of a file's rules, as [{name, kind, unit}]: those
    declared, then one for each other name the rules use, from its values. A
    range such as {"lt": 8, "unit": "km"} makes an axis, in the unit a rule
    gives (UNKNOWN when none does), and a name or a list of names makes labels."""
    found = {d["name"]: dict(d) for d in declared}
    named = set(found)
    for feature in features:
        props = feature.get("properties") if isinstance(feature, Mapping) else None
        values = props.get("dimensions") if isinstance(props, Mapping) else None
        for name, value in values.items() if isinstance(values, Mapping) else ():
            if name in named:
                continue
            if isinstance(value, Mapping) and set(value) & BOUNDS:
                axis = found.setdefault(name, {"name": name, "kind": "axis"})
                if axis.get("unit", UNKNOWN) == UNKNOWN:
                    axis["unit"] = value.get("unit") or UNKNOWN
            elif isinstance(value, (str, list)):
                found.setdefault(name, {"name": name, "kind": "labels"})
    return list(found.values())


def _dimension(described: Mapping[str, str]) -> qe.Dimension:
    """A dimension from the page's description: {name, kind, unit}."""
    if described.get("kind") == "axis":
        return qe.Axis(described["name"], described.get("unit") or "")
    if described.get("kind") == "labels":
        return qe.Labels(described["name"])
    raise ValueError(f"a dimension is labels or an axis, not {described!r}")


def _described(dimension: qe.Dimension) -> dict[str, str]:
    if isinstance(dimension, qe.Axis):
        return {"name": dimension.name, "kind": "axis", "unit": dimension.unit}
    return {"name": dimension.name, "kind": "labels"}


def _space(rule: qe.Rule) -> sp.Space | None:
    value = rule.scope.get("space")
    return None if value is None else qe.SpaceDimension().parse_rule(value)


# ---- values as the page shows and types them ------------------------------------
def _number(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() else value


def _names(text: str) -> list[str]:
    return [name.strip() for name in text.split(",") if name.strip()]


def _value(dimension: qe.Dimension, text: str) -> Any:
    """A rule's value on a dimension as typed in its form, or None when empty:
    labels are names separated by commas, and an axis takes bounds such as <8
    or >=2, several separated by commas, or a range 2-8 (from 2 up to, not
    including, 8), written with the axis's unit."""
    text = text.strip()
    if not text:
        return None
    if not isinstance(dimension, qe.Axis):
        return _names(text)
    value = {}
    if match := _RANGE.fullmatch(text):
        value = {"ge": _number(match[1]), "lt": _number(match[2])}
    for part in [] if value else re.split(r"\s*(?:,|\band\b)\s*|\s+(?=[<>≤≥])", text):
        bound = _BOUND.fullmatch(part.strip())
        if bound is None:
            raise ValueError(f"{text!r} is not a range: write {AXIS_HINT}")
        value[_OPS[bound[1]]] = _number(bound[2])
    return value | ({} if dimension.unit == UNKNOWN else {"unit": dimension.unit})


def _text(dimension: qe.Dimension, value: Any) -> str:
    """A rule's value on a dimension as its form shows it, which _value reads."""
    if value is None:
        return ""
    if not isinstance(dimension, qe.Axis):
        return value if isinstance(value, str) else ", ".join(value)
    shown = {k: str(_number(str(v))) for k, v in value.items() if k in BOUNDS}
    if set(shown) == {"ge", "lt"}:
        return f"{shown['ge']}-{shown['lt']}"
    return ", ".join(f"{_SIGNS[k]}{shown[k]}" for k in _SIGNS if k in shown)


def _query_value(dimension: qe.Dimension | None, text: str) -> Any:
    """A query's value as typed: a number or a range such as 5-10 for an axis,
    names separated by commas otherwise."""
    if not isinstance(dimension, qe.Axis):
        return _names(text)
    if match := _RANGE.fullmatch(text):
        return (float(match[1]), float(match[2]))
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{text!r} is not a number or a range such as 5-10") from None
