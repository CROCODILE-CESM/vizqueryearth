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
    member ({"name": "resolution", "kind": "axis", "unit": "km"}); categories
    declares the categories of the codes as queryearth.Registry takes them, each
    prefix with its title, or with its title and parent for a subcategory:
    {"REGION": "Regions", "ITF": {"title": "Indonesian Throughflow", "parent":
    "REGION"}}. Without them, the file's own "dimensions" and "categories"
    members declare them ("groups" in files from before queryearth 0.6). Once
    there are categories, every rule's prefix must be one.

    The file is written as queryearth writes one: a "queryearth" member naming
    the release whose file format it uses (queryearth.FORMAT), its "categories" when
    there are any, and its "dimensions". A file that needs a later queryearth
    than this one is refused with queryearth.LoadError.
    """

    def __init__(
        self,
        collection: Mapping[str, Any] | None = None,
        *,
        dimensions: Iterable[qe.Dimension | Mapping[str, Any]] | None = None,
        categories: Mapping[str, Any] | None = None,
    ) -> None:
        collection = collection or {"type": "FeatureCollection", "features": []}
        if (
            not isinstance(collection, Mapping)
            or collection.get("type") != "FeatureCollection"
        ):
            raise ValueError("a rule file is a GeoJSON FeatureCollection")
        # the categories, called "groups" in files from before queryearth 0.6
        given = collection.get("categories", collection.get("groups"))
        if {"queryearth", "groups"} & collection.keys():
            # queryearth says whether it reads this file's format, and its name
            # for the categories
            named = ("queryearth", "groups", "categories")
            members = {k: collection[k] for k in named if k in collection}
            known = _parents_first(given) if isinstance(given, Mapping) else None
            empty = {"type": "FeatureCollection", "features": []}
            qe.Registry(categories=known).add(empty | members)
        self.collection = copy.deepcopy(dict(collection))
        self.collection.setdefault("features", [])
        if dimensions is None:
            dimensions = self.collection.get("dimensions") or []
        if categories is None:
            categories = given or {}
        self._declare(dimensions, categories)

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

    def category(self, index: int) -> str | None:
        """A rule's category, the prefix of its code (ITF for ITF001), or None when
        queryearth cannot read its code."""
        try:
            return split_code(self.codes[index])[0]
        except ERRORS:
            return None

    def prefixes(self) -> list[str]:
        """The prefixes the rules' codes use, in the order they first appear."""
        found = (self.category(i) for i in range(len(self.features)))
        return list(dict.fromkeys(p for p in found if p is not None))

    def category_paths(self) -> dict[str, list[str]]:
        """Each category with the categories it sits in, outermost first, as
        queryearth gives them: {"ITF": ["REGION", "ITF"], ...}."""
        registry = qe.Registry("vizqueryearth", categories=self.categories)
        return {p: registry.category_path(p) for p in self.categories}

    def order(self) -> list[int]:
        """The positions of the rules, sorted by code: by category, in the order
        the categories are declared, then prefixes that are not categories,
        alphabetically,
        then by number. Codes queryearth cannot read come last."""
        declared = {prefix: n for n, prefix in enumerate(self.categories)}

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

    def record(self, index: int) -> str:
        """One rule's record as JSON text, as text() writes it in the file (there
        indented four more spaces, inside "features")."""
        return json.dumps(self.features[index], indent=2, ensure_ascii=False)

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
        self._declare(dimensions, self.categories)

    def set_categories(self, categories: Mapping[str, Any]) -> None:
        """Declare the categories, in queryearth's form (see RuleFile); the
        file's "categories" member follows. They are put in an order queryearth
        reads, each category after its parent, moving as few as possible.

        Every rule's prefix must stay a category, and every parent a category: a
        category that rules use, or that has subcategories, cannot be removed,
        and the first categories of a file with rules must take in every prefix
        the rules use. Categories cannot sit in each other."""
        if not isinstance(categories, Mapping):
            raise ValueError(
                f"categories map each prefix to a title, not {categories!r}"
            )
        used = self.prefixes()
        gone = [p for p in self.categories if p not in categories and p in used]
        if gone:
            raise ValueError(
                f"{', '.join(gone)} still {'has' if len(gone) == 1 else 'have'} "
                "rules: move them to another category or delete them first"
            )
        for removed in (p for p in self.categories if p not in categories):
            inside = [p for p, v in categories.items() if _parent(v) == removed]
            if inside:
                raise ValueError(
                    f"{removed} has subcategories: {', '.join(inside)}; move them "
                    "to another category or remove them first"
                )
        missing = [p for p in used if p not in categories] if categories else []
        if missing:
            raise ValueError(
                "once there are categories, every rule's prefix must be one: add "
                f"{', '.join(missing)} too"
            )
        self._declare(self.dimensions, categories)

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
        """Add a rule with the code queryearth gives next in a category, such as
        ITF009 after ITF008; returns its position. Without a prefix, the first
        category's, or in a file without categories the prefix of the last rule's
        code, or RULE in an empty file."""
        if prefix is None:
            last = [p for p in map(self.category, range(len(self.features))) if p]
            first = next(iter(self.categories), None)
            prefix = first or (last[-1] if last else "RULE")
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

    def move(self, index: int, prefix: str) -> str:
        """Move a rule to another category: it takes the code queryearth gives
        next there, and keeps its old code in its "aliases", so the old code
        still finds it and is never given again. Returns the new code."""
        old = self.codes[index]
        if self.category(index) == prefix:
            raise ValueError(f"{old} is already in {prefix}")
        code = self._numbering().next_code(prefix)
        feature = copy.deepcopy(self.features[index])
        props = feature["properties"]
        aliases = props.get("aliases") or []
        aliases = [aliases] if isinstance(aliases, str) else list(aliases)
        props["code"] = code
        props["aliases"] = aliases + [old] if old not in aliases else aliases
        if feature.get("id") == old:
            feature["id"] = code  # an id that named the old code follows it
        self._keep(index, feature)
        return code

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
            "vizqueryearth", dimensions=self.dimensions, categories=self.categories
        )

    def _numbering(self) -> qe.Registry:
        """A Registry holding a stand-in for every rule whose code queryearth
        reads, refused rules too, with the codes it keeps as aliases or
        supersedes, to ask queryearth for the next code."""
        registry = qe.Registry("vizqueryearth", categories=self.categories)
        for feature in self.features:
            props = feature.get("properties") or {}
            code = props.get("code")
            stand_in = {"code": code, "title": "-", "message": "-"}
            kept = {k: props[k] for k in ("aliases", "supersedes") if k in props}
            for tried in (stand_in | kept, stand_in):
                try:
                    registry.add(
                        {"type": "Feature", "geometry": None, "properties": tried}
                    )
                    break
                except ERRORS:
                    pass
        return registry

    def _declare(
        self,
        dimensions: Iterable[qe.Dimension | Mapping[str, Any]],
        categories: Mapping[str, Any],
    ) -> None:
        """Check dimensions and categories with queryearth, keep them, and write
        them into the file, with the "queryearth" member, before the features."""
        if isinstance(dimensions, (str, Mapping)) or not isinstance(
            dimensions, Iterable
        ):
            raise ValueError(f"dimensions are a list, not {dimensions!r}")
        if not isinstance(categories, Mapping):
            raise ValueError(
                f"categories map each prefix to a title, not {categories!r}"
            )
        dimensions = tuple(
            d if isinstance(d, qe.Dimension) else dimension_from(d) for d in dimensions
        )
        registry = qe.Registry(  # checks them
            "vizqueryearth",
            dimensions=dimensions,
            categories=_parents_first(categories),
        )
        self.dimensions, self.categories = dimensions, registry.categories
        written = {"queryearth": qe.FORMAT}
        if self.categories:
            written["categories"] = registry.categories
        written["dimensions"] = [describe_dimension(d) for d in dimensions]
        before, after, features = {}, {}, None
        for key, value in self.collection.items():  # other members stay put
            if key == "features":
                features = value
            elif key not in (
                "type",
                "queryearth",
                "categories",
                "groups",
                "dimensions",
            ):
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


