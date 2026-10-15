"""The web page in headless Chromium, used as a person would use it.

Needs playwright and its Chromium (python -m playwright install chromium), and
network access: the page loads its libraries, Pyodide and queryearth from CDNs.
Without playwright these tests are skipped.

QUERYEARTH_WHEEL=path/to/queryearth-X-py3-none-any.whl tests a queryearth that
is not on PyPI: the tests then serve a copy of web/ that installs it.
CROCODASH_RULES=path/to/rules.geojson adds a test on one of CrocoDash's files.
"""

import atexit
import functools
import http.server
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

WEB = Path(__file__).resolve().parents[2] / "web"
DEMO = json.loads((WEB / "sites" / "demo" / "rules.geojson").read_text())
APP = "window.__vizqueryearth"


class Files(http.server.SimpleHTTPRequestHandler):
    """A static web host that, like GitHub Pages, lets other sites read its files."""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args):
        pass


def serve(folder):
    """Serve a folder on a port of its own, so each folder is its own site."""
    handler = functools.partial(Files, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


@functools.cache
def app():
    """Where the page is served; with QUERYEARTH_WHEEL, a copy that installs it."""
    wheel = os.environ.get("QUERYEARTH_WHEEL")
    if not wheel:
        return serve(WEB)
    web = Path(tempfile.mkdtemp()) / "web"
    shutil.copytree(WEB, web)  # with web/py's link followed
    shutil.copy(wheel, web)
    url = serve(web)
    script = web / "app.js"
    wanted = f'const QUERYEARTH = "{url}/{Path(wheel).name}"'
    script.write_text(re.sub(r'const QUERYEARTH = "[^"]*"', wanted, script.read_text()))
    return url


@functools.cache
def browser():
    """One browser for every test, so Python and queryearth download once."""
    playwright = sync_api.sync_playwright().start()
    atexit.register(playwright.stop)
    webgl = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
    return playwright.chromium.launch(
        args=[*webgl, "--ignore-gpu-blocklist"]
    ).new_context(
        viewport={"width": 1280, "height": 800},
        accept_downloads=True,
        permissions=["clipboard-read", "clipboard-write"],
    )


def visit(path, rules):
    """Open a page with no drafts, filters or modes kept from earlier tests, and
    wait until it shows its rules; returns it and the errors it logs."""
    for earlier in browser().pages:
        earlier.close()
    page = browser().new_page()
    page.goto(f"{app()}/app.css")
    page.evaluate("localStorage.clear()")
    errors = []
    page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(path if path.startswith("http") else app() + path)
    page.wait_for_function(
        f"{APP} && {APP}.page.state && {APP}.page.state.rules.length === {rules}",
        timeout=300_000,  # the first visit downloads Python and queryearth
    )
    return page, errors


def state(page):
    return page.evaluate(f"{APP}.page.state")


def codes(page):
    return [rule["code"] for rule in state(page)["rules"]]


def row(page, node):
    """A row of the tree: "all", "cat:DOMAIN/OBC" or "rule:5"."""
    return page.locator(f'#rule-tree [data-node="{node}"] > .tree-row')


def open_rule(page, code):
    """Open the categories a rule is in, and click it."""
    path = code.split("/")[:-1]
    for i in range(1, len(path) + 1):
        node = page.locator(f'[data-node="cat:{"/".join(path[:i])}"]')
        if node.get_attribute("aria-expanded") == "false":
            node.locator(":scope > .tree-row .twisty").click()
    row(page, f"rule:{codes(page).index(code)}").locator(".code").click()


def drag(page, handle, onto):
    """Drag a row by its handle onto another row."""
    start, end = handle.bounding_box(), onto.bounding_box()
    page.mouse.move(start["x"] + 4, start["y"] + 8)
    page.mouse.down()
    page.mouse.move(end["x"] + 10, end["y"] + 8, steps=12)
    page.mouse.up()


def click_at(page, lon, lat):
    x, y = page.evaluate(f"""(() => {{
        const map = {APP}.map(), p = map.project([{lon}, {lat}]);
        const box = map.getContainer().getBoundingClientRect();
        return [box.left + p.x, box.top + p.y];
    }})()""")
    page.mouse.click(x, y)
    page.wait_for_timeout(250)


def downloaded(page, button):
    with page.expect_download() as info:
        page.locator("#file").get_by_role("button", name=button).click()
    return Path(info.value.path()).read_text()


def test_check_a_drawn_domain():
    page, errors = visit("/sites/demo/", 5)
    tree = page.locator("#rule-tree")
    assert tree.locator(".rule-row").count() == 0  # the categories start closed
    assert row(page, "cat:OCN").locator(".count").inner_text() == "3"

    page.locator("#check").get_by_role("button", name="Draw rectangle").click()
    click_at(page, 172, 56)  # across the date line, in the Bering Sea
    click_at(page, -168, 63)
    page.wait_for_function(f"{APP}.page.areaShape !== null")
    page.fill("#q-start", "2001-01-01")
    page.fill("#q-end", "2001-03-31")
    page.fill("[data-dim=product]", "demo_ocean")
    page.fill("[data-dim=variable]", "thetao")
    page.locator("#check").get_by_role("button", name="Check", exact=True).click()
    page.wait_for_function(f"{APP}.page.results !== null")
    assert page.evaluate(f"{APP}.page.results") == [codes(page).index("OCN/OCN002")]

    card = page.locator("#check .card")
    card.get_by_role("button", name="Copy GeoJSON").click()
    page.wait_for_timeout(300)
    assert (
        json.loads(page.evaluate("navigator.clipboard.readText()"))
        == DEMO["features"][1]
    )
    card.locator("p").first.click()  # opens the rule in the tree, read only
    text = page.locator(".rule-card").inner_text()
    assert "What to do: Compare demo_ocean" in text and "Made up for this demo" in text
    assert page.locator(".rule-form").count() == 0
    assert errors == []


def test_edit_a_rule_and_download_the_file():
    page, errors = visit("/sites/demo/#edit", 5)
    row(page, "cat:DOMAIN").locator(".twisty").click()
    row(page, "cat:DOMAIN/ICE").get_by_role(
        "button", name="New rule in DOMAIN/ICE"
    ).click()
    page.wait_for_function(f"{APP}.page.state.rules.length === 6")
    assert page.input_value("#f-code") == "DOMAIN/ICE/ICE002"

    page.fill("#f-title", "Thin ice")
    page.locator("#f-title").blur()
    page.select_option("#f-level", "error")
    page.fill("[data-rule-dim=model]", "demo_model")
    page.locator("[data-rule-dim=model]").blur()
    page.fill("#f-start", "2001-01-01")
    page.locator("#f-start").blur()
    page.wait_for_function(f"{APP}.page.state.rules[5].time.start === '2001-01-01'")
    page.evaluate(f"{APP}.map().jumpTo({{center: [-40, 70], zoom: 2.5}})")
    page.wait_for_timeout(600)
    page.locator(".rule-form").get_by_role("button", name="Draw rectangle").click()
    click_at(page, -50, 65)
    click_at(page, -30, 75)
    page.wait_for_function(f"{APP}.page.state.rules[5].fill !== null")

    saved = json.loads(downloaded(page, "Download rules file"))
    rule = saved["features"][5]
    assert saved["queryearth"] == "0.7"
    assert rule["properties"]["title"] == "Thin ice"
    assert rule["properties"]["level"] == "error"
    assert rule["properties"]["dimensions"] == {"model": ["demo_model"]}
    assert rule["time"] == {"interval": ["2001-01-01", ".."]}
    assert rule["geometry"]["type"] == "Polygon"
    assert saved["features"][:5] == DEMO["features"]  # the others as they were
    assert errors == []


def test_move_rules_and_categories_in_the_tree():
    page, errors = visit("/sites/demo/#edit", 5)
    row(page, "cat:DOMAIN").locator(".twisty").click()
    row(page, "cat:OCN").locator(".twisty").click()
    drag(page, row(page, "rule:0").locator(".drag"), row(page, "cat:DOMAIN/OBC"))
    page.wait_for_function(f"{APP}.page.state.rules[0].code === 'DOMAIN/OBC/OCN001'")
    assert "OCN/OCN001 is now DOMAIN/OBC/OCN001" in page.inner_text("#status")

    open_rule(page, "OCN/OCN002")
    page.select_option("#f-category", "")  # none, the top level
    page.wait_for_function(f"{APP}.page.state.rules[1].code === 'OCN002'")

    row(page, "cat:DOMAIN").get_by_role("button", name="More for DOMAIN").click()
    page.fill('[id="c-name-DOMAIN"]', "SETUP")
    page.locator('[id="c-name-DOMAIN"]').blur()
    page.wait_for_function(f"{APP}.page.state.rules[2].code === 'SETUP/ICE/ICE001'")
    assert codes(page) == [
        "SETUP/OBC/OCN001",
        "OCN002",
        "SETUP/ICE/ICE001",
        "OCN/OCN003",
        "SETUP/OBC/OBC001",
    ]

    # a category without rules is kept in the page; one with rules stays
    row(page, "cat:OCN").get_by_role("button", name="More for OCN").click()
    page.fill('[id="new-category-OCN"]', "SALT")
    page.get_by_role("button", name="Add subcategory").click()
    assert row(page, "cat:OCN/SALT").locator(".count").inner_text() == "0"
    row(page, "cat:OCN").get_by_role("button", name="More for OCN").click()
    page.get_by_role("button", name="Remove OCN").click()
    assert "OCN still has rules" in page.inner_text("#status")

    saved = json.loads(downloaded(page, "Download rules file"))
    assert [f["properties"]["code"] for f in saved["features"]] == codes(page)
    assert errors == []


def test_download_as_a_web_page(tmp_path):
    page, errors = visit("/sites/demo/#edit", 5)
    page.fill("#d-name", "resolution")
    page.select_option("#d-kind", "axis")
    page.fill("#d-unit", "km")
    page.locator("#dimensions").get_by_role("button", name="Add", exact=True).click()
    page.wait_for_function(f"{APP}.page.state.dimensions.length === 4")
    page.fill("#page-title", "Demo copy")
    (tmp_path / "index.html").write_text(downloaded(page, "Download as web page"))
    copy, more = visit(f"{serve(tmp_path)}/", 5)
    assert copy.title() == "Demo copy"
    assert [d["name"] for d in state(copy)["dimensions"]][-1] == "resolution"
    assert errors == [] and more == []


def test_open_a_queryearth_0_6_file_by_link(tmp_path):
    old = {
        "type": "FeatureCollection",
        "queryearth": "0.6",
        "categories": {"OCN": "Ocean", "BAD": "Edge rules"},
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"code": "OCN001", "title": "Old", "message": "From 0.6."}},  # fmt: skip
        ],
    }
    (tmp_path / "old.geojson").write_text(json.dumps(old))
    page, errors = visit(f"{app()}/?src={serve(tmp_path)}/old.geojson", 1)
    assert codes(page) == ["OCN/OCN001"]

    edge = {"code": "BAD001", "title": "Edge", "message": "Where a domain's edge crosses.", "edge": True}  # fmt: skip
    old["features"].append({"type": "Feature", "geometry": None, "properties": edge})
    (tmp_path / "edge.geojson").write_text(json.dumps(old))
    page.get_by_role("button", name="Open link").click()
    page.fill("#link-url", f"{serve(tmp_path)}/edge.geojson")
    page.locator("#linkbar").get_by_role("button", name="Open", exact=True).click()
    page.wait_for_function(
        "document.getElementById('status').textContent.includes('Could not')"
    )
    assert (
        "Could not open edge.geojson: feature 1: BAD/BAD001: ['edge']"
        in page.inner_text("#status")
    )
    assert codes(page) == ["OCN/OCN001"]  # the open file stays
    assert errors == []


@pytest.mark.skipif(not os.environ.get("CROCODASH_RULES"), reason="no CROCODASH_RULES")
def test_crocodash_rules():
    rules = Path(os.environ["CROCODASH_RULES"])
    count = len(json.loads(rules.read_text())["features"])
    page, errors = visit(f"{app()}/?src={serve(rules.parent)}/{rules.name}#edit", count)
    assert downloaded(page, "Download rules file") == rules.read_text()
    first = codes(page)[0]
    page.locator("#rule-tree .tree-row .name").nth(1).click()  # a category
    page.wait_for_timeout(300)
    open_rule(page, first)
    page.select_option("#f-category", "")
    page.wait_for_function(
        f"{APP}.page.state.rules[0].code === '{first.split('/')[-1]}'"
    )
    assert errors == []
