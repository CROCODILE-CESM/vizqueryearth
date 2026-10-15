"""The web page in headless Chromium, used as a person would use it.

Needs playwright and its Chromium (python -m playwright install chromium), and
network access: the page loads its libraries, Pyodide and queryearth from CDNs.
Without playwright these tests are skipped.

QUERYEARTH_WHEEL=path/to/queryearth-X-py3-none-any.whl tests a queryearth that
is not on PyPI yet: the tests then serve a copy of web/ that installs it.
CROCODASH_RULES=path/to/qe_rules.geojson adds a test on CrocoDash's rules.
"""

import functools
import http.server
import json
import os
import re
import shutil
import threading
from pathlib import Path
from urllib.parse import urljoin

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

WEB = Path(__file__).resolve().parents[2] / "web"
START = 300_000  # ms; the first start downloads Python and queryearth
WEBGL = [
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
]
APP = "window.__vizqueryearth"


class Files(http.server.SimpleHTTPRequestHandler):
    """A static web host that, like GitHub Pages, lets other sites read its files."""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def serve():
    """Serve a folder on a port of its own, so each folder is its own site."""
    servers = []

    def start(folder):
        handler = functools.partial(Files, directory=str(folder))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()


@pytest.fixture(scope="module")
def app(serve, tmp_path_factory):
    wheel = os.environ.get("QUERYEARTH_WHEEL")
    if not wheel:
        return serve(WEB)
    web = tmp_path_factory.mktemp("app") / "web"
    shutil.copytree(WEB, web)  # with web/py's link followed
    shutil.copy(wheel, web)
    url = serve(web)
    script = web / "app.js"
    pinned = r'const QUERYEARTH = "[^"]*"'
    wanted = f'const QUERYEARTH = "{url}/{Path(wheel).name}"'
    script.write_text(re.sub(pinned, wanted, script.read_text(), count=1))
    return url


@pytest.fixture(scope="module")
def context():
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=WEBGL)
        yield browser.new_context(
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            permissions=["clipboard-read", "clipboard-write"],
        )
        browser.close()


def visit(context, url, rules, fresh=True):
    """Open a page and wait until it shows its rules; returns it and its errors."""
    page = context.new_page()
    if fresh:  # forget the drafts, filters and modes of earlier tests
        page.goto(urljoin(url, "/app.css"))
        page.evaluate("localStorage.clear()")
    errors = []
    page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
    page.on(
        "console",
        lambda msg: msg.type == "error" and errors.append(f"console: {msg.text}"),
    )
    page.on("dialog", lambda d: (errors.append(f"dialog: {d.message}"), d.dismiss()))
    page.goto(url)
    ready(page, rules)
    return page, errors


def mode(page):
    return page.evaluate(f"{APP}.page.mode")


def ready(page, rules):
    page.wait_for_function(
        f"{APP} && {APP}.page.state && {APP}.page.state.rules.length === {rules}",
        timeout=START,
    )


def state(page):
    return page.evaluate(f"{APP}.page.state")


def settle(page):
    """Wait for the globe to stop moving, and for Python to answer."""
    page.wait_for_function(f"!{APP}.map().isMoving()")
    page.wait_for_timeout(400)


def listed(page):
    """The codes of the rules the tree shows, in its order."""
    return page.locator("#rule-tree .rule-row .code").all_inner_texts()


def open_rule(page, code):
    """Open the categories a rule is in, and click it to read or edit it, unless
    it is open already."""
    rule = next(r for r in state(page)["rules"] if r["code"] == code)
    for id in [f"cat:{p}" for p in rule["path"]] or ["uncategorized"]:
        if node(page, id).get_attribute("aria-expanded") == "false":
            row(page, id).locator(".twisty").click()
    if page.evaluate(f"{APP}.page.selected") != rule["index"]:
        row(page, f"rule:{rule['index']}").locator(".code").click()


def open_all(page):
    """Open every branch of the tree."""
    closed = page.locator('#rule-tree [aria-expanded="false"] > .tree-row .twisty')
    while closed.count():
        closed.first.click()


def node(page, id):
    """A node of the tree: "all", "cat:OBC", "uncategorized" or "rule:5"."""
    return page.locator(f'#rule-tree [data-node="{id}"]')


def row(page, id):
    return page.locator(f'#rule-tree [data-node="{id}"] > .tree-row')


def new_rule(page, category=None):
    """+ Rule on a category, or on the root for the first category."""
    if category:
        name = f"New rule in {category}"
        row(page, f"cat:{category}").get_by_role("button", name=name).click()
    else:
        row(page, "all").get_by_role("button", name="+ Rule").click()


def focused(page):
    return page.evaluate("document.activeElement.dataset.node")