def _parent(value: Any) -> str | None:
    """A category's parent, from its title or {"title", "parent"}."""
    return value.get("parent") if isinstance(value, Mapping) else None


def _parents_first(categories: Mapping[str, Any]) -> dict[str, Any]:
    """Categories in an order queryearth reads: each after its parent. One is
    moved only when its parent comes later, to just after the parent."""
    for prefix, value in categories.items():
        parent = _parent(value)
        if parent is not None and parent not in categories:
            raise ValueError(f"{prefix} sits in {parent}, which is not a category")
    ordered: dict[str, Any] = {}
    waiting: dict[str, list[str]] = {}  # a parent's children placed before it

    def place(prefix: str) -> None:
        ordered[prefix] = categories[prefix]
        for child in waiting.pop(prefix, []):
            place(child)

    for prefix, value in categories.items():
        parent = _parent(value)
        if parent is None or parent in ordered:
            place(prefix)
        else:
            waiting.setdefault(parent, []).append(prefix)
    if len(ordered) < len(categories):  # what is left sits in itself, round a loop
        loop = [next(p for p in categories if p not in ordered)]
        while (parent := _parent(categories[loop[-1]])) not in loop:
            loop.append(parent)
        loop = loop[loop.index(parent) :] + [parent]
        raise ValueError(f"categories cannot sit in each other: {' in '.join(loop)}")
    return ordered


def _put(props: dict[str, Any], name: str, value: Any) -> None:
    """Set a property, or remove it when value is None."""
    if value is None:
        props.pop(name, None)
    else:
        props[name] = value
