# vizqueryearth design

**Status:** the web app, built in October 2026. It replaces version 1, a Jupyter editor on ipyleaflet, which is in the git history.

## 1. Goal

A page where anyone can see queryearth rules on a globe, check which of them apply to their own work, and write or edit rules without typing coordinates. The people who use it are the people who use the rules: they open a page, draw where they work, and read what applies. The people who keep a set of rules edit them on the same page and publish the result.

## 2. Decisions

**Browser-only.** By decision of the project, there is no server, no sign-in and nothing stored by us. A rules file is opened from disk or from a link (`?src=<url>`) and saved by downloading it. Unsaved edits are kept in the browser's storage as a safety net and offered back on the next visit; they are never the only copy we rely on.

**queryearth runs in the page.** Pyodide runs queryearth itself, from PyPI, and this repository's Python (`vizqueryearth/`). Every shape, edit, file and query goes through queryearth, so the page can never save a file that queryearth would refuse or read differently, and there is no second implementation of its rules in JavaScript. The JavaScript draws and wires events; `Session.call(name, json)` is its only way into Python, and also reads what people type (axis bounds such as `<8`, change values as JSON). The same Python is tested in CI without a browser. The cost is the first visit: about 20 MB, cached afterwards.

**Hosting.** GitHub Pages, deployed from `main` by `.github/workflows/pages.yml`, which copies `web/` with the `web/py` symlink followed. GitHub Pages sends `Access-Control-Allow-Origin: *`, which pages hosted elsewhere need to load the app.

**Curated pages by pull request.** A page for a set of rules is a folder `web/sites/<name>/` with an `index.html` stub, `site.json` (title, description, rules, optional dimensions and view) and the rules file. Review of the pull request is the only moderation, and the page lives at `/sites/<name>/`.

**Self-hosting.** "Download as web page" gives one `index.html` that embeds the settings and the rules and loads `app.js` and `app.css` from wherever the app is hosted. It can go on any static host, or be opened from disk, with nothing of ours involved beyond the app's files.

**Files describe themselves.** A rules file declares its dimensions in a top-level `"dimensions"` member, the form queryearth 0.3 reads (`Registry.from_file`). The page always writes it. When opening, the file's member wins, then the site's `dimensions`, then a guess from the rules.

**One view.** Checking an area and editing rules are on one panel: selecting a rule, from the list, its label or its shape, opens its form in place. There are no modes and no browser dialogs: `prompt()` and `confirm()` return nothing in some embedded browsers, so titles, links and deletion use fields and a second click.

## 3. Globe and drawing

**MapLibre GL's globe with Terra Draw.** Leaflet, used by version 1, draws Web Mercator, which stops near 85° and cannot show the poles; polar caps and Arctic or Antarctic rules are common for ocean and ice models. On a globe the poles and the date line are ordinary places.

**Longitudes are wrapped.** Terra Draw rejects longitudes beyond ±180, so drawings arrive between -180 and 180, and a shape across the date line has an edge that jumps, such as from 170 to -170. queryearth takes every edge the short way round and splits the shape at ±180, so a drawn polygon goes to queryearth as it is. A rectangle becomes a record `box` and follows the same rule: corners at 170 and -170 make a box 20° wide across the date line. Shapes that cross the date line, reach a pole or have holes cannot be handed back to Terra Draw to move their corners; they are redrawn instead.

**The poles.** MapLibre's globe draws map data only to about 85° and fills the rest from polygon edges that reach the pole. Rule shapes reach it exactly (a point drawn within 0.5° of a pole is taken to the pole), so polar caps are filled to the pole. Land is Natural Earth's GeoJSON, which is cut at ±180; the world-atlas TopoJSON is stitched across ±180 and draws a band across the globe. Natural Earth's Antarctica runs to the pole along 89.99°S, which the globe draws badly, so it is cut at 84°S and a band of land from there to the pole replaces it. Rule labels on the far side of the globe are hidden.

**Turning to the rules.** Python gives the extent of the shapes, the short way round, so a set across the date line gets one extent. A page without a `view` opens on its rules, selecting a rule turns the globe to it, and a set that goes all the way round is shown from above its pole.

## 4. Follow-up

**Versioned app paths.** A downloaded page loads `app.js` from the site root, so it changes whenever the app does, and a breaking change to the settings it embeds would break it. The plan is to publish each major version of the app under its own path, such as `/v1/`, have downloaded pages point there, and keep the root for the latest. Not implemented yet.