def on_globe(page):
    """The positions of the rules the globe shows."""
    script = f"""(async () => (await {APP}.map().getSource("rules").getData())
        .features.map(f => f.properties.index))()"""
    return sorted(page.evaluate(script))


def click_at(page, lon, lat):
    x, y = page.evaluate(f"""(() => {{
            const map = {APP}.map();
            const p = map.project([{lon}, {lat}]);
            const box = map.getContainer().getBoundingClientRect();
            return [box.left + p.x, box.top + p.y];
        }})()""")
    page.mouse.click(x, y)
    page.wait_for_timeout(250)
    return x, y


def test_check_an_area(app, context):
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    st = state(page)
    assert [d["name"] for d in st["dimensions"]] == ["product", "variable", "model"]
    assert st["values"]["variable"] == ["so", "thetao"]

    check = page.locator("#check")
    check.get_by_role("button", name="Draw rectangle").click()
    click_at(page, 172, 56)  # across the date line
    click_at(page, -168, 63)
    page.wait_for_function(f"{APP}.page.areaShape !== null")
    assert page.evaluate(f"{APP}.page.areaShape.fill.type") == "MultiPolygon"

    page.fill("#q-start", "2001-01-01")
    page.fill("#q-end", "2001-03-31")
    page.fill("[data-dim=product]", "demo_ocean")
    page.fill("[data-dim=variable]", "thetao")
    check.get_by_role("button", name="Check", exact=True).click()
    page.wait_for_function(f"{APP}.page.results !== null")
    codes = page.evaluate(f"{APP}.page.results.findings.map(f => f.code)")
    assert codes == ["OCN002"]

    page.fill("[data-dim=variable]", "")
    page.check("#q-conditional")
    check.get_by_role("button", name="Check", exact=True).click()
    page.wait_for_timeout(1000)
    found = page.evaluate(
        f"{APP}.page.results.findings.map(f => [f.code, f.conditional_on])"
    )
    assert ["OCN003", ["variable"]] in found

    page.locator(".card", has_text="OCN002").click()  # selects it, below
    page.wait_for_timeout(500)
    assert page.evaluate(f"{APP}.page.selected") == 1
    card = node(page, "rule:1")
    assert "too warm in the Bering Sea" in card.inner_text()
    assert page.locator(".rule-form").count() == 0  # read only
    assert not errors


