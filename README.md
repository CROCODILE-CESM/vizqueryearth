# vizqueryearth

Draw the shapes of [queryearth](https://github.com/CROCODILE-CESM/queryearth) rules on a map in Jupyter.

- `vq.draw()` shows a map to draw one polygon or box on, for a rule written in Python.
- `vq.Editor("rules.geojson")` shows every rule of a rule file on a map. You can pick a rule, draw or edit its shape, edit its code, kind, level, title, message and facets (with dropdowns of the values the ruleset uses), add rules, and save.

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
    axes=[qe.Axis("resolution", "km")],  # the ruleset's vocabulary, as for qe.Registry
    vocabulary={"product": ["glorys", "era5"]},  # facet values to offer
)
ed  # pick a rule, draw, Apply, Save file
```

`examples/demo.py` walks through both, on made-up rules.

## How shapes are stored

- **Rectangles** become a record `box` (`{west, width, south, north}`). Any other drawing becomes a GeoJSON polygon. Several drawings on one rule make one MultiPolygon.
- **Across the date line**, Leaflet gives continuous longitudes, such as 165 to 200. A box keeps them (`west` 165, `width` 35). A polygon is split at ±180 in the file and joined again on the map.
- **Near the poles**, the map stops at about 85°. Use the **Arctic cap** and **Antarctic cap** buttons or the box fields; such shapes are shown cut off at 85° and edited by their fields.
- **Holes** in rules loaded from a file are kept, but version 1 cannot draw them.
- **Saving** changes only the rules you edited. Every other rule is written back as it was read, and the file is checked with queryearth before it is replaced.

## Development

```bash
pip install -e ".[test]"
pytest
black .
```

The design is in `docs/design.md`.
