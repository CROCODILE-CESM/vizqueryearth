"""Jupyter widgets: draw() for one shape, and Editor for the shapes of a rule file.

Both put Leaflet-Geoman's drawing tools on an ipyleaflet map. Whatever is on the
drawing layer comes back through the control's synced `data` list and becomes a
Shape (vizqueryearth.shapes). queryearth checks every shape and every rule.
"""

from __future__ import annotations

import copy
import html
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import ipyleaflet as L
import ipywidgets as W
import queryearth as qe
import shapely
import shapely.geometry
from queryearth.objects import KINDS

from vizqueryearth.shapes import Shape, from_leaflet, to_leaflet

__all__ = ["draw", "Drawing", "Editor"]

_DRAWN = {"color": "#2f55c4", "weight": 2, "fillOpacity": 0.15}
_OTHER = {"color": "#56666e", "weight": 1, "fillOpacity": 0.08, "dashArray": "4"}
_WIDE = W.Layout(width="100%")
_NUMBERED = re.compile(r"(.*?)(\d{3,4})")  # a rule code: prefix, then number


def _describe(shape: Shape | None) -> str:
    """One line saying what a shape is."""
    if shape is None:
        return "No shape: the rule applies everywhere."
    if shape.box is not None:
        b = shape.box
        return (
            f"Box: west {b['west']}°, width {b['width']}°, "
            f"latitude {b['south']}° to {b['north']}°."
        )
    parts = len(getattr(shape.space.geometry, "geoms", [None]))
    return f"Polygon in {parts} part{'s' * (parts > 1)} (split at ±180 when saved)."


class _ShapeMap(W.VBox):
    """A map whose drawing layer holds one shape."""

    def __init__(self) -> None:
        self.map = L.Map(
            center=(20, 0),
            zoom=2,
            scroll_wheel_zoom=True,
            layout=W.Layout(height="460px", width="100%"),
        )
        path = {"pathOptions": _DRAWN}
        self.control = L.GeomanDrawControl(
            polygon=path,
            rectangle=path,
            polyline={},
            circlemarker={},
            edit=True,
            drag=True,
            remove=True,
            cut=False,  # no holes in version 1
            rotate=False,
        )
        self.map.add(self.control)
        self.status = W.HTML()
        self._quiet = False
        self.control.observe(self._on_data, names="data")
        super().__init__([self.map, self.status])

    def _show(self, shape: Shape | None) -> None:
        """Put a shape on the drawing layer, without treating it as a drawing."""
        drawn = [] if shape is None else to_leaflet(shape)
        for part in drawn:
            part["properties"] = {"style": _DRAWN}
        self._quiet = True
        try:
            self.control.data = drawn
        finally:
            self._quiet = False

    def _on_data(self, change: dict[str, Any]) -> None:
        """The drawing layer changed in the browser."""
        if self._quiet:
            return
        try:
            shape = from_leaflet(change["new"])
        except ValueError as err:
            self._say(f"queryearth cannot use this shape: {err}", error=True)
            return
        self._drawn(shape)

    def _drawn(self, shape: Shape | None) -> None:
        raise NotImplementedError

    def _say(self, text: str, error: bool = False) -> None:
        color = "#b3261e" if error else "inherit"
        self.status.value = f'<div style="color:{color}">{html.escape(text)}</div>'


class Drawing(_ShapeMap):
    """A map to draw one shape on; read it from .shape in the next cell."""

    def __init__(self) -> None:
        super().__init__()
        self.shape: Shape | None = None
        self._say("Draw a polygon or a rectangle. Drawing more shapes adds parts.")

    def _drawn(self, shape: Shape | None) -> None:
        self.shape = shape
        self._say(_describe(shape))

    @property
    def space(self) -> qe.Space | None:
        """The shape as a queryearth Space, for Scope(space=...)."""
        return None if self.shape is None else self.shape.space

    @property
    def geometry(self) -> dict[str, Any] | None:
        """The GeoJSON geometry to put in a rule file; None for a box."""
        return None if self.shape is None else self.shape.geometry

    @property
    def box(self) -> dict[str, float] | None:
        """The record box to put in a rule file; None for a polygon."""
        return None if self.shape is None else self.shape.box


def draw() -> Drawing:
    """Show a map to draw one polygon or box on; read it from .shape later."""
    return Drawing()