def test_edit_rules_and_download_them(app, context, serve, tmp_path):
    page, errors = visit(context, f"{app}/sites/demo/#edit", 5)
    new_rule(page)  # in the first category
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    assert state(page)["rules"][5]["code"] == "OCN004"
    assert page.input_value("#f-code") == "OCN004"

    # draw its shape
    page.evaluate(f"{APP}.map().jumpTo({{center: [-90, 25], zoom: 3}})")
    settle(page)
    form = page.locator(".rule-form")
    form.get_by_role("button", name="Draw polygon").click()
    first = click_at(page, -97, 20)
    for lon, lat in [(-82, 20), (-84, 29), (-96, 29)]:
        click_at(page, lon, lat)
    page.mouse.click(*first)
    page.wait_for_function(f"{APP}.page.state.rules[5].fill !== null")
    assert state(page)["rules"][5]["fill"]["type"] == "Polygon"

    # its fields; a refused code stays as typed, marked
    def type_in(selector, text):
        page.fill(selector, text)
        page.locator(selector).blur()
        page.wait_for_timeout(500)

    type_in("#f-title", "Gulf test rule")
    page.select_option("#f-level", "error")
    page.wait_for_timeout(500)
    rule = state(page)["rules"][5]
    assert (rule["title"], rule["level"]) == ("Gulf test rule", "error")
    type_in("#f-code", "OCN001")
    assert "already in the file" in page.inner_text("#status")
    assert page.get_attribute("#f-code", "aria-invalid") == "true"
    assert state(page)["rules"][5]["code"] == "OCN004"

    # time, months, a dimension and a change
    type_in("#f-start", "2001-01-01")
    for month in ("Dec", "Jan"):
        page.locator(".months label", has_text=month).locator("input").check()
        page.wait_for_timeout(500)
    type_in("[data-rule-dim=product]", "demo_ocean")
    page.get_by_role("button", name="Add change").click()
    row = page.locator("#f-changes .change-row").last
    for part, text in [("target", "MOM_input"), ("key", "DT"), ("value", "900")]:
        row.locator(f"[data-part={part}]").fill(text)
    row.locator("[data-part=value]").blur()
    page.wait_for_timeout(800)
    rule = state(page)["rules"][5]
    assert rule["time"]["start"] == "2001-01-01"
    assert sorted(rule["time"]["months"]) == [1, 12]
    assert rule["dimensions"]["product"] == "demo_ocean"
    assert rule["changes"] == [
        {"target": "MOM_input", "key": "DT", "value": "900", "rationale": ""}
    ]

    page.fill("#cap-north", "70")
    page.get_by_role("button", name="Arctic cap from", exact=True).click()
    page.wait_for_timeout(800)
    rule = state(page)["rules"][5]
    assert rule["fill"] is not None and rule["editable"] is None

    # declare a dimension
    page.fill("#d-name", "resolution")
    page.select_option("#d-kind", "axis")
    page.fill("#d-unit", "km")
    page.locator("#dimensions").get_by_role("button", name="Add", exact=True).click()
    page.wait_for_function(f"{APP}.page.state.dimensions.length === 4")

    # move a corner of OCN001, a polygon
    open_rule(page, "OCN001")
    settle(page)  # selecting turns the globe to the rule
    before = state(page)["rules"][0]["fill"]
    page.get_by_role("button", name="Move corners").click()
    lon, lat = before["coordinates"][0][0]
    page.evaluate(f"{APP}.map().jumpTo({{center: [{lon}, {lat}], zoom: 4}})")
    settle(page)
    x, y = click_at(page, lon, lat)
    page.mouse.click(x + 40, y + 40)  # pick the polygon, inside it
    page.wait_for_timeout(400)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 30, y - 30, steps=8)
    page.mouse.up()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Done").click()
    page.wait_for_timeout(1000)
    assert state(page)["rules"][0]["fill"] != before

    # download the rules file
    file = page.locator("#file")
    with page.expect_download() as info:
        file.get_by_role("button", name="Download rules file").click()
    saved = json.loads(Path(info.value.path()).read_text())
    assert len(saved["features"]) == 6
    assert saved["dimensions"][-1] == {
        "name": "resolution",
        "kind": "axis",
        "unit": "km",
    }

    # download a web page, and open it from another site
    page.fill("#page-title", "Bering test page")
    with page.expect_download() as info:
        file.get_by_role("button", name="Download as web page").click()
    site = tmp_path / "site"
    site.mkdir()
    info.value.save_as(site / "index.html")
    html = (site / "index.html").read_text()
    assert "Bering test page" in html and '"OCN004"' in html and '"categories"' in html
    elsewhere, more_errors = visit(context, f"{serve(site)}/", 6)
    assert elsewhere.title() == "Bering test page"
    elsewhere.close()

    # deleting asks first
    open_rule(page, "OCN004")
    settle(page)
    page.get_by_role("button", name="Delete OCN004").click()
    page.get_by_role("button", name="Click again to delete OCN004").click()
    page.wait_for_function(f"{APP}.page.state.rules.length === 5")
    assert not errors and not more_errors


def test_open_a_rules_file_by_link(app, context):
    page, errors = visit(context, f"{app}/", 0)
    center = page.evaluate(f"{APP}.map().getCenter().toArray()")
    assert center == pytest.approx([-30, 30])  # the default view
    page.get_by_role("button", name="Open link").click()
    page.fill("#link-url", f"{app}/sites/demo/rules.geojson")
    page.locator("#linkbar").get_by_role("button", name="Open", exact=True).click()
    ready(page, 5)
    assert "src=" in page.url  # the address now opens these rules
    settle(page)
    lon = page.evaluate(f"{APP}.map().getCenter().lng")
    assert lon > 165 or lon < -80  # turned to the rules, across the date line
    page.evaluate(f"{APP}.map().jumpTo({{center: [20, 0], zoom: 2}})")
    page.get_by_role("button", name="Fit to rules").click()
    settle(page)
    lon = page.evaluate(f"{APP}.map().getCenter().lng")
    assert lon > 165 or lon < -80
    page.close()

    page, more_errors = visit(context, f"{app}/?src={app}/sites/demo/rules.geojson", 5)
    assert not errors and not more_errors


def test_unsaved_edits_are_offered_back(app, context):
    page, errors = visit(context, f"{app}/sites/demo/#edit", 5)
    new_rule(page)
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    page.wait_for_timeout(500)
    page.goto(f"{app}/sites/demo/")  # a site page opens in Check, but for the draft
    ready(page, 5)
    assert mode(page) == "edit" and page.url.endswith("#edit")
    page.goto(f"{app}/sites/demo/#check")  # asked for Check: a notice points to Edit
    page.wait_for_function(f"{APP}.page.mode === 'check'")
    page.get_by_role("button", name="Go to Edit to restore them").click()
    page.get_by_role("button", name="Restore them").click()
    ready(page, 6)
    assert not errors


