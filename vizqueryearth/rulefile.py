"""A rule file being edited, checked by queryearth at every step.

The page in the browser and Python scripts use the same RuleFile, so the page
can never save a file that queryearth would refuse or read differently.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import queryearth as qe
from queryearth.dimensions import describe_dimension, dimension_from
from queryearth.rules import split_code

from vizqueryearth.shapes import Shape

__all__ = ["RuleFile", "guess_dimensions"]

ERRORS = (ValueError, TypeError, KeyError)  # what queryearth raises for a bad rule
EDITED = (
    "code",
    "level",
    "title",
    "message",
    "time",
    "months",
    "dimensions",
    "changes",
    "edge",
)
_RANGE_KEYS = {"gt", "ge", "lt", "le", "unit"}
_VERSION_KEYS = {"introduced", "fixed", "last_affected", "versions"}


def guess_dimensions(collection: Mapping[str, Any]) -> list[dict[str, str]]:
    """The dimensions a file's rules use, guessed from how they are written, for
    a file that does not declare them: ranges such as {"lt": 10} make an axis,
    version ranges make versions, and anything else is labels. An axis takes its
    unit from the rules' "unit", or "unknown" when they give none.

    The result is in the form of a rule file's "dimensions" member."""
    found: dict[str, dict[str, str]] = {}
    for feature in collection.get("features", []):
        given = (feature.get("properties") or {}).get("dimensions") or {}
        for name, value in given.items():
            if name in found:
                continue
            items = [value] if isinstance(value, Mapping) else value
            keys = set()
            if isinstance(items, list):
                keys = {k for v in items if isinstance(v, Mapping) for k in v}
            if keys and keys <= _RANGE_KEYS:
                units = [v.get("unit") for v in items if v.get("unit")]
                unit = units[0] if units else "unknown"
                found[name] = {"name": name, "kind": "axis", "unit": unit}
            elif keys and keys <= _VERSION_KEYS:
                found[name] = {"name": name, "kind": "versions"}
            else:
                found[name] = {"name": name, "kind": "labels"}
    return list(found.values())


