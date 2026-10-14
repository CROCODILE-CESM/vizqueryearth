# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

vizqueryearth is a browser-only web page for [queryearth](https://github.com/CROCODILE-CESM/queryearth) rule files: it shows rules on a globe, checks which apply to an area, dates and dimension values, and edits them. It is hosted on GitHub Pages: no server, no sign-in, nothing stored by us. Files are opened from disk or a link (`?src=`) and saved by download, as a rules file or as a single-file web page. It is a separate repository because queryearth itself must stay free of UI code.

## Rules

- **queryearth is the only judge.** Every shape goes through `queryearth.space.polygon` or a record `box` (`queryearth.rules.box_of`), every rule through `Registry.add`, and every saved file is checked with queryearth first. Never re-implement queryearth's rules here, in Python or in JavaScript.
- **No UI code in queryearth.** If the page needs something from queryearth, it must be a general engine API, proposed in that repo.
- **Small.** One page (`web/app.js`, `web/app.css`), no build step, no framework, no bundler. Libraries come from pinned CDN URLs. The JavaScript only draws and wires events; everything that touches a rule is Python in `vizqueryearth/`, called through `Session.call`.
- **Browser-only.** No server, no accounts, no analytics, nothing sent anywhere. Browser storage is only a safety net for unsaved edits.
- **Saving changes only what was edited.** Other rules are written back exactly as read (`json.dumps(indent=2)`); the file's `"dimensions"` member is always written.
- **Not on PyPI.** The package is used by the page and in tests; no release workflow. It depends on `queryearth>=0.3,<0.4`; raise the bound, and `QUERYEARTH` in `web/app.js`, together when queryearth's API changes.
- **Python 3.11 or later**, black, frozen dataclasses where data is passed around.
- **Git:** never add Co-Authored-By lines; ask before committing or pushing.

## Layout

| Path | What |
|---|---|
| `vizqueryearth/shapes.py` | `Shape` (a geometry or a box), `from_drawn` (drawn GeoJSON to a Shape; rectangles span the short way round, points within 0.5° of a pole go to it), `fill`/`outline`/`editable`/`label_point`/`extent` (what the globe shows), `arctic`, `antarctic` |
| `vizqueryearth/rulefile.py` | `RuleFile`: a rule file edited one rule at a time, each edit checked by queryearth; its `"dimensions"` member; `guess_dimensions` for files that declare none. Dimension descriptions use queryearth's `dimension_from`/`describe_dimension` |
| `vizqueryearth/session.py` | `Session.call(name, json)`: the page's only link to Python. Reads what is typed on the page (axis bounds such as `<8`, change values as JSON) |
| `web/index.html`, `web/app.js`, `web/app.css` | The page. Pinned library URLs (MapLibre GL, Terra Draw, Natural Earth land, Pyodide) and the queryearth version are at the top of `app.js` |
| `web/py/vizqueryearth` | A symlink to `../../vizqueryearth`: the page fetches the package's Python from here. The Pages workflow copies `web/` with links followed (`cp -rL`) |
| `web/sites/<name>/` | Curated pages, added by pull request: an `index.html` stub, `site.json`, `rules.geojson`. `demo/` is the made-up example |
| `tests/` | `test_shapes.py`, `test_rulefile.py`, `test_session.py` (no browser); `browser/test_web.py` drives the page in headless Chromium and is skipped without Playwright |
| `.github/workflows/` | `tests.yml` (pytest on 3.11 to 3.14, plus one browser job), `quality_control.yml` (black), `pages.yml` (deploys `web/` to GitHub Pages from main) |
| `docs/design.md` | The design and its decisions |

## Development

```bash
pip install -e ".[test]"
pytest
black .
python -m http.server 8000 -d web   # then http://localhost:8000/sites/demo/
```

The browser tests need Playwright and network access (CDNs and PyPI):

```bash
pip install playwright && python -m playwright install chromium
pytest tests/browser
```

`window.__vizqueryearth` exposes the page state, `call`, the map and Terra Draw for these tests. Keep the browser tests to what only a browser can check; test behaviour in Python where possible. After changing `app.js`, look at a screenshot of the page, including both poles.