class Editor(_ShapeMap):
    """Draw the shapes of the rules in one rule file.

    Pick a rule in the list or click its shape, then draw, edit, drag or delete
    shapes on the map; New rule adds one. The form holds code, kind, title and
    message; everything else stays as it is in the file. Changes are kept when
    you pick another rule or save. dimensions declares the dimensions the
    rules use besides space and time, as for queryearth.Registry; the file is
    checked against them when saved.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        dimensions: Iterable[Any] = (),
    ) -> None:
        self.path = Path(path)
        self._dimensions = tuple(dimensions)
        self._collection = self._read(self.path)
        self.features: list[dict[str, Any]] = self._collection["features"]
        self._index: int | None = None  # the rule in the form; None for a new one
        self._shape: Shape | None = None  # its shape as drawn
        self._shape_changed = False
        super().__init__()
        self._others = L.GeoJSON(
            data=_collection([]), style=_OTHER, hover_style={"weight": 3}
        )
        self._others.on_click(self._clicked)
        self._labels = L.LayerGroup()
        self.map.add(self._others)
        self.map.add(self._labels)
        self.map.layout = W.Layout(height="520px", width="65%")
        self.children = [W.HBox([self.map, self._form()]), self.status]
        problems = self._check_all()
        self._refresh()
        if self.features:
            self.select(0)
        else:
            self._fill({})
            self._say("No rules yet: click New rule.")
        if problems:
            self._say("Problems in the file: " + "; ".join(problems), error=True)

    # ---- the file ----------------------------------------------------------------
    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"type": "FeatureCollection", "features": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
            raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
        return data

    def _registry(self) -> qe.Registry:
        return qe.Registry("vizqueryearth", dimensions=self._dimensions)

    def _check_all(self) -> list[str]:
        """Problems queryearth finds in the file as it stands."""
        try:
            self._registry().add(self._collection)
        except qe.LoadError as err:
            return list(err.problems)
        return []

    def save(self, path: str | os.PathLike[str] | None = None) -> None:
        """Keep the form's changes, check the whole file with queryearth, write it."""
        if self._pending():
            self.apply()
        path = Path(path) if path is not None else self.path
        problems = self._check_all()
        if problems:
            self._say("Not saved: " + "; ".join(problems), error=True)
            raise qe.LoadError(problems)
        text = json.dumps(self._collection, indent=2, ensure_ascii=False) + "\n"
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)  # never leaves a half-written file
        self._say(f"Saved {len(self.features)} rules to {path}.")

    # ---- rules -------------------------------------------------------------------
    @property
    def rules(self) -> list[str]:
        """The codes of the rules in the file, in order."""
        return [f.get("properties", {}).get("code", "") for f in self.features]

    def select(self, rule: str | int) -> None:
        """Show one rule, by code or position; changes to the last one are kept."""
        index = self.rules.index(rule) if isinstance(rule, str) else rule
        if index != self._index and self._pending():
            self.apply()
        self._index = index
        feature = self.features[index]
        self._shape = _shape_of(feature)
        self._shape_changed = False
        self._fill(feature["properties"])
        self._show(self._shape)
        self._refresh()
        self._say(_describe(self._shape))

    def new(self) -> str:
        """Add a rule with the next free code, such as DEMO005 after DEMO004, and
        select it; then fill in its fields and draw its shape."""
        code = _next_code(self.rules)
        self.add(code, title="New rule", message="Say what this rule is about.")
        self._say(f"Added {code}: fill in its fields, draw its shape, then Save.")
        return code

    def add(
        self,
        code: str,
        kind: str = "warning",
        title: str = "",
        message: str = "",
        **properties: Any,
    ) -> None:
        """Add a rule without a shape and select it; draw its shape next."""
        if code in self.rules:
            raise ValueError(f"{code} is already in the file")
        props = {"code": code, "kind": kind, "title": title, "message": message}
        feature = {"type": "Feature", "id": code, "geometry": None, "time": None}
        feature["properties"] = props | properties
        self._check(feature)
        self.features.append(feature)
        self.select(len(self.features) - 1)

    def set_shape(self, shape: Shape | None) -> None:
        """Give the selected rule a shape, such as vq.arctic(66.5); None for none."""
        self._shape = shape
        self._shape_changed = True
        self._show(shape)
        self._say(_describe(shape))

    def apply(self) -> str:
        """Check the form and the shape with queryearth and keep them in the file."""
        if self._index is None:
            raise self._fail("No rule selected: pick one or click New rule.")
        feature = self._edited()
        code = feature["properties"]["code"]
        clash = [i for i, c in enumerate(self.rules) if c == code and i != self._index]
        if clash:
            raise self._fail(f"{code} is already in the file")
        try:
            self._check(feature)
        except (ValueError, TypeError, KeyError) as err:
            raise self._fail(f"{code}: {err}") from err
        self.features[self._index] = feature
        self._shape_changed = False
        self._refresh()
        self._say(f"Kept {code}. Save writes the file.")
        return code

    def _check(self, feature: dict[str, Any]) -> None:
        self._registry().add(feature)  # the record, then its names

    def _fail(self, text: str) -> ValueError:
        self._say(text, error=True)
        return ValueError(text)

    def _edited(self) -> dict[str, Any]:
        """The selected rule with the form's values and the drawn shape."""
        feature = copy.deepcopy(self.features[self._index])
        props = feature["properties"]
        old_code = props.get("code")
        props.update(
            code=self._code.value.strip(),
            kind=self._kind.value,
            title=self._title.value,
            message=self._message.value,
        )
        if "id" in feature and feature["id"] == old_code:
            feature["id"] = props["code"]  # an id that named the old code follows it
        if self._shape_changed:
            shape = self._shape
            feature["geometry"] = None if shape is None else shape.geometry
            if shape is not None and shape.box is not None:
                props["box"] = shape.box
            else:
                props.pop("box", None)
        return feature

    def _pending(self) -> bool:
        """Whether the form or the shape differs from the stored rule."""
        if self._index is None:
            return False
        return self._shape_changed or self._edited() != self.features[self._index]

    def _drawn(self, shape: Shape | None) -> None:
        if self._index is None:
            self._say("Click New rule first, then draw its shape.", error=True)
            return
        self._shape = shape
        self._shape_changed = True
        self._say(_describe(shape))

    # ---- the form ----------------------------------------------------------------
    def _form(self) -> W.VBox:
        self._picker = W.Dropdown(description="Rule", layout=_WIDE)
        self._picker.observe(self._picked, names="value")
        self._code = W.Text(description="Code", layout=_WIDE)
        self._kind = W.Dropdown(description="Kind", options=list(KINDS), layout=_WIDE)
        self._title = W.Text(description="Title", layout=_WIDE)
        self._message = W.Textarea(description="Message", rows=4, layout=_WIDE)
        new, save = W.Button(description="New rule"), W.Button(description="Save")
        new.on_click(lambda _: _quietly(self.new))
        save.on_click(lambda _: _quietly(self.save))
        save.button_style = "primary"
        fields = [self._picker, self._code, self._kind, self._title, self._message]
        return W.VBox(
            [*fields, W.HBox([new, save])],
            layout=W.Layout(width="35%", padding="0 0 0 12px"),
        )

    def _fill(self, props: Mapping[str, Any]) -> None:
        """Show a rule's fields in the form."""
        kind = props.get("kind")
        self._code.value = props.get("code", "")
        self._kind.value = kind if kind in KINDS else KINDS[0]
        self._title.value = props.get("title", "")
        self._message.value = props.get("message", "")

    def _picked(self, change: dict[str, Any]) -> None:
        if change["new"] is not None and change["new"] != self._index:
            _quietly(self.select, change["new"])

    def _clicked(self, **event: Any) -> None:
        index = (event.get("properties") or {}).get("index")
        if index is not None:
            _quietly(self.select, index)

    def _refresh(self) -> None:
        """Redraw the other rules and their labels, and the rule list."""
        shapes, labels = [], []
        for i, feature in enumerate(self.features):
            shape = _shape_or_none(feature)
            if i == self._index or shape is None:
                continue
            code = feature["properties"].get("code", f"feature {i}")
            parts = to_leaflet(shape)
            for part in parts:
                part["properties"] = {"index": i, "code": code}
            shapes += parts
            if parts:
                labels.append(_label(code, parts[0]["geometry"], i, self._clicked))
        self._others.data = _collection(shapes)
        old = self._labels.layers
        self._labels.layers = tuple(labels)
        for marker in old:  # free the old labels' widgets in the browser too
            marker.icon.close()
            marker.close()
        options = [
            (f"{c or f'feature {i}'}{' (everywhere)' * (_shape_or_none(f) is None)}", i)
            for i, (c, f) in enumerate(zip(self.rules, self.features))
        ]
        self._picker.unobserve(self._picked, names="value")
        self._picker.options = options
        self._picker.value = self._index
        self._picker.observe(self._picked, names="value")