def test_sort_and_filter_the_rules(app, context):
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    open_all(page)
    assert listed(page) == ["OCN001", "OCN002", "OCN003", "ICE001", "OBC001"]
    page.fill("#rule-filter", "ICE")  # a code or a title, in any case
    assert listed(page) == ["ICE001"] and on_globe(page) == [2]
    page.fill("#rule-filter", "bering")
    assert listed(page) == ["OCN002"] and on_globe(page) == [1]
    page.wait_for_timeout(700)  # once typing stops, the globe turns to the rules left
    settle(page)
    lon = page.evaluate(f"{APP}.map().getCenter().lng")
    assert lon > 165 or lon < -160  # the Bering Sea, across the date line
    page.fill("#rule-filter", "")

    row(page, "cat:DOMAIN").locator(".name").click()  # a category, at any depth
    settle(page)
    assert on_globe(page) == [2, 4]
    row(page, "cat:OBC").locator(".name").click()
    settle(page)  # the globe turns to the category's rules
    assert on_globe(page) == [4]
    assert 128 < page.evaluate(f"{APP}.map().getCenter().lng") < 150
    assert row(page, "rule:4").locator(".tag").inner_text() == "edge"

    page.reload()  # each viewer's filter is kept
    ready(page, 5)
    assert on_globe(page) == [4]
    assert "picked" in row(page, "cat:OBC").get_attribute("class")
    row(page, "all").locator(".name").click()
    assert on_globe(page) == [0, 1, 2, 4]  # OCN003 has no shape
    assert not errors


def test_categories_new_codes_and_edge_rules(app, context):
    page, errors = visit(context, f"{app}/sites/demo/#edit", 5)
    row(page, "cat:DOMAIN").get_by_role("button", name="More for DOMAIN").click()
    page.fill("#new-prefix-DOMAIN", "grid")  # taken in capitals
    page.fill("#new-title-DOMAIN", "Grids")
    page.get_by_role("button", name="Add subcategory").click()
    page.wait_for_function(f"{APP}.page.state.categories.length === 5")
    assert state(page)["tree"] == ["OCN", "DOMAIN", "ICE", "OBC", "GRID"]

    # a new rule takes the next code in its category
    new_rule(page, "OBC")
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    assert page.input_value("#f-code") == "OBC002"
    new_rule(page, "GRID")
    page.wait_for_function(f"{APP}.page.state.rules.length === 7")
    assert page.input_value("#f-code") == "GRID001"

    # a category with rules cannot be removed; without them it can
    row(page, "cat:GRID").get_by_role("button", name="More for GRID").click()
    page.get_by_role("button", name="Remove GRID").click()
    page.wait_for_timeout(300)
    assert "GRID still has rules" in page.inner_text("#status")
    open_rule(page, "GRID001")
    page.get_by_role("button", name="Delete GRID001").click()
    page.get_by_role("button", name="Click again to delete GRID001").click()
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    page.get_by_role("button", name="Remove GRID").click()  # its actions still open
    page.wait_for_function(f"{APP}.page.state.categories.length === 4")

    # the edge box goes to the file; a rule without a shape cannot have it
    open_rule(page, "OCN002")
    settle(page)
    page.check("#f-edge")
    page.wait_for_function(f"{APP}.page.state.rules[1].edge === true")
    open_rule(page, "OCN003")
    settle(page)
    page.click("#f-edge")
    page.wait_for_timeout(500)
    assert "needs a space" in page.inner_text("#status")
    assert not page.is_checked("#f-edge")
    with page.expect_download() as info:
        page.locator("#file").get_by_role("button", name="Download rules file").click()
    saved = json.loads(Path(info.value.path()).read_text())
    assert saved["queryearth"] == "0.6" and "groups" not in saved
    assert list(saved["categories"]) == ["OCN", "DOMAIN", "ICE", "OBC"]
    assert saved["categories"]["OBC"] == {
        "title": "Open boundaries",
        "parent": "DOMAIN",
    }
    props = {f["properties"]["code"]: f["properties"] for f in saved["features"]}
    assert props["OCN002"]["edge"] is True and props["OBC001"]["edge"] is True
    assert "edge" not in props["OCN003"] and "OBC002" in props
    assert not errors


def test_a_file_for_a_later_queryearth_is_not_opened(app, context, serve, tmp_path):
    later = json.loads((WEB / "sites" / "demo" / "rules.geojson").read_text())
    (tmp_path / "later.geojson").write_text(json.dumps(later | {"queryearth": "9.0"}))
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    page.get_by_role("button", name="Open link").click()
    page.fill("#link-url", f"{serve(tmp_path)}/later.geojson")
    page.locator("#linkbar").get_by_role("button", name="Open", exact=True).click()
    page.wait_for_function(
        "document.getElementById('status').textContent.includes('9.0')"
    )
    assert "this file needs queryearth 9.0 or later" in page.inner_text("#status")
    assert len(state(page)["rules"]) == 5 and "src=" not in page.url
    assert not errors


