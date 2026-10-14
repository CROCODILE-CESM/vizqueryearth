"""The web page in headless Chromium, used as a person would use it.

Needs playwright and its Chromium (python -m playwright install chromium), and
network access: the page loads its libraries, Pyodide and queryearth from CDNs.
Without playwright these tests are skipped.

QUERYEARTH_WHEEL=path/to/queryearth-X-py3-none-any.whl tests a queryearth that
is not on PyPI yet: the tests then serve a copy of web/ that installs it.
"""

import functools
import http.server
import json
import os
import re
import shutil
import threading
from pathlib import Path

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
            viewport={"width": 1280, "height": 800}, accept_downloads=True
        )
        browser.close()


def visit(context, url, rules, fresh=True):
    """Open a page and wait until it shows its rules; returns it and its errors."""
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
    page.on(
        "console",
        lambda msg: msg.type == "error" and errors.append(f"console: {msg.text}"),
    )
    page.on("dialog", lambda d: (errors.append(f"dialog: {d.message}"), d.dismiss()))
    page.goto(url)
    if fresh:
        page.evaluate("localStorage.clear()")  # before the page looks for a draft
    ready(page, rules)
    return page, errors


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
    """The codes in the rules list, in its order."""
    return page.locator("#rule-list .rule-row .code").all_inner_texts()


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
    assert page.input_value("#f-code") == "OCN002"
    assert not errors


def test_edit_rules_and_download_them(app, context, serve, tmp_path):
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    page.get_by_role(
        "button", name="New rule", exact=True
    ).click()  # in the first group
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
    page.locator(".rule-row", has_text="OCN001").click()
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
    assert "Bering test page" in html and '"OCN004"' in html and '"groups"' in html
    elsewhere, more_errors = visit(context, f"{serve(site)}/", 6)
    assert elsewhere.title() == "Bering test page"
    elsewhere.close()

    # deleting asks first
    page.locator(".rule-row", has_text="OCN004").click()
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
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    page.get_by_role("button", name="New rule", exact=True).click()
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    page.wait_for_timeout(500)
    page.reload()
    ready(page, 5)
    page.get_by_role("button", name="Restore them").click()
    ready(page, 6)
    assert not errors


def test_sort_and_filter_the_rules(app, context):
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    assert listed(page) == ["OCN001", "OCN002", "OCN003", "ICE001", "OBC001"]
    page.fill("#rule-filter", "ICE")  # a code or a title, in any case
    assert listed(page) == ["ICE001"] and on_globe(page) == [2]
    page.fill("#rule-filter", "bering")
    assert listed(page) == ["OCN002"] and on_globe(page) == [1]
    page.fill("#rule-filter", "")

    groups = page.locator("#rules .group-buttons")
    groups.get_by_role("button", name="Open boundaries (OBC)").click()
    settle(page)  # the globe turns to the group's rules
    assert listed(page) == ["OBC001"] and on_globe(page) == [4]
    assert 128 < page.evaluate(f"{APP}.map().getCenter().lng") < 150
    edge = page.locator(".rule-row", has_text="OBC001").locator(".tag")
    assert edge.inner_text() == "edge"

    page.reload()  # each viewer's filter is kept
    ready(page, 5)
    assert listed(page) == ["OBC001"]
    groups = page.locator("#rules .group-buttons")
    pressed = groups.get_by_role("button", name="Open boundaries (OBC)")
    assert pressed.get_attribute("aria-pressed") == "true"
    groups.get_by_role("button", name="All", exact=True).click()
    assert len(listed(page)) == 5
    assert on_globe(page) == [0, 1, 2, 4]  # OCN003 has no shape
    assert not errors


def test_groups_new_codes_and_edge_rules(app, context):
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    groups = page.locator("#groups")
    page.fill("#g-prefix", "grid")  # taken in capitals
    page.fill("#g-title", "Grids")
    groups.get_by_role("button", name="Add", exact=True).click()
    page.wait_for_function(f"{APP}.page.state.groups.length === 4")

    # a new rule takes the next code in the group picked
    page.select_option("#new-group", "OBC")
    page.get_by_role("button", name="New rule", exact=True).click()
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    assert page.input_value("#f-code") == "OBC002"
    page.select_option("#new-group", "GRID")
    page.get_by_role("button", name="New rule", exact=True).click()
    page.wait_for_function(f"{APP}.page.state.rules.length === 7")
    assert page.input_value("#f-code") == "GRID001"

    # a group with rules cannot be removed; without them it can
    assert groups.get_by_role("button", name="Remove GRID").is_disabled()
    page.get_by_role("button", name="Delete GRID001").click()
    page.get_by_role("button", name="Click again to delete GRID001").click()
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    groups.get_by_role("button", name="Remove GRID").click()
    page.wait_for_function(f"{APP}.page.state.groups.length === 3")

    # the edge box goes to the file; a rule without a shape cannot have it
    page.locator(".rule-row", has_text="OCN002").click()
    settle(page)
    page.check("#f-edge")
    page.wait_for_function(f"{APP}.page.state.rules[1].edge === true")
    page.locator(".rule-row", has_text="OCN003").click()
    settle(page)
    page.click("#f-edge")
    page.wait_for_timeout(500)
    assert "needs a space" in page.inner_text("#status")
    assert not page.is_checked("#f-edge")
    with page.expect_download() as info:
        page.locator("#file").get_by_role("button", name="Download rules file").click()
    saved = json.loads(Path(info.value.path()).read_text())
    assert saved["queryearth"] == "0.4"
    assert list(saved["groups"]) == ["OCN", "ICE", "OBC"]
    props = {f["properties"]["code"]: f["properties"] for f in saved["features"]}
    assert props["OCN002"]["edge"] is True and props["OBC001"]["edge"] is True
    assert "edge" not in props["OCN003"] and "OBC002" in props
    assert not errors


def test_a_file_for_a_later_queryearth_is_not_opened(app, context, serve, tmp_path):
    later = json.loads((WEB / "sites" / "demo" / "rules.geojson").read_text())
    (tmp_path / "later.geojson").write_text(json.dumps(later | {"queryearth": "0.5"}))
    page, errors = visit(context, f"{app}/sites/demo/", 5)
    page.get_by_role("button", name="Open link").click()
    page.fill("#link-url", f"{serve(tmp_path)}/later.geojson")
    page.locator("#linkbar").get_by_role("button", name="Open", exact=True).click()
    page.wait_for_function(
        "document.getElementById('status').textContent.includes('0.5')"
    )
    assert "this file needs queryearth 0.5 or later" in page.inner_text("#status")
    assert len(state(page)["rules"]) == 5 and "src=" not in page.url
    assert not errors
