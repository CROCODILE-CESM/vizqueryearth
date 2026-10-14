# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

vizqueryearth draws the shapes of [queryearth](https://github.com/CROCODILE-CESM/queryearth) rules on a map in Jupyter: `draw()` for one shape, `Editor` for the shapes of a rule file. It is a separate package because queryearth itself must stay free of UI code.

## Rules

- **queryearth is the only judge.** Every shape goes through `queryearth.space.polygon` or a record `box` (`queryearth.rules.box_of`), every rule through `Registry.add`, and every saved file is checked with queryearth before it replaces the old one. Never re-implement queryearth's rules here.
- **No UI code in queryearth.** If the editor needs something from queryearth, it must be a general engine API, proposed in that repo.
- **Small.** No JavaScript of our own: ipyleaflet and its Leaflet-Geoman control do the drawing. Prefer Leaflet over MapLibre.
- **Saving changes only what was edited.** Other rules are written back exactly as read (`json.dumps(indent=2)`), so a file written by the editor and saved again without changes is byte-identical.
- **Not on PyPI.** Installed from GitHub; no release workflow. Depend on queryearth from git until queryearth 0.1.0 is on PyPI, then use `queryearth>=0.1`.
- **Python 3.11 or later**, black, frozen dataclasses where data is passed around.
- **Git:** never add Co-Authored-By lines; ask before committing or pushing.

## Layout

| Path | What |
|---|---|
| `vizqueryearth/shapes.py` | `Shape` (a geometry or a box), `from_leaflet` (drawing layer to Shape), `to_leaflet` (Shape to map features, joining pieces split at ±180 and cutting at 85°), `arctic`, `antarctic`. Pure Python; this is where correctness lives |
| `vizqueryearth/widgets.py` | `draw()`/`Drawing` and `Editor`, thin layers over ipyleaflet. The drawing control's synced `data` list is the only channel from the browser |
| `tests/` | `test_shapes.py` (conversions, round trips) and `test_editor.py` (the editor driven without a browser by setting `control.data`) |
| `examples/` | `demo.py` (`# %%` cells) and `demo_rules.geojson` (made up) |
| `docs/design.md` | The design and its decisions |

## Development

```bash
pip install -e ".[test]"
pytest
black .
```

Widgets can only be checked by eye: run `examples/demo.py` cell by cell in VS Code or JupyterLab.