def test_check_and_edit_modes(app, context):
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    assert mode(page) == "check"  # a site page opens in Check
    assert page.locator("#check").is_visible()
    for hidden in ("#dimensions", "#file", ".rule-form", ".tree-row button", ".drag"):
        assert page.locator(hidden).count() == 0
    assert page.get_by_role("button", name="+ Rule").count() == 0
    header = page.locator("header")
    assert not header.get_by_role("button", name="Download rules file").is_visible()
    assert header.get_by_role("button", name="Open link").is_visible()

    # a rule's card, read only: its row, then what it says
    open_rule(page, "OCN002")
    settle(page)
    card = node(page, "rule:1")
    text = card.inner_text()
    for shown in (
        "WARNING",  # level
        "OCN002",
        "demo_ocean is too warm in the Bering Sea",  # title
        "runs about 1 K too warm",  # message
        "What to do: Compare demo_ocean",  # instruction
        "product: demo_ocean",  # dimensions
        "Any time.",
        "Made up for this demo",  # evidence
    ):
        assert shown in text
    link = card.get_by_role("link", name="queryearth: writing rules")
    assert link.get_attribute("href") == "https://crocodile-cesm.github.io/queryearth/"
    open_rule(page, "ICE001")
    assert 'case ice = "CICE"' in page.locator(".rule-card").inner_text()  # changes
    open_rule(page, "OCN003")
    assert "From 1993-01-01 to 2003-12-31." in page.locator(".rule-card").inner_text()
    open_rule(page, "OBC001")
    settle(page)
    assert "edge" in row(page, "rule:4").locator(".tag").inner_text()
    assert "Where a domain's edge crosses" in node(page, "rule:4").inner_text()

    # an area drawn in Check stays there; Edit hides it, and cancels drawing
    page.evaluate(f"{APP}.map().jumpTo({{center: [0, 20], zoom: 2}})")
    settle(page)
    page.locator("#check").get_by_role("button", name="Draw rectangle").click()
    click_at(page, -10, 10)
    click_at(page, 10, 30)
    page.wait_for_function(f"{APP}.page.areaShape !== null")
    page.locator("#check").get_by_role("button", name="Draw polygon").click()
    page.locator(".modes").get_by_role("button", name="Edit").click()
    assert mode(page) == "edit" and page.url.endswith("#edit")
    assert page.evaluate(f"{APP}.page.drawing") is None
    assert area_on_globe(page) == 0
    assert page.locator("#check").count() == 0
    assert page.locator(".rule-form").count() == 1  # the rule selected, to edit
    assert header.get_by_role("button", name="Download rules file").is_visible()
    pressed = page.locator(".modes button[aria-pressed=true]")
    assert pressed.inner_text() == "Edit"
    page.locator(".modes").get_by_role("button", name="Check").focus()
    page.keyboard.press("Enter")  # the switch works from the keyboard
    assert mode(page) == "check" and area_on_globe(page) == 2  # fill and outline
    page.locator(".modes").get_by_role("button", name="Edit").click()

    # the main page opens in the viewer's last mode, a site page in Check;
    # the address can ask for either
    others = []
    for url, rules, expected in [
        (f"{app}/", 0, "edit"),
        (f"{app}/sites/demo/", 5, "check"),
        (f"{app}/?src={app}/sites/demo/rules.geojson#check", 5, "check"),
        (f"{app}/sites/demo/#edit", 5, "edit"),
    ]:
        other, more = visit(context, url, rules, fresh=False)
        assert mode(other) == expected, url
        others += more
        other.close()
    assert not errors and not others


def area_on_globe(page):
    script = f"""(async () =>
        (await {APP}.map().getSource("area").getData()).features.length)()"""
    return page.evaluate(script)