def _next_code(codes: list[str]) -> str:
    """The code after the last numbered one: DEMO005 after DEMO004, ERA5-015 after
    ERA5-014; RULE001 in an empty file."""
    numbered = [m for c in codes if (m := _NUMBERED.fullmatch(c))]
    if not numbered:
        return "RULE001"
    prefix = numbered[-1].group(1)
    same = [m for m in numbered if m.group(1) == prefix]
    width = len(same[-1].group(2))
    return f"{prefix}{max(int(m.group(2)) for m in same) + 1:0{width}d}"


def _shape_of(feature: Mapping[str, Any]) -> Shape | None:
    """A record's shape as it is in the file, or None when it has none."""
    box = (feature.get("properties") or {}).get("box")
    if box is not None:
        return Shape(box=box)
    if feature.get("geometry") is not None:
        return Shape(geometry=feature["geometry"])
    return None


def _shape_or_none(feature: Mapping[str, Any]) -> Shape | None:
    """As _shape_of, with None for a shape queryearth refuses (listed as a problem)."""
    try:
        return _shape_of(feature)
    except ValueError:
        return None


def _label(
    code: str, geometry: Mapping[str, Any], index: int, clicked: Any
) -> L.Marker:
    point = shapely.geometry.shape(geometry).point_on_surface()
    icon = L.DivIcon(html=html.escape(code), icon_size=[70, 18], icon_anchor=[35, 9])
    marker = L.Marker(location=(point.y, point.x), icon=icon, draggable=False)
    marker.on_click(lambda **event: clicked(properties={"index": index}))
    return marker


def _collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _quietly(method: Any, *args: Any) -> None:
    """Run a button's action; its error is already shown under the map."""
    try:
        method(*args)
    except (ValueError, TypeError, KeyError, qe.LoadError):
        pass