class RuleFile:
    """The rules of one rule file, edited one rule at a time.

    Every edit is checked with queryearth before it is kept, and text() checks
    the whole file before writing it. Rules you do not edit are written back as
    they were read.

    dimensions declares the dimensions the rules use besides space and time, as
    queryearth Dimension objects or in the form of a rule file's "dimensions"
    member ({"name": "resolution", "kind": "axis", "unit": "km"}); groups
    declares the code groups, prefix to title ({"ITF": "Indonesian
    Throughflow"}), as for queryearth.Registry. Without them, the file's own
    "dimensions" and "groups" members declare them. Once there are groups, every
    rule's prefix must be one.

    The file is written as queryearth writes one: a "queryearth" member naming
    the release whose file format it uses (queryearth.FORMAT), its "groups" when
    there are any, and its "dimensions". A file that needs a later queryearth
    than this one is refused with queryearth.LoadError.
    """

    def __init__(
        self,
        collection: Mapping[str, Any] | None = None,
        *,
        dimensions: Iterable[qe.Dimension | Mapping[str, Any]] | None = None,
        groups: Mapping[str, str] | None = None,
    ) -> None:
        collection = collection or {"type": "FeatureCollection", "features": []}
        if (
            not isinstance(collection, Mapping)
            or collection.get("type") != "FeatureCollection"
        ):
            raise ValueError("a rule file is a GeoJSON FeatureCollection")
        if "queryearth" in collection:  # queryearth says whether it can read it
            empty = {"type": "FeatureCollection", "features": []}
            qe.Registry().add(empty | {"queryearth": collection["queryearth"]})
        self.collection = copy.deepcopy(dict(collection))
        self.collection.setdefault("features", [])
        if dimensions is None:
            dimensions = self.collection.get("dimensions") or []
        if groups is None:
            groups = self.collection.get("groups") or {}
        self._declare(dimensions, groups)

    @classmethod
    def from_text(cls, text: str, **kwargs: Any) -> RuleFile:
        """A rule file from its JSON text."""
        return cls(json.loads(text), **kwargs)

    @classmethod
    def read(cls, path: str | os.PathLike[str], **kwargs: Any) -> RuleFile:
        """A rule file from disk; an empty one if the file does not exist yet."""
        path = Path(path)
        if not path.exists():
            return cls(**kwargs)
        return cls.from_text(path.read_text(encoding="utf-8"), **kwargs)

    def write(self, path: str | os.PathLike[str]) -> None:
        """Check the whole file with queryearth, then write it in one step."""
        path = Path(path)
        text = self.text()
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)  # never leaves a half-written file

    # ---- reading -----------------------------------------------------------------
    @property
    def features(self) -> list[dict[str, Any]]:
        return self.collection["features"]

    @property
    def codes(self) -> list[str]:
        """The codes of the rules, in file order."""
        return [(f.get("properties") or {}).get("code", "") for f in self.features]

    def registry(self) -> qe.Registry:
        """A Registry holding every rule; raises queryearth.LoadError on problems."""
        registry = self._registry()
        registry.add(self.collection)
        return registry

    def group(self, index: int) -> str | None:
        """A rule's group, the prefix of its code (ITF for ITF001), or None when
        queryearth cannot read its code."""
        try:
            return split_code(self.codes[index])[0]
        except ERRORS:
            return None

    def prefixes(self) -> list[str]:
        """The prefixes the rules' codes use, in the order they first appear."""
        found = (self.group(i) for i in range(len(self.features)))
        return list(dict.fromkeys(p for p in found if p is not None))

    def order(self) -> list[int]:
        """The positions of the rules, sorted by code: by group, in the order the
        groups are declared, then prefixes that are not groups, alphabetically,
        then by number. Codes queryearth cannot read come last."""
        declared = {prefix: n for n, prefix in enumerate(self.groups)}

        def key(index: int) -> tuple[int, int, str, int]:
            code = self.codes[index]
            try:
                prefix, number = split_code(code)
            except ERRORS:
                return (2, 0, str(code), 0)
            if prefix in declared:
                return (0, declared[prefix], "", number)
            return (1, 0, prefix, number)

        return sorted(range(len(self.features)), key=key)

    def problems(self) -> list[str]:
        """What queryearth refuses in the file as it stands."""
        try:
            self.registry()
        except qe.LoadError as err:
            return list(err.problems)
        except ERRORS as err:
            return [str(err)]
        return []

    def problem(self, index: int) -> str | None:
        """What queryearth refuses in one rule, or None."""
        try:
            self._check(self.features[index])
        except ERRORS as err:
            return str(err)
        return None

    def text(self) -> str:
        """The file as JSON text, after checking it all with queryearth."""
        self.registry()
        return json.dumps(self.collection, indent=2, ensure_ascii=False) + "\n"

    def shape(self, index: int) -> Shape | None:
        """A rule's shape, or None when it has none or queryearth refuses it."""
        try:
            return Shape.of(self.features[index])
        except ERRORS:
            return None

    def level(self, index: int) -> str:
        """A rule's level as a lower-case name, with the default filled in:
        warning without changes, info with them."""
        props = self.features[index].get("properties") or {}
        level = props.get("level")
        if level is None:
            return "info" if props.get("changes") else "warning"
        return (
            logging.getLevelName(level) if isinstance(level, int) else level
        ).lower()

    def accepted(self) -> qe.Registry:
        """A Registry holding the rules queryearth accepts; the rules it refuses
        (see problems()) are left out."""
        registry = self._registry()
        for feature in self.features:
            try:
                registry.add(feature)
            except ERRORS:
                pass
        return registry

    def query(self, **fields: Any) -> list[qe.Finding]:
        """Registry.query() over the rules queryearth accepts."""
        return self.accepted().query(**fields)

    # ---- editing -----------------------------------------------------------------
    def set_dimensions(
        self, dimensions: Iterable[qe.Dimension | Mapping[str, Any]]
    ) -> None:
        """Declare the dimensions the rules use, as Dimension objects or in the
        form of the file's "dimensions" member, which follows. Rules that use a
        name no longer declared become problems()."""
        self._declare(dimensions, self.groups)

    def set_groups(self, groups: Mapping[str, str]) -> None:
        """Declare the code groups, prefix to title, in order; the file's "groups"
        member follows. Every rule's prefix must stay a group: a group that rules
        use cannot be removed, and the first groups of a file with rules must
        take in every prefix the rules use."""
        if not isinstance(groups, Mapping):
            raise ValueError(f"groups map each prefix to a title, not {groups!r}")
        used = self.prefixes()
        gone = [p for p in self.groups if p not in groups and p in used]
        if gone:
            raise ValueError(
                f"rules still use {', '.join(gone)}: change their codes or delete "
                "them first"
            )
        missing = [p for p in used if p not in groups] if groups else []
        if missing:
            raise ValueError(
                "once there are groups, every rule's prefix must be one: add "
                f"{', '.join(missing)} too"
            )
        self._declare(self.dimensions, groups)

    def add(
        self, code: str, title: str = "", message: str = "", **properties: Any
    ) -> int:
        """Add a rule without a shape; returns its position."""
        props = {"code": code, "title": title, "message": message} | properties
        feature = {"type": "Feature", "id": code, "geometry": None, "time": None}
        feature["properties"] = props
        self._keep(len(self.features), feature)
        return len(self.features) - 1

    def new(self, prefix: str | None = None) -> int:
        """Add a rule with the code queryearth gives next in a group, such as
        ITF009 after ITF008; returns its position. Without a prefix, the first
        group's, or in a file without groups the prefix of the last rule's code,
        or RULE in an empty file."""
        if prefix is None:
            last = [p for p in map(self.group, range(len(self.features))) if p]
            prefix = next(iter(self.groups), None) or (last[-1] if last else "RULE")
        code = self._numbering().next_code(prefix)
        return self.add(code, title="New rule", message="Say what this rule is about.")

    def update(self, index: int, **fields: Any) -> None:
        """Change some of a rule's fields; the others are kept as they are.

        - code, title, message: text.
        - level: "info", "warning" or "error"; None or "" is the default,
          warning without changes and info with them.
        - time: [start, end], dates or times, with None, "" or ".." for an open
          end; both open means always. It replaces the rule's time member and
          drops its periods, time_start and time_end.
        - months: the months of every year the rule applies, such as [12, 1, 2];
          empty means every month.
        - dimensions: {name: value} as a record writes it, such as
          {"product": ["era5"], "resolution": {"lt": 10}}; a value of None, ""
          or [] removes that name. Names not given are kept.
        - changes: a list of {target, key, value, rationale}; empty for none.
        - edge: True for a rule that applies where a domain's edge meets its
          shape, rather than wherever they overlap.
        """
        unknown = set(fields) - set(EDITED)
        if unknown:
            raise ValueError(
                f"{', '.join(EDITED)} are edited here, not {sorted(unknown)}"
            )
        feature = copy.deepcopy(self.features[index])
        props = feature["properties"]
        old_code = props.get("code")
        for name in ("code", "title", "message"):
            if name in fields:
                props[name] = fields[name].strip() if name == "code" else fields[name]
        if "level" in fields:
            _put(props, "level", fields["level"] or None)
        if "time" in fields:
            start, end = fields["time"] or (None, None)
            start, end = start or "..", end or ".."
            if (start, end) == ("..", ".."):
                feature["time"] = None
            else:
                feature["time"] = {"interval": [start, end]}
            for name in ("periods", "time_start", "time_end"):
                props.pop(name, None)
        if "months" in fields:
            months = list(fields["months"] or [])
            _put(props, "recurrence", {"months": months} if months else None)
        if "dimensions" in fields:
            given = dict(props.get("dimensions") or {})
            for name, value in fields["dimensions"].items():
                if value is None or value == "" or value == []:
                    given.pop(name, None)
                else:
                    given[name] = value
            _put(props, "dimensions", given or None)
        if "changes" in fields:
            _put(props, "changes", [dict(c) for c in fields["changes"] or []] or None)
        if "edge" in fields:
            if not isinstance(fields["edge"], bool):
                raise ValueError(f"edge is true or false, not {fields['edge']!r}")
            _put(props, "edge", True if fields["edge"] else None)
        if feature.get("id") == old_code:
            feature["id"] = props["code"]  # an id that named the old code follows it
        self._keep(index, feature)

    def set_shape(self, index: int, shape: Shape | None) -> None:
        """Give a rule a shape, such as from_drawn(...) or arctic(66.5); None for none."""
        feature = copy.deepcopy(self.features[index])
        props = feature["properties"]
        feature["geometry"] = None if shape is None else shape.geometry
        if shape is not None and shape.box is not None:
            props["box"] = shape.box
        else:
            props.pop("box", None)
        self._keep(index, feature)

    def delete(self, index: int) -> None:
        del self.features[index]

    def _registry(self) -> qe.Registry:
        return qe.Registry(
            "vizqueryearth", dimensions=self.dimensions, groups=self.groups
        )

    def _numbering(self) -> qe.Registry:
        """A Registry holding a stand-in for every rule whose code queryearth
        reads, refused rules too, to ask queryearth for the next code."""
        registry = qe.Registry("vizqueryearth", groups=self.groups)
        for code in self.codes:
            stand_in = {"code": code, "title": code, "message": code}
            try:
                registry.add(
                    {"type": "Feature", "geometry": None, "properties": stand_in}
                )
            except ERRORS:
                pass
        return registry

    def _declare(
        self,
        dimensions: Iterable[qe.Dimension | Mapping[str, Any]],
        groups: Mapping[str, str],
    ) -> None:
        """Check dimensions and groups with queryearth, keep them, and write them
        into the file, with the "queryearth" member, before the features."""
        if isinstance(dimensions, (str, Mapping)) or not isinstance(
            dimensions, Iterable
        ):
            raise ValueError(f"dimensions are a list, not {dimensions!r}")
        if not isinstance(groups, Mapping):
            raise ValueError(f"groups map each prefix to a title, not {groups!r}")
        dimensions = tuple(
            d if isinstance(d, qe.Dimension) else dimension_from(d) for d in dimensions
        )
        groups = dict(groups)
        qe.Registry("vizqueryearth", dimensions=dimensions, groups=groups)  # checks
        self.dimensions, self.groups = dimensions, groups
        written = {"queryearth": qe.FORMAT}
        if groups:
            written["groups"] = dict(groups)
        written["dimensions"] = [describe_dimension(d) for d in dimensions]
        before, after, features = {}, {}, None
        for key, value in self.collection.items():  # other members stay put
            if key == "features":
                features = value
            elif key not in ("type", "queryearth", "groups", "dimensions"):
                (before if features is None else after)[key] = value
        self.collection = {"type": self.collection["type"]} | before | written
        self.collection |= {"features": features} | after

    def _check(self, feature: Mapping[str, Any]) -> None:
        self._registry().add(feature)

    def _keep(self, index: int, feature: dict[str, Any]) -> None:
        """Check one rule with queryearth and store it at index (appending at the end)."""
        code = feature["properties"].get("code")
        if any(c == code and i != index for i, c in enumerate(self.codes)):
            raise ValueError(f"{code} is already in the file")
        self._check(feature)
        if index == len(self.features):
            self.features.append(feature)
        else:
            self.features[index] = feature


def _put(props: dict[str, Any], name: str, value: Any) -> None:
    """Set a property, or remove it when value is None."""
    if value is None:
        props.pop(name, None)
    else:
        props[name] = value