@pytest.mark.skipif(
    not os.environ.get("CROCODASH_RULES"), reason="CROCODASH_RULES is not set"
)
def test_crocodash_rules(app, context, serve):
    """CrocoDash's rules, one file that queryearth's to_file wrote."""
    rules = Path(os.environ["CROCODASH_RULES"])
    count = len(json.loads(rules.read_text())["features"])
    page, errors = visit(
        context, f"{app}/?src={serve(rules.parent)}/{rules.name}#check", count
    )
    assert state(page)["problems"] == []
    assert row(page, "cat:CLAUDE").locator(".count").inner_text() == "10"
    page.fill("#rule-filter", "gulf")
    assert listed(page) == ["OBC001"]
    page.wait_for_timeout(700)
    settle(page)
    lon, lat = page.evaluate(f"{APP}.map().getCenter().toArray()")
    assert -85 < lon < -50 and 20 < lat < 50  # off North America
    page.fill("#rule-filter", "")

    # saved untouched, the file is as queryearth wrote it
    page.locator(".modes").get_by_role("button", name="Edit").click()
    file = page.locator("#file")
    with page.expect_download() as info:
        file.get_by_role("button", name="Download rules file").click()
    assert Path(info.value.path()).read_text() == rules.read_text()
    file.get_by_role("button", name="Copy rules file").click()
    page.wait_for_timeout(300)
    assert clipboard(page) == rules.read_text()

    # a rule of Claude's moves into a region
    open_rule(page, "CLAUDE003")
    page.select_option("#f-category", "ITF")
    page.wait_for_function(
        f"{APP}.page.state.rules.every(r => r.code !== 'CLAUDE003')", timeout=10000
    )
    moved = next(r for r in state(page)["rules"] if "CLAUDE003" in r["aliases"])
    assert moved["code"].startswith("ITF") and moved["path"] == ["REGION", "ITF"]
    assert f"CLAUDE003 is now {moved['code']}" in page.inner_text("#status")
    assert row(page, "cat:CLAUDE").locator(".count").inner_text() == "9"
    assert not errors


# a list of numbers spread over lines, which queryearth writes on one line
SPREAD = re.compile(r"\[\n\s*-?[0-9]")


def clipboard(page):
    return page.evaluate("navigator.clipboard.readText()")


NO_CLIPBOARD = """Object.defineProperty(navigator, "clipboard",
    {value: undefined, configurable: true})"""


def test_copy_a_rules_geojson(app, context):
    page, errors = visit(context, f"{app}/sites/demo/#edit", 5)
    new_rule(page)
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    block = page.locator("#f-geojson")
    assert block.get_attribute("open") is None  # closed at first
    block.locator("summary").click()
    page.wait_for_function("document.getElementById('f-geojson').open")

    def shown():
        return json.loads(page.locator("#f-geojson-text").inner_text())

    assert shown()["properties"]["code"] == "OCN004"
    page.fill("#f-title", "Copied rule")
    page.locator("#f-title").blur()
    page.wait_for_function(f"{APP}.page.state.rules[5].title === 'Copied rule'")
    assert shown()["properties"]["title"] == "Copied rule"  # still open, updated

    page.evaluate(f"{APP}.map().jumpTo({{center: [-90, 25], zoom: 3}})")
    settle(page)
    page.locator(".rule-form").get_by_role("button", name="Draw rectangle").click()
    click_at(page, -95, 20)
    click_at(page, -85, 28)
    page.wait_for_function(f"{APP}.page.state.rules[5].fill !== null")
    assert "box" in shown()["properties"]

    page.locator("#f-geojson").get_by_role("button", name="Copy", exact=True).click()
    page.wait_for_timeout(300)
    record = page.locator("#f-geojson-text").inner_text()  # as shown
    assert clipboard(page) == record
    assert json.loads(record) == json.loads(state(page)["rules"][5]["record"])
    assert not SPREAD.search(record) and '"box": {' in record
    assert "Copied OCN004 as GeoJSON" in page.inner_text("#status")

    # the whole file, as Download rules file saves it
    page.locator("#file").get_by_role("button", name="Copy rules file").click()
    page.wait_for_timeout(300)
    with page.expect_download() as info:
        page.locator("#file").get_by_role("button", name="Download rules file").click()
    saved = Path(info.value.path()).read_text()
    assert clipboard(page) == saved
    assert json.loads(saved)["features"][5] == json.loads(record)
    assert not SPREAD.search(saved) and saved.endswith("}\n")

    # where the browser will not copy, the text is selected for Ctrl+C
    page.evaluate(NO_CLIPBOARD)
    page.locator("#f-geojson").get_by_role("button", name="Copy", exact=True).click()
    page.wait_for_timeout(300)
    assert "press Ctrl+C" in page.inner_text("#status")
    assert page.evaluate("getSelection().toString()") == record

    # the block stays open for this viewer
    again, more = visit(context, f"{app}/sites/demo/#edit", 5, fresh=False)
    open_rule(again, "OCN001")
    assert again.locator("#f-geojson").get_attribute("open") is not None
    shown = again.locator("#f-geojson-text").inner_text()
    assert "[-98.0, 18.0]" in shown and not SPREAD.search(shown)  # as queryearth writes
    again.close()
    assert not errors and not more


