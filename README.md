# vizqueryearth

A web page for [queryearth](https://github.com/CROCODILE-CESM/queryearth) rule files. It shows the rules on a globe, tells you which of them apply to your area, your dates and what you use, and lets you edit them: their shapes, time, dimensions and changes.

It runs entirely in your browser. There is no server and no sign-in, and nothing is stored online: you open a rules file from your computer or from a link, and you save by downloading.

## Try it

- The demo, with made-up rules: https://crocodile-cesm.github.io/vizqueryearth/sites/demo/
- The page itself, to open your own rules: https://crocodile-cesm.github.io/vizqueryearth/

The first visit downloads about 20 MB (Python and queryearth, see [How it works](#how-it-works)); later visits are quicker.

## Using the page

The globe is on the left and the panel on the right. The page has two modes, switched at the top: **Check**, for people who read the rules, and **Edit**, for people who write them. **Open file** and **Open link** work in both.

### Check

**Check your area.** Draw a rectangle or a polygon where you work, or leave it empty to ask about anywhere. Give dates if you like, and a value for each dimension the rules use, such as a product or a resolution. **Check** lists the rules that apply and highlights them on the globe. "No rule applies" means only that no rule matched, not that all is well. Tick **Also list rules that need more information** to see the rules that would apply if they knew more, such as a variable you left empty. Click a result to open that rule below.

**Rules.** The rules are a tree: **All rules** at the root, then the categories, their subcategories at any depth, and the rules in each, sorted by code. A rule's category is the prefix of its code: `OBC` for `OBC001`. Rules whose prefix is not a category are under **Uncategorized**, at the end. Each category shows its title, its prefix and how many rules are in it, at any depth. The categories start closed. Open or close a branch with its arrow; the page remembers which you opened, in this browser.

Click a category to show its rules on the globe, and those of every category in it; the globe turns to them. Type in the filter box to show only the rules whose code or title has those letters (`OBC`, `strait`, `gulf`), with the categories they are in, opened; the globe shows them too and turns to them. Clear the filter and the branches are as you left them. The page remembers your filter. The tree works from the keyboard: the arrow keys move up and down and open and close branches, Home and End go to the first and last item, and Enter or Space picks a category or opens a rule.

Click a rule in the tree, its label or its shape on the globe to open its card, with its categories opened in the tree: the globe turns to it, and the card shows what the rule says and what it covers: its level, code, title, category and message, what to do, any changes, where and when it applies, what it applies to, and its references and evidence. **Copy GeoJSON** on the card copies the rule's record, as the rules file holds it. Edge rules (see below) have a dashed outline and a lighter fill on the globe, and an "edge" tag.

### Edit

**Rules.** The same tree, one line to a row, where you also manage the rules and categories:

- To move a rule, drag it by its handle (⠿) onto a category, or pick another **Category** in its form. To move a category, drag it onto another one (or onto **All rules**, for the top level), or use **Move to…** in its **⋯**. A rule that moves takes the next code in its new category, and keeps its old code in its `aliases`, so the old code still finds it and is never given to another rule: "ITF003 is now OBC006; ITF003 kept as an alias". A category that moves takes its rules and subcategories with it; the page refuses a move that would put a category inside itself, and says why;
- **+ Rule** on a category adds a rule with the next code in it, such as `OBC010` after `OBC009`; on **All rules** it adds one to the first category (or, in a file without categories, continues the last rule's prefix);
- **+ Category** on **All rules** adds a top-level category, with its prefix and title; **⋯** on a category moves it, renames it, adds a subcategory in it, or removes it. A category that still holds rules or subcategories is not removed, and the page says why. Once a file has categories, every rule's prefix must be one of them, so a file whose rules have none yet gets them all at once, with **Make a category for each prefix**; then give them titles and arrange them.

Clicking a rule opens its form in the tree:

- code, level, category (picking another moves the rule, as dragging does), title and message;
- **Where:** draw a rectangle or a polygon, move the corners of the current shape, remove it (the rule then applies anywhere), or give it an Arctic or Antarctic cap from a latitude. Tick **Applies where a domain's edge crosses this area** for an edge rule: it applies where the edge of the area you check crosses its shape, not wherever they overlap, for advice about where to put a domain's open boundaries;
- **When:** from and to dates, and the months of every year it applies;
- **What it applies to:** one field per dimension (see the table below);
- **Changes:** what to change when the rule applies, as rows of target, key, value and an optional reason. The value is JSON, such as `900`, `true` or `"CICE"`; plain text is taken as text. A rule with changes is info by default, one without is a warning;
- **GeoJSON:** the rule's record as the rules file holds it, laid out as queryearth writes rule files and packs (indented, with each list of numbers, such as a corner, on one line), kept up to date as you edit, with **Copy** to copy it. Saved as a file, it is that rule's file in a pack. The page remembers whether you keep it open;
- **Delete**, which asks you to click a second time.

Every edit is checked by queryearth before it is kept. If queryearth refuses one, the field keeps what you typed, marked in red, and the line at the bottom of the page says why.

**Dimensions.** What the rules can depend on besides place and time. Labels are names, such as a product; an axis is numbers with a unit, such as a resolution in km; versions are such as `4.07` or `ERA5T`. Add or remove them here; the rules file keeps the list.

**File.** **Download rules file** saves the rules, laid out as queryearth writes rule files, and **Copy rules file** copies the same text, to paste into a file, a gist or a message. **Download as web page** saves a page that shows them; see [Sharing](#sharing). The same two buttons are at the top of the page in Edit mode.

Edits you have not downloaded are kept in your browser. When you come back to the same page address, Edit mode offers them back; the page switches to Edit to show you, unless its address asked for Check.

### Which mode a page opens in

`#edit` at the end of the address opens Edit mode and `#check` opens Check mode, also after a link's `?src=`: `https://crocodile-cesm.github.io/vizqueryearth/?src=<link>#edit`. Otherwise the page itself opens in the mode you used last, and a site's page or a downloaded web page opens in Check. Switching modes changes the `#` in the address, so you can share the address as it is.

What to type for a dimension:

| Kind | In a rule | In Check your area |
|---|---|---|
| labels | names separated by commas: `glorys, era5*` (`*` and `?` match any letters) | `glorys` |
| axis | `<8`, `<=8`, `>2`, `>=2`, several such as `>2, <=8`, or `2-8` (from 2 up to, not including, 8) | a number or a range: `8`, `5-10` |
| versions | `4.07, ERA5T`, or JSON such as `{"introduced": "4.00", "fixed": "4.09"}` | `4.07` |

Anything else queryearth reads, such as a list of ranges `[{"lt": 5}, {"gt": 50}]` or `{"any_of": [...], "none_of": [...]}`, can be typed as JSON.

## Rules files

A rules file is a GeoJSON FeatureCollection of queryearth records; see [Writing rules](https://crocodile-cesm.github.io/queryearth/) in the queryearth docs. Open one with **Open file** or **Open link**, or give its address in the page's own: `?src=<link>`.

A rules file says, next to its `features`, which queryearth file format it uses, its categories and the dimensions its rules use:

```json
{
  "type": "FeatureCollection",
  "queryearth": "0.5",
  "categories": {
    "DOMAIN": "Domain design",
    "OBC": {"title": "Open boundaries", "parent": "DOMAIN"},
    "ITF": "Coral Triangle and the Indonesian Throughflow"
  },
  "dimensions": [
    {"name": "product", "kind": "labels"},
    {"name": "resolution", "kind": "axis", "unit": "km"}
  ],
  "features": [...]
}
```

A category is its title, or its title and the category it sits in (its `parent`, which comes first in the list). This is how queryearth 0.6 writes and reads rule files (`Registry.to_file`, `Registry.from_file`), and the page always writes these members; `categories` only when there are some. All of them are optional when you open a file. Files written for queryearth 0.4 and 0.5 call the categories `groups`; they open as they are and are written for 0.6. Without `dimensions`, the page uses the dimensions its site declares, or else guesses them from the rules. A file that needs a later queryearth than the page's is not opened, and the line at the bottom of the page says which release it needs.

Rules you do not edit are written back as they were read.

## Sharing

**A link.** Put your rules file where other sites may read it, then share the page with `?src=` (and `#edit` at the end for people who will edit it):

```
https://crocodile-cesm.github.io/vizqueryearth/?src=https://raw.githubusercontent.com/<you>/<repo>/main/rules.geojson
```

The file's host must allow cross-origin reads, as raw files on GitHub and gists do. Many other hosts do not; the page then says it could not open the link.

**Your own page.** **Download as web page** gives an `index.html` that holds the rules file, with its categories and dimensions, the title you give it and the view of the globe you see. It loads the app itself from GitHub Pages, so it is one small file you can host anywhere:

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
| `dimensions` | Optional, for a rules file that does not declare them: `[{"name": "product", "kind": "labels"}, {"name": "resolution", "kind": "axis", "unit": "km"}]`, with `kind` one of `axis`, `labels` or `versions`, and `unit` for an axis only. |
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

The page's Python is a small package you can use in scripts. It is not on PyPI:

```bash
pip install git+https://github.com/CROCODILE-CESM/vizqueryearth
```

It needs Python 3.11 or later and `queryearth>=0.6,<0.7`.

```python
import queryearth as qe
from vizqueryearth import RuleFile, arctic

rules = RuleFile.read("rules.geojson")  # with the categories and dimensions it declares
i = rules.new("ICE")  # the next code in the category, such as ICE002
rules.update(
    i,
    title="Sea ice",
    message="North of 66.5°N, check the sea ice.",
    time=["2000-01-01", ""],
    months=[12, 1, 2],
    dimensions={"product": ["demo_ocean"]},
)
rules.set_shape(i, arctic(66.5))
rules.write("rules.geojson")  # checked by queryearth, then written in one step
findings = rules.query(
    space=qe.space.point(0, 80),
    time=qe.interval("2001-01-01", "2001-01-31"),
    dimensions={"product": "demo_ocean"},
)
print(qe.report(findings))
```

`RuleFile` checks every edit with queryearth and refuses what queryearth would refuse; `problems()` lists what queryearth refuses in the file as it stands. `set_categories()` and `set_dimensions()` declare categories (in queryearth's form, parents first or moved there) and dimensions, `category_paths()` gives the categories each sits in, `move(i, "OBC")` moves a rule to another category (a new code, the old one kept as an alias), `order()` gives the rules sorted by code, and `update(i, edge=True)` makes an edge rule. `vizqueryearth.shapes` turns drawn GeoJSON into rule shapes (`from_drawn`).

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
- Saving is by download. Unsaved edits are kept in your browser, as a safety net, and offered back when you return to the same page address; downloading the rules file clears them.
- Some embedded browsers, such as an editor's preview pane, block downloads. The page says so; open it in a normal browser.
- Where a browser does not let the page copy, the Copy buttons select the text instead, and the line at the bottom of the page says to press Ctrl+C (⌘C on a Mac).
- The globe draws map data only to about 85° north and south and fills the poles from there. South of 84°S the land is drawn as one band, which also covers the last degree of the Ross Ice Shelf. A point drawn within half a degree of a pole is taken to be on it.
- A downloaded web page loads the app from GitHub Pages, so it changes when the app does.
- Opening a link needs a host that allows cross-origin reads.

## License

Apache-2.0
