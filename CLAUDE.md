# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

vizqueryearth is a browser-only web page for [queryearth](https://github.com/CROCODILE-CESM/queryearth) rule files: it shows rules on a globe, checks which apply to an area, dates and dimension values, and edits them. It has two modes on one page: Check (read the rules, check an area; the default) and Create (write them; called Edit before, and `#edit` still opens it), chosen by `#check`/`#create`, else the viewer's last mode on the main page, else Check. What the file holds is on the left (the rules tree, the dimensions, the file's buttons), the globe is in the middle, and what you do is on the right (the Check/Create switch, checking, adding and editing); the page keeps its words few, with explanations in tooltips. It is hosted on GitHub Pages: no server, no sign-in, nothing stored by us. Files are opened from disk or a link (`?src=`) and saved by download, as a rules file or as a single-file web page. It is a separate repository because queryearth itself must stay free of UI code.

## Rules

- **queryearth is the only judge.** Files are read with `Registry.from_file` and written with `Registry.to_file`, every rule is a `queryearth.Rule` checked by `Registry.add` after every edit, and every shape goes through `queryearth.space`. Never re-implement queryearth's rules here, in Python or in JavaScript.
- **No UI code in queryearth.** If the page needs something from queryearth, it must be a general engine API, proposed in that repo.
- **Small.** One page (`web/app.js`, `web/app.css`), no build step, no framework, no bundler. Libraries come from pinned CDN URLs. The JavaScript only draws and wires events; everything that touches a rule is Python in `vizqueryearth/`, called through `Session.call`.
- **Browser-only.** No server, no accounts, no analytics, nothing sent anywhere. Browser storage is only a safety net for unsaved edits.
- **Saving writes what queryearth writes.** `Session.do_text()` is `Registry.to_file`'s text; rules not edited keep every value as read (`Rule.to_feature`). Rule files do not declare dimensions: the page infers them from the rules' values (`infer`), after any the site declares, and a downloaded web page embeds them. Files from queryearth 0.7 or before, whose rules have a `code` rather than a `name`, are refused by queryearth; the page converts nothing.
- **Categories are name paths.** A rule's category is `rule.category`; the tree is built from the rules' names; moving a rule or renaming a category rewrites names (`do_move`, `do_rename`). A category with no rule lives only in the page (`page.empty`).
- **Not on PyPI.** The package is used by the page and in tests; no release workflow. It depends on `queryearth>=0.8,<0.9`; raise the bound, and `QUERYEARTH` in `web/app.js`, together when queryearth's API or file format changes.
- **Python 3.11 or later**, black, frozen dataclasses where data is passed around.
- **Git:** never add Co-Authored-By lines; ask before committing or pushing.

## Layout

| Path | What |
|---|---|
| `vizqueryearth/shapes.py` | `drawn` (drawn GeoJSON to a queryearth space; points within 0.5° of a pole go to it), `cap`, `on_globe` (fill, outline, label, editable corners, extent), `extent` |
| `vizqueryearth/session.py` | `Session.call(name, json)`: the page's only link to Python. It holds the rules (`queryearth.Rule`) and dimensions, checks every edit with a Registry before keeping it, and reads what is typed on the page (axis bounds such as `<8`). Each rule in the state carries its `record`, its Feature as JSON text. `infer` (dimensions from the rules' values) |
| `web/index.html`, `web/app.js`, `web/app.css` | The page. Pinned library URLs (MapLibre GL, Terra Draw, Natural Earth land, Pyodide) and the queryearth version are at the top of `app.js`. `render()` builds the left side (`#rules-list`, the tree, which scrolls; `#rules-foot`, the dimensions in Create and the file's buttons) and the right side (`#panel`: `modeBar()`, the Check/Create switch and, in Create, + Rule, + Category and + Dimension, kept in view; then the mode's content). The header holds only the title. The rules are one tree (`treeItems()`, from `categories()`, the name paths plus `page.empty`; ARIA tree with arrow keys); categories start closed and the opened ones are kept (`openedStore`), and `openTo()` opens a category's branches when a rule is picked elsewhere. Rows are one line with no buttons; in Create they have pointer drag and drop, and the non-drag moves are the rule form's Category select and the Inside select of a category's form. The selected rule opens at the top of the right panel (`ruleSection()`): its card in Check, its form and its GeoJSON (`geojsonWindow()`, always open) in Create; in Create, a picked category with no rule selected shows its form there (`categorySection()`: name, Inside, Remove). + Rule and + Category add where `here()` says: the selected rule's category, else the picked one. Hovering a rule's shape, label or row shows its tooltip (`showTip()`, one `#tip` box). `packed()` lays out a rule's record as queryearth's `to_file` does |
| `web/py/vizqueryearth` | A symlink to `../../vizqueryearth`: the page fetches the package's Python from here. The Pages workflow copies `web/` with links followed (`cp -rL`) |
| `web/sites/<name>/` | Curated pages, added by pull request: an `index.html` stub, `site.json`, `rules.geojson`. `demo/` is the made-up example; `crocodash/` holds a copy of `CrocoDash/rules.geojson` from CrocoDash's `cd_qe_int` branch, copied again by hand when that changes |
| `tests/` | `test_shapes.py`, `test_session.py` (no browser); `browser/test_web.py` drives the page in headless Chromium and is skipped without Playwright. `QUERYEARTH_WHEEL=<wheel>` makes it serve a copy of `web/` that installs that wheel, to test a queryearth not on PyPI yet; `CROCODASH_RULES=<rules.geojson>` adds a check on one of CrocoDash's rule files |
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
# a queryearth that is not on PyPI yet, built from its checkout:
QUERYEARTH_WHEEL=/path/to/queryearth-0.8.0-py3-none-any.whl pytest tests/browser
```

`window.__vizqueryearth` exposes the page state, `call`, the map and Terra Draw for these tests. Keep the browser tests to what only a browser can check; test behaviour in Python where possible. After changing `app.js`, look at a screenshot of the page, including both poles.
