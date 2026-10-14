# vizqueryearth

Draw the shapes of [queryearth](https://github.com/CROCODILE-CESM/queryearth) rules on a map in Jupyter.

- `vq.draw()` shows a map to draw one polygon or box on, for a rule written in Python.
- `vq.Editor("rules.geojson")` shows every rule of a rule file on a map. Pick a rule (from the list or by clicking its shape), draw or edit its shape, and edit its code, kind, title and message. **New rule** adds one with the next free code. Time, the other dimensions, level and everything else stay as they are in the file.

queryearth checks every shape and every rule, so the editor never saves a file that queryearth would refuse or read differently.

## Install

vizqueryearth is not on PyPI. Install it from GitHub:

```bash
pip install git+https://github.com/CROCODILE-CESM/vizqueryearth
```

or from a clone with `pip install -e .`. It needs Python 3.11 or later, queryearth and ipyleaflet, and runs in JupyterLab and VS Code notebooks.

## Use

```python
import queryearth as qe
import vizqueryearth as vq

d = vq.draw()  # draw a polygon or a rectangle, then in the next cell:
rule = qe.Rule(
    code="MINE001",
    kind="warning",
    title="Example",
    message="A rule whose shape was drawn on the map.",
    scope=qe.Scope(space=d.space),
)
```

```python
ed = vq.Editor(
    "rules.geojson",
    dimensions=[qe.Axis("resolution", "km"), qe.Labels("product")],  # as for qe.Registry
)
ed  # pick a rule or click New rule, draw its shape, Save
```

`examples/demo.ipynb` walks through both, on made-up rules.

## How shapes are stored

- **Rectangles** become a record `box` (`{west, width, south, north}`). Any other drawing becomes a GeoJSON polygon. Several drawings on one rule make one MultiPolygon.
- **Across the date line**, Leaflet gives continuous longitudes, such as 165 to 200. A box keeps them (`west` 165, `width` 35). A polygon is split at ±180 in the file and joined again on the map.
- **Near the poles**, the map stops at about 85°, so anything drawn to its top or bottom edge reaches the pole: a rectangle drawn to the top edge is a box up to 90°N. From code, `ed.set_shape(vq.arctic(66.5))` gives a full-width cap.
- **Holes** in rules loaded from a file are kept, but version 1 cannot draw them.
- **Saving** changes only the rules you edited. Every other rule is written back as it was read, and the file is checked with queryearth before it is replaced.

## Development

```bash
pip install -e ".[test]"
pytest
black .
```

The design is in `docs/design.md`.
