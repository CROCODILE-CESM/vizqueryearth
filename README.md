# vizqueryearth

A web page for [queryearth](https://github.com/CROCODILE-CESM/queryearth) rule files. It shows the rules on a globe, tells you which of them apply to your area, your dates and what you use, and lets you edit them: their shapes, time, dimensions and categories.

It runs entirely in your browser. There is no server and no sign-in, and nothing is stored online: you open a rules file from your computer or from a link, and you save by downloading.

## Try it

- The demo, with made-up rules: https://crocodile-cesm.github.io/vizqueryearth/sites/demo/
- CrocoDash's rules, advice for regional ocean model cases: https://crocodile-cesm.github.io/vizqueryearth/sites/crocodash/
- The page itself, to open your own rules: https://crocodile-cesm.github.io/vizqueryearth/

The first visit downloads about 20 MB (Python and queryearth, see [How it works](#how-it-works)); later visits are quicker.

## Using the page

The globe is on the left and the panel on the right. The page has two modes, switched at the top: **Check**, for people who read the rules, and **Edit**, for people who write them. **Open file** and **Open link** work in both.

### Check

**Check your area.** Draw a rectangle or a polygon where you work, or leave it empty to ask about anywhere. Give dates if you like, and a value for each dimension the rules use, such as a product or a resolution. **Check** lists the rules that apply and highlights them on the globe. A rule about a dimension you leave empty does not apply, and "No rule applies" means only that no rule matched, not that all is well. Click a result to open that rule below, or copy its GeoJSON.

**Rules.** The rules are a tree, made from their codes: a code may be a path, such as `REGION/ITF/ITF001`, whose part before the last slash is its category, `REGION/ITF`, inside `REGION`. **All rules** is at the root, then the categories, their subcategories at any depth, and the rules in each, sorted by code; rules whose code has no slash sit at the root. Each category shows how many rules are in it, at any depth. The categories start closed. Open or close a branch with its arrow; the page remembers which you opened, in this browser.

Click a category to show its rules on the globe, and those of every category in it; the globe turns to them. Type in the filter box to show only the rules whose code or title has those letters (`OBC`, `strait`, `gulf`), with the categories they are in, opened; the globe shows them too and turns to them. Clear the filter and the branches are as you left them. The page remembers your filter. The tree works from the keyboard: the arrow keys move up and down and open and close branches, Home and End go to the first and last item, and Enter or Space picks a category or opens a rule.

Click a rule in the tree, its label or its shape on the globe to open its card, with its categories opened in the tree: the globe turns to it, and the card shows what the rule says and what it covers: its code, message and instruction, where and when it applies, what it applies to, its references and evidence, and any other property it carries. **Copy GeoJSON** copies the rule as the rules file holds it.

### Edit

**Rules.** The same tree, one line to a row, where you also manage the rules and categories. A category exists because a rule's code is in it, so moving and renaming change codes:

- To move a rule, drag it by its handle (⠿) onto a category, or onto **All rules** for none, or pick another **Category** in its form. Its code takes the new path and keeps its last part: `REGION/ITF/ITF003` moved to `DOMAIN/OBC` becomes `DOMAIN/OBC/ITF003`;
- To move a category, drag it onto another one (or onto **All rules**, for the top level), or use **Move to…** in its **⋯**. Renaming it there works the same way: every code in it takes the new path;
- **+ Rule** on a category adds a rule numbered after the last part of its path, such as `DOMAIN/OBC/OBC006` after `DOMAIN/OBC/OBC005`; on **All rules** it adds `RULE001` at the root;
- **+ Category** on **All rules**, and **Add subcategory** in a category's **⋯**, make a category. It holds no rule yet, so it is kept only while the page is open: put a rule in it to keep it in the file. **Remove** in the **⋯** removes a category with no rules; one that holds rules is not removed, and the page says why.

Clicking a rule opens its form in the tree:

- code, level (info, warning or error), category (picking another moves the rule, as dragging does), title and message;
- **Where:** draw a rectangle or a polygon, move the corners of the current shape, remove it (the rule then applies anywhere), or give it the Arctic or Antarctic from a latitude;
- **When:** from and to dates;
- **What it applies to:** one field per dimension (see the table below);
- **GeoJSON:** the rule as the rules file holds it, kept up to date as you edit, with **Copy**. The page remembers whether you keep it open;
- **Delete**, which asks you to click a second time.

Other properties of a rule, such as its instruction, references and evidence, are kept as they are and shown in Check.

Every edit is checked by queryearth before it is kept. If queryearth refuses one, the field keeps what you typed, marked in red, and the line at the bottom of the page says why.

**Dimensions.** What the rules can depend on besides place and time. Labels are names, such as a product; an axis is numbers in a unit, such as a resolution in km. A rules file does not list them, so the page reads them from the rules' values: a range such as `{"lt": 8, "unit": "km"}` makes an axis in that unit, and a name or a list of names makes labels. Set an axis's unit here when its rules give none, add a dimension to check against, or remove one no rule uses.

**File.** **Download rules file** saves the rules as queryearth writes rule files, and **Copy rules file** copies the same text, to paste into a file, a gist or a message. **Download as web page** saves a page that shows them; see [Sharing](#sharing). The same two buttons are at the top of the page in Edit mode.

Edits you have not downloaded are kept in your browser. When you come back to the same page address, Edit mode offers them back; the page switches to Edit to show you, unless its address asked for Check.

### Which mode a page opens in

`#edit` at the end of the address opens Edit mode and `#check` opens Check mode, also after a link's `?src=`: `https://crocodile-cesm.github.io/vizqueryearth/?src=<link>#edit`. Otherwise the page itself opens in the mode you used last, and a site's page or a downloaded web page opens in Check. Switching modes changes the `#` in the address, so you can share the address as it is.

What to type for a dimension:

| Kind | In a rule | In Check your area |
|---|---|---|
| labels | names separated by commas: `glorys, era5*` (`*` and `?` match any letters) | `glorys` |
| axis | `<8`, `<=8`, `>2`, `>=2`, several such as `>2, <=8`, or `2-8` (from 2 up to, not including, 8) | a number or a range: `8`, `5-10` |

## Rules files

A rules file is a GeoJSON FeatureCollection with one Feature per rule, as queryearth 0.7 reads and writes it (`Registry.from_file`, `Registry.to_file`); see [Rule files](https://crocodile-cesm.github.io/queryearth/) in the queryearth docs. Open one with **Open file** or **Open link**, or give its address in the page's own: `?src=<link>`. A file that needs a later queryearth than the page's is not opened, and the line at the bottom of the page says which release it needs.

**Older files.** Files written for queryearth 0.6 or before open where they map onto 0.7: each code takes the path of the category it was in (`OBC001`, in `OBC` in `DOMAIN`, becomes `DOMAIN/OBC/OBC001`; the categories were called `groups` before 0.6), the dimensions the file declared become the page's, and a record's `box` becomes its geometry. They are saved as 0.7 files. Category titles are not kept. A rule that 0.7 cannot read as its author meant, such as an edge rule or one that recurs every year, is refused, and the page names it.

## Sharing

**A link.** Put your rules file where other sites may read it, then share the page with `?src=` (and `#edit` at the end for people who will edit it):

```
https://crocodile-cesm.github.io/vizqueryearth/?src=https://raw.githubusercontent.com/<you>/<repo>/main/rules.geojson
```

The file's host must allow cross-origin reads, as raw files on GitHub and gists do. Many other hosts do not; the page then says it could not open the link.

**Your own page.** **Download as web page** gives an `index.html` that holds the rules file, the dimensions, the title you give it and the view of the globe you see. It loads the app itself from GitHub Pages, so it is one small file you can host anywhere:

- GitHub Pages: make a repository, add `index.html`, then in Settings → Pages choose "Deploy from a branch", `main` and `/ (root)`. The page appears at `https://<you>.github.io/<repository>/` after a minute.
- Netlify Drop: drag a folder holding `index.html` onto https://app.netlify.com/drop.
- Any static web host, or open the file from your computer.

To change the rules later, open the page, edit, and download it again.

## Adding a page to this site

Curated pages live in this repository under `web/sites/<name>/` and appear at `https://crocodile-cesm.github.io/vizqueryearth/sites/<name>/`. To add one, open a pull request with a folder holding three files:

- `index.html`: a copy of `web/sites/demo/index.html`, with your title in `<title>`;
- `rules.geojson`: the rules;
- `site.json`: the page's settings.

`site.json`:

| Field | What it is |
|---|---|
| `title` | The page's title, at the top and in the browser tab. |
| `description` | A sentence or two shown above Check your area. Optional. |
| `rules` | The rules file: a path relative to the folder (`"rules.geojson"`), a URL, or the FeatureCollection itself. |
| `dimensions` | Optional: dimensions to declare before those read from the rules, such as one no rule uses yet or an axis's unit: `[{"name": "product", "kind": "labels"}, {"name": "resolution", "kind": "axis", "unit": "km"}]`. |
| `view` | Optional: where the globe starts, `{"center": [lon, lat], "zoom": 1.6}`. Without it, the globe turns to the rules. |

For example, `web/sites/demo/site.json`:

```json
{
  "title": "vizqueryearth demo",
  "description": "Made-up rules about a made-up ocean product, demo_ocean. ...",
  "rules": "rules.geojson",
  "view": {"center": [-150, 45], "zoom": 1.6}
}
```

## Using it from Python

The page's Python is a small package, not on PyPI; to work with rule files in Python, use queryearth itself. It needs Python 3.11 or later and `queryearth>=0.7,<0.8`. `vizqueryearth.Session` holds the rules a page shows and answers its calls, `upgrade()` turns a file from queryearth 0.6 or before into the 0.7 form, and `infer()` reads a file's dimensions from its rules:

```python
import json

import queryearth as qe
from vizqueryearth import infer, upgrade

data, declared = upgrade(json.load(open("old_rules.geojson")))
dimensions = infer(data["features"], declared)  # [{"name", "kind", "unit"}]
```

## Local development

```bash
pip install -e ".[test]"
pytest                               # the Python tests
python -m http.server 8000 -d web    # then open http://localhost:8000/sites/demo/
```

`web/py/vizqueryearth` is a link to the package, so the page runs the Python you are editing (on Windows, clone with `git config core.symlinks true`). The browser tests drive the page in headless Chromium; they are skipped unless Playwright is installed:

```bash
pip install playwright
python -m playwright install chromium
pytest tests/browser
```

## How it works

Everything runs in your browser. The page loads [MapLibre GL](https://maplibre.org/) for the globe, [Terra Draw](https://terradraw.io/) for drawing, land from [Natural Earth](https://www.naturalearthdata.com/), and [Pyodide](https://pyodide.org/) (Python in WebAssembly) with numpy, shapely, queryearth from PyPI and this package's Python. Everything that touches a rule goes through queryearth, so the page can never save a file that queryearth would refuse or read differently. The library versions are pinned at the top of `web/app.js`. The design and its reasons are in `docs/design.md`.

## Known limits

- Shapes that cross the date line, reach a pole or have holes cannot be edited corner by corner: draw a new shape instead.
- A category with no rules is kept only while the page is open.
- Saving is by download. Unsaved edits are kept in your browser, as a safety net, and offered back when you return to the same page address; downloading the rules file clears them.
- Some embedded browsers, such as an editor's preview pane, block downloads. The page says so; open it in a normal browser.
- Where a browser does not let the page copy, the Copy buttons select the text instead, and the line at the bottom of the page says to press Ctrl+C (⌘C on a Mac).
- The globe draws map data only to about 85° north and south and fills the poles from there. South of 84°S the land is drawn as one band, which also covers the last degree of the Ross Ice Shelf. A point drawn within half a degree of a pole is taken to be on it.
- A downloaded web page loads the app from GitHub Pages, so it changes when the app does.
- Opening a link needs a host that allows cross-origin reads.
- The page knows two kinds of dimension, labels and axes, and cannot run one you wrote in Python. A file that uses your own dimension is refused, or, where its values look like names, read as labels, which match differently: then checks against that dimension give wrong answers.

## License

Apache-2.0
