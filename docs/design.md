# vizqueryearth design

**Status:** version 1 built on 2026-10-13 (`vizqueryearth/`); this document records its design. Decisions taken after review are in section 10.

## 1. Goal

Writing a queryearth rule file by hand is mostly fine, except for the shapes: typing polygon
coordinates is slow and easy to get wrong. vizqueryearth lets you draw them on a map in Jupyter and
saves them into rules that queryearth reads.

Version 1 does one thing: **draw and edit the shapes of rules.**

- Draw a polygon or a box and get it back in Python, ready for a rule written in Python.
- Open a rule file, see every rule's shape labelled by its code, draw or redraw a rule's shape, add
  a rule with its four required fields (code, kind, title, message), and save the file.

Later, and not designed here (section 8): browsing and filtering a ruleset, test queries, a web
page, and a place where anyone can see their own rules on a map.

## 2. Principles

- **queryearth is the only judge of a rule.** Every shape goes through `queryearth.space.polygon`
  (or a record `box`), every rule through `Registry.add` before it is kept, and the whole file is
  checked by queryearth before it replaces the old one. The editor can never save a file that
  queryearth would reject or read differently.
- **Saving changes only what was edited.** Other rules are written back exactly as they were read,
  so a hand-written file keeps its records and a re-save without changes gives the same bytes
  (for files in the editor's format, `json.dumps` with an indent of 2).
- **No UI code in queryearth.** queryearth keeps numpy and shapely as its only dependencies.
- **Small.** Version 1 is Python only, with no JavaScript of our own.

## 3. The package

- A separate public repo, `CROCODILE-CESM/vizqueryearth`. It is **not published on PyPI**:
  install it with `pip install git+https://github.com/CROCODILE-CESM/vizqueryearth`, or
  `pip install -e .` from a clone. No release workflow.
- Dependencies: `queryearth` and `ipyleaflet` (which brings `ipywidgets`).
- Layout:
  - `vizqueryearth/shapes.py`: converts between drawn GeoJSON and queryearth spaces and boxes.
    Pure Python, so it is tested in CI without a browser. This is the part that could be wrong
    without anyone noticing.
  - `vizqueryearth/widgets.py`: `draw()` and `Editor`, thin layers over ipyleaflet.
  - `examples/demo.ipynb`, `tests/`, and a CI workflow that runs pytest and black.
- The widgets themselves are checked by hand in a notebook.

## 4. Map and drawing

**Leaflet 1.9 with Leaflet-Geoman** (free version), both MIT, through ipyleaflet's `Map` and
`GeomanDrawControl` (jupyter-widgets project, MIT). Geoman draws polygons and rectangles, and
edits, drags, rotates, removes and cuts them. ipyleaflet passes every drawn shape to Python as
GeoJSON through `on_draw`, so version 1 needs no JavaScript of its own.

Leaflet, rather than MapLibre with terra-draw: it is lighter and simpler, Geoman's tools are
polished, and vector tiles or a globe view do not help to draw rule shapes. Leaflet also keeps
longitudes continuous when you draw across the date line, which queryearth already handles,
whereas terra-draw cannot edit a shape across ±180 (its issue #485).

**The date line.** queryearth stores a shape that crosses 180° split into two pieces, one ending at
180° and one starting at -180°. To show and edit it as one shape, the editor shifts the western
piece by 360° and joins the two; on save, queryearth splits it again. A Bering Sea box drawn from
165°E to 160°W is edited as 165 to 200 and stored as 165 to 180 plus -180 to -160.

**The poles.** Leaflet's Web Mercator map stops near 85° north and south. A point drawn past 85°,
at the map's top or bottom edge, is taken to the pole, so a rectangle drawn to the top edge is a
box that reaches 90°N, and a polar box is shown cut off at the edge and edited like any other
shape. From code, `vq.arctic(66.5)` and `vq.antarctic(-60)` give full-width caps.

**To confirm in the prototype:**

| Check | Why it matters |
|---|---|
| `GeomanDrawControl` works in VS Code notebooks and in JupyterLab on Casper | ipyleaflet loads its front end from a CDN in VS Code |
| Drawing across 180° gives continuous longitudes, such as 170 to 200 | queryearth then splits the shape correctly |
| How shapes reach Python | Confirmed in ipyleaflet 0.20's source: the control's synced `data` list holds every shape on the drawing layer after each create, edit, drag or delete, and setting it from Python loads shapes for editing |
| A rectangle can be told apart from a polygon | The front end rebuilds drawn layers as plain polygons, so any axis-aligned four-corner ring becomes a `box`; the shape is the same either way |
| ipyleaflet's release pace (0.20.0, June 2025) is acceptable | the fallback is a small anywidget with the same Leaflet and Geoman |

## 5. From a drawing to a rule

1. Geoman returns a GeoJSON polygon. A rectangle becomes a `box`.
2. The longitudes along each ring are made continuous, so that no step is longer than 180°.
3. queryearth normalises it: `queryearth.space.polygon` splits it at ±180 and checks the ring.
   Its error messages appear under the map, for example for a ring that crosses itself.
4. For a rule file, the editor builds each rule as a record and checks it with `Rule.from_feature`.
5. `save()` checks the whole file by adding it to a fresh `queryearth.Registry` declared with the
   editor's `axes`, `facets` and `dimensions`, which checks every record and every name, then writes
   it to a temporary file and moves that over the old one. Rules that were not edited are written
   back as they were read; an edited rule keeps its other properties and its key order.

## 6. API sketch

Notebook cells do not wait for the user, so a drawing is read in the next cell:

```python
import vizqueryearth as vq

d = vq.draw()  # shows a map: draw one polygon or box
```

```python
import queryearth as qe

d.space  # the shape as a queryearth Space
d.geometry  # the GeoJSON geometry, or the box, to paste into a rule file
rule = qe.Rule(
    code="CROC010",
    kind="warning",
    title="Example",
    message="An example rule.",
    scope=qe.Scope(space=d.space),
)
```

```python
ed = vq.Editor(
    "rules.geojson",  # every rule's shape, labelled by its code
    axes=[qe.Axis("resolution", "km")],  # what the rules use, as for qe.Registry
)
ed.select("CROC003")  # or click a shape; then draw to replace it
ed.new()  # adds CROC012 after CROC011, selected; or ed.add(code, kind, title, message)
ed.set_shape(vq.arctic(70))  # or draw it
ed.save()  # checks the whole file, then writes it
```

## 7. Google Earth Engine

Earth Engine is a good place to make shapes and a poor place to build this editor.

- Earth Engine Apps run only Earth Engine's JavaScript, so they could not run queryearth to check
  a rule; the reader would have to be written twice.
- Earth Engine polygons have geodesic edges by default, along great circles, while queryearth's
  edges are straight in longitude and latitude. The same corner points give a different area for
  a large polygon.
- Authors need a registered Google Cloud project, and files live in Earth Engine assets or Google
  Drive rather than with the rest of a project.

So vizqueryearth takes shapes from it instead: **Import GeoJSON** accepts files exported from Earth
Engine, geemap, QGIS or geojson.io, with an option to add points along geodesic edges so that the
shape keeps its meaning. Rule shapes made from data, such as a threshold on a dataset, are a
possible later feature, computed with xarray or Earth Engine.

## 8. Later

- **Browse a ruleset:** a table beside the map, filters by kind, facet and time, click to select.
- **Test queries:** draw a domain or load one (for example a CrocoDash domain outline), choose
  dates and axes, and list the findings with their area and time fractions, highlighted on the map.
- **A web page:** the same Leaflet and Geoman on a static page, with Pyodide running the real
  queryearth from PyPI. Pyodide 314 is the first release with shapely 2.1, which queryearth needs;
  a first visit downloads about 10 MB. Hosted free on vizqueryearth's GitHub Pages. Anyone opens
  their own rule file, or a link to one, to see it on a map: no accounts and no server.
- **Sharing:** start with files, kept wherever people keep them. Add accounts or a gallery only if
  people ask for them.

## 9. Alternatives considered

| Option | Why not first |
|---|---|
| A `viz` extra inside queryearth | Keeps UI code out of the engine's package |
| MapLibre with terra-draw (opengeos' anymap wraps them) | Heavier; terra-draw cannot edit across ±180 (#485) or draw holes (#425) |
| Panel (used by GLHE's dashboard) | Heavier in the browser; its draw tools work on a Web Mercator plot |
| Solara | Needs a running server for the web version |
| ipympl with cartopy, as in mom6_forge's GridSketcher | Matches the CROC tools and handles the poles, but has no path to a web page |
| OpenLayers | The only real option for drawing on a polar map; kept for later if box presets are not enough |
| marimo, Streamlit or Shiny in the browser | marimo is owned by CoreWeave; stlite and shinylive use a Pyodide without shapely 2.1 |
| Forking geojson.io or Placemark | A whole application to maintain |
| Earth Engine Apps | Section 7 |

## 10. Decisions after review (2026-10-13)

1. **No hole drawing in version 1.** Geoman's cut tool is off; holes in rules loaded from a file are
   kept.
2. **ipyleaflet is fine.**
3. **A lean form (2026-10-14).** After trying it, the form was cut to code, kind (a dropdown),
   title and message, with **New rule** and **Save**. Facets, level, time and every other field
   are edited in the file and kept as they are; facets are part of a rule's scope, but they are set
   once when a rule is written. **New rule** adds a rule with the next free code at once. There is
   no Apply button: changes are kept when you pick another rule or save. Box fields and polar-cap
   buttons gave way to drawing at the map's edge, which reaches the pole.

## 11. Plan

1. `shapes.py` with tests: drawn GeoJSON to Space or box and back, date line, polar caps.
2. `draw()`.
3. `Editor`: open, show, select, redraw, add, save.
4. Then, if wanted: browse, test queries, the web page.

## Sources

Checked on 2026-10-13: ipyleaflet `GeomanDrawControl` docs
(ipyleaflet.readthedocs.io/en/latest/controls/geoman_draw_control.html); Leaflet-Geoman README
(github.com/geoman-io/leaflet-geoman); terra-draw issues #425 and #485
(github.com/JamesLMilner/terra-draw); Pyodide package list
(pyodide.org/en/stable/usage/packages-in-pyodide.html); Earth Engine `ee.Geometry.Polygon`
docs (geodesic default); anymap (anymap.dev); marimo's acquisition by CoreWeave (coreweave.com
news, October 2025).