def test_copy_from_a_rules_card(app, context):
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    open_rule(page, "OCN002")
    card = page.locator(".rule-card")
    card.get_by_role("button", name="Copy GeoJSON").click()
    page.wait_for_timeout(300)
    copied = clipboard(page)
    demo = json.loads((WEB / "sites" / "demo" / "rules.geojson").read_text())
    assert json.loads(copied) == demo["features"][1]
    assert json.loads(copied) == json.loads(state(page)["rules"][1]["record"])
    assert not SPREAD.search(copied)  # each list of numbers on one line
    assert page.locator(".rule-form").count() == 0  # still read only

    page.evaluate(NO_CLIPBOARD)
    card.get_by_role("button", name="Copy GeoJSON").click()
    box = card.locator("textarea.copy-fallback")
    assert box.input_value() == copied
    assert page.evaluate("document.activeElement.className") == "copy-fallback"
    assert "press Ctrl+C" in page.inner_text("#status")
    assert not errors


# ---- the tree --------------------------------------------------------------------
def test_the_tree(app, context):
    page, errors = visit(context, f"{app}/sites/demo/", 5)

    def count(id):
        return row(page, id).locator(".count").inner_text()

    def expanded(id):
        return node(page, id).get_attribute("aria-expanded")

    # at first All rules is open and every category closed, with its count
    assert listed(page) == []
    assert [expanded(n) for n in ("all", "cat:OCN", "cat:DOMAIN")] == [
        "true",
        "false",
        "false",
    ]
    assert [count(n) for n in ("all", "cat:OCN", "cat:DOMAIN")] == [
        "5",
        "3",
        "2",  # the rules in its subcategories
    ]

    # an opened branch stays open for this viewer
    row(page, "cat:DOMAIN").locator(".twisty").click()
    assert expanded("cat:DOMAIN") == "true" and count("cat:ICE") == "1"
    assert node(page, "cat:ICE").get_attribute("aria-level") == "3"
    page.reload()
    ready(page, 5)
    assert expanded("cat:DOMAIN") == "true" and expanded("cat:OCN") == "false"
    assert listed(page) == []  # ICE and OBC are still closed

    # picking a category opens it, shows its rules on the globe, and turns to them
    row(page, "cat:OBC").locator(".name").click()
    settle(page)
    assert on_globe(page) == [4] and listed(page) == ["OBC001"]
    row(page, "cat:DOMAIN").locator(".twisty").click()  # closed again

    # typing opens the categories of the rules that match, while there is text
    page.fill("#rule-filter", "strong current")
    assert listed(page) == ["OBC001"]
    assert expanded("cat:DOMAIN") == "true"
    assert count("cat:DOMAIN") == "1" and node(page, "cat:OCN").count() == 0
    page.wait_for_timeout(700)
    settle(page)  # the globe turns to them too
    assert 128 < page.evaluate(f"{APP}.map().getCenter().lng") < 150
    page.fill("#rule-filter", "")
    assert expanded("cat:DOMAIN") == "false"  # as the viewer left it

    # a rule chosen on the globe opens its categories
    page.evaluate(f"{APP}.map().jumpTo({{center: [-170, 60], zoom: 2.5}})")
    settle(page)
    row(page, "all").locator(".name").click()  # every rule on the globe
    settle(page)
    page.evaluate(f"{APP}.map().jumpTo({{center: [-170, 60], zoom: 2.5}})")
    settle(page)
    click_at(page, -175, 55)  # inside OCN002's box
    page.wait_for_function(f"{APP}.page.selected === 1")
    assert expanded("cat:OCN") == "true" and node(page, "rule:1").is_visible()

    # the keyboard
    row(page, "cat:OCN").locator(".twisty").click()  # closed again
    node(page, "all").focus()
    page.keyboard.press("ArrowDown")
    assert focused(page) == "cat:OCN"
    page.keyboard.press("ArrowRight")
    assert expanded("cat:OCN") == "true"
    page.keyboard.press("ArrowRight")
    assert focused(page) == "rule:0"
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")  # closes the rule opened from the globe
    page.keyboard.press("Enter")  # and opens it again
    assert page.evaluate(f"{APP}.page.selected") == 1 and focused(page) == "rule:1"
    assert "too warm in the Bering Sea" in node(page, "rule:1").inner_text()
    page.keyboard.press("ArrowLeft")
    assert focused(page) == "cat:OCN"
    page.keyboard.press("ArrowLeft")
    assert expanded("cat:OCN") == "false"
    page.keyboard.press("End")
    assert focused(page) == "cat:DOMAIN"
    page.keyboard.press("Home")
    assert focused(page) == "all"
    assert not errors


