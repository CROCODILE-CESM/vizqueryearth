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
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import ipyleaflet as L
import ipywidgets as W
import queryearth as qe
import shapely
import shapely.geometry
from queryearth.objects import KINDS

from vizqueryearth.shapes import Shape, antarctic, arctic, from_leaflet, to_leaflet

__all__ = ["draw", "Drawing", "Editor"]

_DRAWN = {"color": "#2f55c4", "weight": 2, "fillOpacity": 0.15}
_OTHER = {"color": "#56666e", "weight": 1, "fillOpacity": 0.08, "dashArray": "4"}
_FIXED = {"color": "#2f55c4", "weight": 2, "fillOpacity": 0.1, "dashArray": "6"}
_LEVELS = [
    ("default", ""),
    ("info", "info"),
    ("warning", "warning"),
    ("error", "error"),
]
_FORM = {"code", "kind", "level", "title", "message", "facets", "box"}
_WIDE = W.Layout(width="100%")


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

    def __init__(self, **kwargs: Any) -> None:
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
        self._fixed = L.GeoJSON(
            data=_collection([]), style=_FIXED
        )  # past the map's edge
        self.map.add(self._fixed)
        self.map.add(self.control)
        self.status = W.HTML()
        self._quiet = False
        self.control.observe(self._on_data, names="data")
        super().__init__([self.map, self.status], **kwargs)

    def _show(self, shape: Shape | None) -> None:
        """Put a shape on the map: on the drawing layer when it fits on the map."""
        self._quiet = True
        try:
            editable = shape is not None and shape.editable
            drawn = to_leaflet(shape) if editable else []
            for part in drawn:
                part["properties"] = {"style": _DRAWN}
            self.control.data = drawn
            fixed = to_leaflet(shape) if shape is not None and not editable else []
            self._fixed.data = _collection(fixed)
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
        self._fixed.data = _collection([])
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
    """Draw and edit the shapes of the rules in one rule file.

    axes, facets and dimensions declare the ruleset's vocabulary, as for
    queryearth.Registry; the file is checked against it when saved. vocabulary
    adds facet values to offer, beyond those the file already uses.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        axes: Iterable[qe.Axis] = (),
        facets: Iterable[str] = qe.Registry.FACETS,
        dimensions: Iterable[Any] = (),
        vocabulary: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self.path = Path(path)
        self._declared = {
            "axes": tuple(axes),
            "facets": tuple(facets),
            "dimensions": tuple(dimensions),
        }
        self._collection = self._read(self.path)
        self.features: list[dict[str, Any]] = self._collection["features"]
        self._index: int | None = None  # the rule shown in the form; None for a new one
        self._shape: Shape | None = None  # its shape as drawn
        self._shape_changed = False
        # "version" holds version ranges, so it stays out of the form
        self._labels = [f for f in self._declared["facets"] if f != "version"]
        self._vocabulary = {name: set() for name in self._labels}
        for name, values in (vocabulary or {}).items():
            self._vocabulary.setdefault(name, set()).update(values)
        super().__init__()
        self._others = L.GeoJSON(
            data=_collection([]), style=_OTHER, hover_style={"weight": 3}
        )
        self._others.on_click(self._clicked)
        self._labels_layer = L.LayerGroup()
        self.map.add(self._others)
        self.map.add(self._labels_layer)
        self._build_form()
        self.children = [W.HBox([self.map, self.form]), self.status]
        self.map.layout = W.Layout(height="520px", width="60%")
        problems = self._check_all()
        self._refresh()
        if self.features:
            self.select(0)
        else:
            self.new()
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
        return qe.Registry("vizqueryearth", **self._declared)

    def _check_all(self) -> list[str]:
        """Problems queryearth finds in the file as it stands."""
        try:
            self._registry().add(self._collection)
        except qe.LoadError as err:
            return list(err.problems)
        return []

    def save(self, path: str | os.PathLike[str] | None = None) -> None:
        """Apply the form, check the whole file with queryearth, then write it."""
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
        """Show one rule, by code or position; changes to the last one are applied."""
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

    def new(self) -> None:
        """Start a new rule: fill in the form, draw its shape, then apply."""
        if self._pending():
            self.apply()
        self._index = None
        self._shape = None
        self._shape_changed = False
        self._fill({"kind": "warning"})
        self._show(None)
        self._refresh()
        self._say("New rule: give it a code, title and message, and draw its shape.")

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
        """Give the selected rule a shape (None for everywhere); apply to keep it."""
        self._shape = shape
        self._shape_changed = True
        self._show(shape)
        self._say(_describe(shape))

    def apply(self) -> str:
        """Check the form and the shape with queryearth and keep them in the file."""
        feature = self._edited()
        code = feature["properties"]["code"]
        clash = [i for i, c in enumerate(self.rules) if c == code and i != self._index]
        if clash:
            raise self._fail(f"{code} is already in the file")
        try:
            self._check(feature)
        except (ValueError, TypeError, KeyError) as err:
            raise self._fail(f"{code}: {err}") from err
        if self._index is None:
            self.features.append(feature)
            self._index = len(self.features) - 1
        else:
            self.features[self._index] = feature
        self._shape_changed = False
        self._refresh()
        self._say(f"Applied {code}. Save to write the file.")
        return code

    def _check(self, feature: dict[str, Any]) -> None:
        self._registry().add(feature)  # the record, then its names

    def _fail(self, text: str) -> ValueError:
        self._say(text, error=True)
        return ValueError(text)

    def _edited(self) -> dict[str, Any]:
        """The selected rule with the form's values and the drawn shape."""
        if self._index is None:
            feature = {"type": "Feature", "id": None, "geometry": None, "time": None}
            feature["properties"] = {}
        else:
            feature = copy.deepcopy(self.features[self._index])
        props = feature["properties"]
        old_code = props.get("code")
        props.update(
            code=self._code.value.strip(),
            kind=self._kind.value,
            title=self._title.value,
            message=self._message.value,
        )
        if self._level.value:
            props["level"] = self._level.value
        else:
            props.pop("level", None)
        facets = props.get("facets", {})
        for name, widget in self._facet_inputs.items():
            if isinstance(facets.get(name), dict):
                continue  # any_of/none_of patterns: edited in the file
            if widget.value:
                facets[name] = list(widget.value)
            else:
                facets.pop(name, None)
        if facets:
            props["facets"] = facets
        else:
            props.pop("facets", None)
        if "id" in feature and feature["id"] == old_code:
            feature["id"] = props["code"]  # an id that named the old code follows it
        if self._shape_changed or self._index is None:
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
            return bool(self._code.value.strip())
        return self._shape_changed or self._edited() != self.features[self._index]

    def _drawn(self, shape: Shape | None) -> None:
        self._shape = shape
        self._shape_changed = True
        self._say(_describe(shape) + " Apply to keep it.")

    # ---- the form ----------------------------------------------------------------
    def _build_form(self) -> None:
        self._picker = W.Dropdown(description="Rule", layout=_WIDE)
        self._picker.observe(self._picked, names="value")
        self._code = W.Text(description="Code", layout=_WIDE)
        self._kind = W.Dropdown(description="Kind", options=list(KINDS), layout=_WIDE)
        self._level = W.Dropdown(description="Level", options=_LEVELS, layout=_WIDE)
        self._title = W.Text(description="Title", layout=_WIDE)
        self._message = W.Textarea(description="Message", rows=3, layout=_WIDE)
        self._facet_inputs = {
            name: W.TagsInput(allow_duplicates=False, layout=_WIDE)
            for name in self._labels
        }
        facet_rows = [
            W.HBox([W.Label(name, layout=W.Layout(width="90px")), widget])
            for name, widget in self._facet_inputs.items()
        ]
        self._new_facet = W.Dropdown(options=self._labels, layout=W.Layout(width="40%"))
        self._new_value = W.Text(placeholder="new value", layout=W.Layout(width="40%"))
        add_value = W.Button(description="Add value", layout=W.Layout(width="20%"))
        add_value.on_click(lambda _: self._add_value())
        self._extra = W.HTML()
        box = {
            k: W.FloatText(description=k, layout=W.Layout(width="50%"))
            for k in ("west", "width", "south", "north")
        }
        self._box = box
        use_box = W.Button(description="Use box")
        use_box.on_click(lambda _: self._use_box())
        self._cap = W.FloatText(value=66.5, description="Cap from", layout=_WIDE)
        north = W.Button(description="Arctic cap")
        north.on_click(lambda _: self.set_shape(arctic(self._cap.value)))
        south = W.Button(description="Antarctic cap")
        south.on_click(lambda _: self.set_shape(antarctic(self._cap.value)))
        everywhere = W.Button(description="No shape")
        everywhere.on_click(lambda _: self.set_shape(None))
        buttons = {
            "Apply": self.apply,
            "New rule": self.new,
            "Save file": self.save,
        }
        actions = []
        for label, method in buttons.items():
            button = W.Button(
                description=label, button_style="primary" * (label == "Apply")
            )
            button.on_click(lambda _, m=method: _quietly(m))
            actions.append(button)
        self.form = W.VBox(
            [
                self._picker,
                self._code,
                self._kind,
                self._level,
                self._title,
                self._message,
                W.HTML("<b>Facets</b>"),
                *facet_rows,
                W.HBox([self._new_facet, self._new_value, add_value]),
                self._extra,
                W.HTML("<b>Box</b> (or draw on the map)"),
                W.HBox([box["west"], box["width"]]),
                W.HBox([box["south"], box["north"]]),
                W.HBox([use_box, everywhere]),
                self._cap,
                W.HBox([north, south]),
                W.HBox(actions),
            ],
            layout=W.Layout(width="40%", padding="0 0 0 12px"),
        )

    def _fill(self, props: Mapping[str, Any]) -> None:
        """Show a rule's properties in the form."""
        self._code.value = props.get("code", "")
        kind, level = props.get("kind"), props.get("level", "")
        self._kind.value = kind if kind in KINDS else "warning"
        self._level.value = level if level in dict(_LEVELS).values() else ""
        self._title.value = props.get("title", "")
        self._message.value = props.get("message", "")
        facets = props.get("facets", {})
        for name, widget in self._facet_inputs.items():
            value = facets.get(name, [])
            values = [] if isinstance(value, dict) else list(value)
            self._vocabulary[name].update(values)
            widget.allowed_tags = sorted(self._vocabulary[name])
            widget.value = values
        kept = [k for k in props if k not in _FORM]
        patterns = [n for n, v in facets.items() if isinstance(v, dict)]
        notes = []
        if kept:
            notes.append(f"Also has {', '.join(kept)}: kept as in the file.")
        if patterns:
            notes.append(f"Facet patterns for {', '.join(patterns)}: edit in the file.")
        self._extra.value = "<br>".join(html.escape(n) for n in notes)
        box = props.get("box") or {}
        for key, widget in self._box.items():
            widget.value = box.get(key, 0.0)

    def _add_value(self) -> None:
        name, value = self._new_facet.value, self._new_value.value.strip()
        if name and value:
            self._vocabulary[name].add(value)
            self._facet_inputs[name].allowed_tags = sorted(self._vocabulary[name])
            self._new_value.value = ""

    def _use_box(self) -> None:
        box = {k: w.value for k, w in self._box.items()}
        try:
            self.set_shape(Shape(box=box))
        except ValueError as err:
            self._say(f"queryearth cannot use this box: {err}", error=True)

    def _picked(self, change: dict[str, Any]) -> None:
        if change["new"] is not None and change["new"] != self._index:
            _quietly(self.select, change["new"])

    def _clicked(self, **event: Any) -> None:
        index = (event.get("properties") or {}).get("index")
        if index is not None:
            _quietly(self.select, index)

    def _refresh(self) -> None:
        """Redraw the other rules, their labels and the rule list."""
        shapes, labels = [], []
        for i, feature in enumerate(self.features):
            for name, values in (feature["properties"].get("facets") or {}).items():
                if name in self._vocabulary and isinstance(values, list):
                    self._vocabulary[name].update(values)
            if i == self._index:
                continue
            try:
                shape = _shape_of(feature)
            except ValueError:
                continue  # listed among the file's problems
            if shape is None:
                continue
            code = feature["properties"].get("code", f"feature {i}")
            parts = to_leaflet(shape)
            for part in parts:
                part["properties"] = {"index": i, "code": code}
            shapes += parts
            if parts:
                labels.append(_label(code, parts[0]["geometry"], i, self._clicked))
        self._others.data = _collection(shapes)
        old = self._labels_layer.layers
        self._labels_layer.layers = tuple(labels)
        for marker in old:  # free the old labels' widgets in the browser too
            marker.icon.close()
            marker.close()
        options = [
            (
                f"{code or f'feature {i}'}{' (everywhere)' * (_shape_or_none(f) is None)}",
                i,
            )
            for i, (code, f) in enumerate(zip(self.rules, self.features))
        ]
        self._picker.unobserve(self._picked, names="value")
        self._picker.options = options
        self._picker.value = self._index
        self._picker.observe(self._picked, names="value")


def _shape_of(feature: Mapping[str, Any]) -> Shape | None:
    """A record's shape as it is in the file, or None when it has none."""
    box = (feature.get("properties") or {}).get("box")
    if box is not None:
        return Shape(box=box)
    if feature.get("geometry") is not None:
        return Shape(geometry=feature["geometry"])
    return None


def _shape_or_none(feature: Mapping[str, Any]) -> Shape | None:
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