def test_managing_rules_in_the_tree(app, context, serve, tmp_path):
    page, errors = visit(context, f"{app}/sites/demo/#edit", 5)

    # move a rule with its select: a new code, and the old one kept
    open_rule(page, "OCN002")  # its form's Category moves it
    page.select_option("#f-category", "OBC")
    page.wait_for_function(f"{APP}.page.state.rules[1].code === 'OBC002'")
    assert "OCN002 is now OBC002; OCN002 kept as an alias" in page.inner_text("#status")

    # drag a rule onto a category
    handle = row(page, "rule:0").locator(".drag").bounding_box()
    onto = row(page, "cat:ICE").locator(".name").bounding_box()
    page.mouse.move(handle["x"] + 4, handle["y"] + 8)
    page.mouse.down()
    page.mouse.move(onto["x"] + 10, onto["y"] + 8, steps=12)
    page.mouse.up()
    page.wait_for_function(f"{APP}.page.state.rules[0].code === 'ICE002'")
    assert "OCN001 is now ICE002" in page.inner_text("#status")

    # move a category to the top level, and back by dragging; loops are refused
    row(page, "cat:OBC").get_by_role("button", name="More for OBC").click()
    page.select_option("#c-move-OBC", "^")  # in its ⋯ menu
    page.wait_for_function(f"{APP}.page.state.tree.join() === 'OCN,DOMAIN,ICE,OBC'")
    assert state(page)["categories"][3]["parent"] == ""
    row(page, "cat:DOMAIN").get_by_role("button", name="More for DOMAIN").click()
    page.select_option("#c-move-DOMAIN", "ICE")
    page.wait_for_timeout(300)
    assert "cannot sit in each other" in page.inner_text("#status")
    handle = row(page, "cat:OBC").locator(".drag").bounding_box()
    onto = row(page, "cat:DOMAIN").locator(".name").bounding_box()
    page.mouse.move(handle["x"] + 4, handle["y"] + 8)
    page.mouse.down()
    page.mouse.move(onto["x"] + 10, onto["y"] + 8, steps=12)
    page.mouse.up()
    page.wait_for_function(f"{APP}.page.state.categories[3].parent === 'DOMAIN'")

    # add a category at the top, rename it, and remove it; refusals say why
    row(page, "all").get_by_role("button", name="+ Category").click()
    page.fill("#new-prefix-top", "MISC")
    page.fill("#new-title-top", "Miscellany")
    page.get_by_role("button", name="Add category").click()
    page.wait_for_function(f"{APP}.page.state.categories.length === 5")
    row(page, "cat:MISC").get_by_role("button", name="More for MISC").click()
    page.fill("#c-title-MISC", "Other things")
    page.locator("#c-title-MISC").blur()
    page.wait_for_function(f"{APP}.page.state.categories[4].title === 'Other things'")
    assert row(page, "cat:MISC").locator(".name").inner_text() == "Other things"
    row(page, "cat:DOMAIN").get_by_role("button", name="More for DOMAIN").click()
    page.get_by_role("button", name="Remove DOMAIN").click()
    page.wait_for_timeout(300)
    assert "DOMAIN has subcategories" in page.inner_text("#status")
    row(page, "cat:MISC").get_by_role("button", name="More for MISC").click()
    page.get_by_role("button", name="Remove MISC").click()
    page.wait_for_function(f"{APP}.page.state.categories.length === 4")

    with page.expect_download() as info:
        page.locator("#file").get_by_role("button", name="Download rules file").click()
    saved = json.loads(Path(info.value.path()).read_text())
    props = {f["properties"]["code"]: f["properties"] for f in saved["features"]}
    assert props["OBC002"]["aliases"] == ["OCN002"]
    assert props["ICE002"]["aliases"] == ["OCN001"]
    assert saved["categories"]["OBC"] == {
        "title": "Open boundaries",
        "parent": "DOMAIN",
    }

    # a file from queryearth 0.5, with "groups", opens and is saved for 0.6
    old = json.loads((WEB / "sites" / "demo" / "rules.geojson").read_text())
    old["queryearth"] = "0.5"
    old["groups"] = old.pop("categories")
    (tmp_path / "old.geojson").write_text(json.dumps(old))
    page.get_by_role("button", name="Open link").click()
    page.fill("#link-url", f"{serve(tmp_path)}/old.geojson")
    page.locator("#linkbar").get_by_role("button", name="Open", exact=True).click()
    page.wait_for_function(f"{APP}.page.state.name === 'old.geojson'")
    assert state(page)["problems"] == [] and len(state(page)["categories"]) == 4
    with page.expect_download() as info:
        page.locator("#file").get_by_role("button", name="Download rules file").click()
    saved = json.loads(Path(info.value.path()).read_text())
    assert saved["queryearth"] == "0.6" and "groups" not in saved
    assert saved["categories"] == old["groups"]
    assert not errors
