// vizqueryearth: check and edit queryearth rules on a globe, in the browser.
//
// The page has two modes: Check, for people who read the rules (which apply to
// my area?), and Edit, for people who write them.
//
// The page reads its settings, shows a globe (MapLibre) with drawing tools
// (Terra Draw), and starts Python (Pyodide) with queryearth and vizqueryearth's
// own Python, which does everything that touches rules: Session.call() in
// vizqueryearth/session.py. Nothing leaves the browser: files are opened from
// disk or a link, and saved by downloading them.

const APP = new URL(".", import.meta.url); // where app.js, app.css and py/ are
const LIBS = {
  maplibre: "https://cdn.jsdelivr.net/npm/maplibre-gl@6.11.2/dist/maplibre-gl.mjs",
  maplibreCss: "https://cdn.jsdelivr.net/npm/maplibre-gl@6.11.2/dist/maplibre-gl.css",
  terraDraw: "https://cdn.jsdelivr.net/npm/terra-draw@1.35.0/dist/terra-draw.umd.js",
  terraDrawAdapter:
    "https://cdn.jsdelivr.net/npm/terra-draw-maplibre-gl-adapter@1.4.1/dist/terra-draw-maplibre-gl-adapter.umd.js",
  // Natural Earth's own GeoJSON, cut at ±180 so that a flat renderer draws it as is
  land: "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/ne_50m_land.geojson",
  pyodide: "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.js",
};
const QUERYEARTH = "queryearth==0.4.0"; // a requirement or a wheel URL, for micropip
const PY_FILES = ["__init__.py", "shapes.py", "rulefile.py", "session.py"];
const LEVEL_COLOR = { error: "#c62828", warning: "#e08a00", info: "#1e6fd9" };
const LEVELS = [
  ["", "default"],
  ["info", "info"],
  ["warning", "warning"],
  ["error", "error"],
];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const KINDS = ["labels", "axis", "versions"];
const HINTS = {
  labels: "names, separated by commas; * and ? match any letters",
  axis: "<8, <=8, >2, >=2, or 2-8 (from 2 up to, not including, 8)",
  versions: 'versions, such as 4.07, ERA5T, or {"introduced": "4.00", "fixed": "4.09"}',
};
const DEFAULT_VIEW = { center: [-30, 30], zoom: 1.3 };
// A page shown inside another (such as an editor's preview) may not be allowed to download.
const EMBEDDED = (() => {
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
})();

// ---- small helpers --------------------------------------------------------------
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("aria-") && typeof value === "boolean") {
      node.setAttribute(key, String(value)); // aria states are "true" or "false"
      continue;
    }
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined && child !== false) {
      node.append(child instanceof Node ? child : String(child));
    }
  }
  return node;
}

function field(id, label, input) {
  return el("div", { class: "field" }, el("label", { for: id }, label), input);
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = el("script", { src });
    script.onload = resolve;
    script.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.append(script);
  });
}

function say(text, error = false) {
  const status = document.getElementById("status");
  status.textContent = text;
  status.className = error ? "error" : "";
}

function download(name, text, type) {
  // Some embedded browsers block downloads without telling the page: say so.
  const blocked = "Open this page in a normal web browser, such as Firefox or Chrome, to save files.";
  try {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = el("a", { href: url, download: name });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    say(`Could not download ${name}: ${err.message}. ${blocked}`, true);
    return false;
  }
  return EMBEDDED ? ` If no file appeared, this browser blocks downloads. ${blocked}` : "";
}

function collection(features) {
  return { type: "FeatureCollection", features };
}

// Browser storage can be missing or blocked, so every use is allowed to fail.
function browserStore(name, place) {
  return {
    key: () => `vizqueryearth:${name}:${place()}`,
    get() {
      try {
        return JSON.parse(localStorage.getItem(this.key()));
      } catch {
        return null;
      }
    },
    set(value) {
      try {
        localStorage.setItem(this.key(), JSON.stringify(value));
      } catch {}
    },
    clear() {
      try {
        localStorage.removeItem(this.key());
      } catch {}
    },
  };
}
// unsaved edits, in case the tab is closed, for this page and these rules
const store = browserStore("draft", () => location.pathname + location.search);
// each viewer's filter of the rules list, for this page
const filterStore = browserStore("filter", () => location.pathname);
// the mode each viewer used last, Check or Edit
const modeStore = browserStore("mode", () => "last");
const MODES = ["check", "edit"];

// ---- settings: inline, from a site's site.json, then ?src= ----------------------
async function readSettings() {
  let site = {};
  const inline = document.getElementById("vizqueryearth-site");
  if (inline) {
    site = JSON.parse(inline.textContent);
  } else if (document.body.dataset.site) {
    const response = await fetch(document.body.dataset.site, { cache: "no-cache" });
    if (response.ok) site = await response.json();
  }
  const params = new URLSearchParams(location.search);
  let source = null;
  if (params.get("src")) source = { url: params.get("src") };
  else if (typeof site.rules === "string") source = { url: new URL(site.rules, location.href).href };
  else if (site.rules) source = { text: JSON.stringify(site.rules), name: "rules.geojson" };
  return {
    site: Boolean(inline || document.body.dataset.site), // a page made for a set of rules
    title: site.title || "vizqueryearth",
    description: site.description || "",
    dimensions: site.dimensions || null, // for rules files that do not declare them
    view: site.view || null, // without one, the globe turns to the rules
    source,
  };
}

// ---- Python ---------------------------------------------------------------------
let session = null;
async function startPython() {
  await loadScript(LIBS.pyodide);
  const py = await globalThis.loadPyodide();
  await py.loadPackage(["numpy", "shapely", "micropip"]);
  await py.pyimport("micropip").install(QUERYEARTH);
  py.FS.mkdirTree("/home/pyodide/vizqueryearth");
  for (const name of PY_FILES) {
    const response = await fetch(new URL(`py/vizqueryearth/${name}`, APP), { cache: "no-cache" });
    if (!response.ok) throw new Error(`could not load vizqueryearth/${name}`);
    py.FS.writeFile(`/home/pyodide/vizqueryearth/${name}`, await response.text());
  }
  session = py.runPython(
    "import sys; sys.path.insert(0, '/home/pyodide')\n" +
      "from vizqueryearth.session import Session\nSession()"
  );
}

async function call(name, args = {}) {
  await pythonReady;
  const out = JSON.parse(session.call(name, JSON.stringify(args)));
  if ("error" in out) throw new Error(out.error);
  return out.ok;
}

// ---- the page -------------------------------------------------------------------
const page = {
  mode: "check", // "check": read the rules, check an area; "edit": write them
  settings: null,
  state: null, // what Python says about the rules: Session.do_state()
  selected: null, // the rule being edited, by position
  area: [], // the area to check, as drawn
  areaShape: null, // and as queryearth reads it
  query: { start: "", end: "", values: {}, include_conditional: false },
  results: null,
  drawing: null, // what the drawing tools are for: "area", "rule" or "corners"
  drawingEnded: 0, // when the last drawing ended
  markers: [],
  draft: null, // edits kept in this browser from an earlier visit
  pageTitle: "",
  filter: { text: "", group: "" }, // which rules the list and the globe show
};
let map, draw, maplibregl, pythonReady;

function build() {
  const s = page.settings;
  document.title = s.title;
  page.pageTitle = s.title === "vizqueryearth" ? "My rules" : s.title;
  const fileInput = el("input", { type: "file", accept: ".geojson,.json", hidden: true, onchange: openFile });
  document.body.append(
    el(
      "header",
      { class: "bar" },
      el("h1", {}, s.title),
      el(
        "div",
        { class: "modes", role: "group", "aria-label": "Mode" },
        el("button", { type: "button", "data-mode": "check", title: "Read the rules, and check which apply to your area", onclick: () => setMode("check") }, "Check"),
        el("button", { type: "button", "data-mode": "edit", title: "Write the rules: their fields, shapes, groups and dimensions", onclick: () => setMode("edit") }, "Edit")
      ),
      el("span", { class: "grow" }),
      el("button", { onclick: () => fileInput.click() }, "Open file"),
      el("button", { id: "open-link", "aria-expanded": false, "aria-controls": "linkbar", onclick: () => showLinkBar(document.getElementById("linkbar").hidden) }, "Open link"),
      el("button", { class: "edit-only", onclick: downloadRules }, "Download rules file"),
      el("button", { class: "edit-only", onclick: downloadPage }, "Download as web page"),
      fileInput
    ),
    el(
      "form",
      { id: "linkbar", class: "bar linkbar", hidden: true, onsubmit: submitLink },
      el("label", { for: "link-url" }, "Link to a rules file"),
      el("input", { id: "link-url", type: "text", inputmode: "url", autocomplete: "off", spellcheck: "false", placeholder: "https://…/rules.geojson", required: true }),
      el("button", { class: "primary", type: "submit" }, "Open"),
      el("button", { type: "button", onclick: () => showLinkBar(false) }, "Cancel"),
      el("span", { class: "hint" }, "The file's host must let other sites read it, as GitHub and gists do.")
    ),
    el("main", {}, el("div", { id: "map" }), el("aside", { id: "panel" })),
    el("div", { id: "status", role: "status" })
  );
}

function render() {
  const parts =
    page.mode === "edit"
      ? [page.draft ? draftNotice() : null, rulesSection(), groupsSection(), dimensionsSection(), fileSection()]
      : [page.draft ? draftPointer() : null, checkSection(), rulesSection()];
  document.getElementById("panel").replaceChildren(...parts.filter(Boolean));
  drawRules();
  drawArea();
}

// ---- modes: Check to read the rules, Edit to write them -------------------------
function setMode(mode) {
  if (!MODES.includes(mode)) return;
  stopDrawing(); // a drawing belongs to the mode it was started in
  page.mode = mode;
  document.body.dataset.mode = mode;
  for (const button of document.querySelectorAll(".modes button")) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  modeStore.set(mode);
  if (location.hash !== `#${mode}`) history.replaceState(null, "", `${location.pathname}${location.search}#${mode}`);
  render();
}

// #edit or #check in the address, else the viewer's last mode, else Check. A
// page made for a set of rules opens in Check unless its address says #edit.
function chosenMode() {
  const asked = location.hash.slice(1);
  if (MODES.includes(asked)) return { mode: asked, asked: true };
  const last = page.settings.site ? null : modeStore.get();
  return { mode: MODES.includes(last) ? last : "check", asked: false };
}

// ---- check your area: which rules apply to my area, time and values? ------------
function checkSection() {
  const s = page.settings;
  const state = page.state;
  const q = page.query;
  return el(
    "section",
    { id: "check" },
    s.description ? el("p", { class: "hint" }, s.description) : null,
    state && !state.rules.length && !s.source
      ? el(
          "div",
          { class: "notice" },
          el("p", {}, "No rules loaded yet. Open a rules file or a link to one, or switch to Edit to start a set."),
          el("p", {}, el("a", { href: new URL("sites/demo/", APP).href }, "Try the demo"))
        )
      : null,
    el("h2", {}, "Check your area"),
    el("p", { class: "hint" }, "Draw where you work, or leave it empty to ask about anywhere."),
    el(
      "div",
      { class: "row" },
      el("button", { onclick: () => startDrawing("rectangle", "area") }, "Draw rectangle"),
      el("button", { onclick: () => startDrawing("polygon", "area") }, "Draw polygon"),
      el("button", { onclick: clearArea, disabled: !page.area.length }, "Clear")
    ),
    page.areaShape ? el("p", { class: "hint" }, `Area: ${page.areaShape.km2.toLocaleString()} km²`) : null,
    el(
      "div",
      { class: "two" },
      field("q-start", "From", el("input", { id: "q-start", type: "date", value: q.start, oninput: (e) => (q.start = e.target.value) })),
      field("q-end", "To", el("input", { id: "q-end", type: "date", value: q.end, oninput: (e) => (q.end = e.target.value) }))
    ),
    (state?.dimensions || []).map((dim) => {
      const id = `q-${dim.name}`;
      const values = state.values[dim.name] || [];
      const hint = dim.kind === "axis" ? "a number or a range, such as 8 or 5-10" : "one or more, separated by commas";
      return field(
        id,
        [dim.name, unit(dim)],
        [
          el("input", { id, "data-dim": dim.name, placeholder: hint, list: values.length ? `${id}-list` : null, value: q.values[dim.name] || "", oninput: (e) => (q.values[dim.name] = e.target.value) }),
          values.length ? el("datalist", { id: `${id}-list` }, values.map((v) => el("option", { value: v }))) : null,
        ]
      );
    }),
    el(
      "div",
      { class: "row" },
      el("input", { id: "q-conditional", type: "checkbox", style: "width:auto", checked: q.include_conditional, onchange: (e) => (q.include_conditional = e.target.checked) }),
      el("label", { for: "q-conditional" }, "Also list rules that need more information")
    ),
    el("div", { class: "row" }, el("button", { class: "primary", onclick: runQuery, disabled: !state?.rules.length }, "Check")),
    page.results ? resultsView(page.results) : null
  );
}

function unit(dim) {
  return dim.kind === "axis" && dim.unit && dim.unit !== "unknown" ? el("span", { class: "unit" }, ` (${dim.unit})`) : null;
}

async function runQuery() {
  const q = page.query;
  const declared = new Set(page.state.dimensions.map((d) => d.name));
  const values = Object.fromEntries(Object.entries(q.values).filter(([name]) => declared.has(name)));
  try {
    page.results = await call("query", { area: page.area, start: q.start, end: q.end, values, include_conditional: q.include_conditional });
    const n = page.results.findings.length;
    say(n === 0 ? "No rule applies. That means only that no rule matched, not that all is well." : n === 1 ? "1 rule applies." : `${n} rules apply.`);
  } catch (err) {
    page.results = null;
    say(err.message, true);
  }
  render();
}

function resultsView(results) {
  const n = results.findings.length;
  return [
    el("h3", {}, n === 0 ? "No rule applies" : n === 1 ? "1 rule applies" : `${n} rules apply`),
    results.findings.map((f) =>
      el(
        "div",
        { class: "card", role: "button", tabindex: "0", title: `Select ${f.code}`, onclick: () => focusRule(f.code), onkeydown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), focusRule(f.code)) },
        el("div", { class: "head" }, el("span", { class: `chip ${f.level}` }, f.level), el("strong", {}, f.code), el("span", {}, f.title), isEdge(f.code) ? edgeTag() : null),
        el("p", {}, f.message),
        f.area_fraction !== null && f.area_fraction !== undefined ? el("p", { class: "needs" }, `Covers ${Math.round(f.area_fraction * 100)}% of your area`) : null,
        f.conditional_on.length ? el("p", { class: "needs" }, `Applies only if it matches your ${f.conditional_on.join(", ")}: give them to know.`) : null,
        f.changes.map((c) => el("p", { class: "change" }, `Change: ${c.target} ${c.key} = ${JSON.stringify(c.value)}${c.rationale ? ` (${c.rationale})` : ""}`))
      )
    ),
    results.report
      ? el("div", { class: "row" }, el("button", { onclick: () => navigator.clipboard?.writeText(results.report).then(() => say("Copied the findings as text.")) }, "Copy as text"))
      : null,
  ];
}

function clearArea() {
  page.area = [];
  page.areaShape = null;
  page.results = null;
  drawArea();
  render();
}

// ---- rules: filter them, pick one to see and edit it ----------------------------
function matches(rule) {
  const { text, group } = page.filter;
  const words = text.trim().toLowerCase();
  if (group && rule.group !== group) return false;
  return !words || rule.code.toLowerCase().includes(words) || rule.title.toLowerCase().includes(words);
}

// The rules the list and the globe show, sorted by code: those the filter
// leaves, and the selected one.
function shown() {
  const state = page.state;
  if (!state) return [];
  return state.order.map((i) => state.rules[i]).filter((r) => r.index === page.selected || matches(r));
}

function isEdge(code) {
  return Boolean(page.state?.rules.find((r) => r.code === code)?.edge);
}

function edgeTag() {
  return el("span", { class: "tag", title: "Applies where a domain's edge crosses its area" }, "edge");
}

function setFilter(change) {
  page.filter = { ...page.filter, ...change };
  filterStore.set(page.filter);
}

function filterGroup(prefix) {
  setFilter({ group: prefix });
  render();
  fitRules(); // turn to the rules the group has
}

let fitSoon = null;
function filterText(event) {
  setFilter({ text: event.target.value });
  document.getElementById("rule-list").replaceChildren(...ruleItems());
  document.getElementById("rule-count").textContent = countText();
  drawRules();
  clearTimeout(fitSoon); // once typing stops, turn to the rules it leaves
  fitSoon = setTimeout(() => fitRules({ quiet: true }), 500);
}

function countText() {
  const total = page.state?.rules.length || 0;
  const n = page.state ? page.state.rules.filter(matches).length : 0;
  if (!total) return page.mode === "edit" ? "No rules yet: click New rule, or open a rules file." : "No rules yet.";
  const showing = n === total ? `${total} rule${total === 1 ? "" : "s"}` : `${n} of ${total} rules`;
  return `${showing}. Click a rule, here or on the globe, to ${page.mode === "edit" ? "edit" : "read"} it.`;
}

function rulesSection() {
  const state = page.state;
  const filters = state?.filters || [];
  const groups = state?.groups || [];
  const preferred = groups.some((g) => g.prefix === page.filter.group) ? page.filter.group : groups[0]?.prefix;
  return el(
    "section",
    { id: "rules" },
    el("h2", {}, "Rules"),
    el(
      "div",
      { class: "filter" },
      el("input", { id: "rule-filter", type: "search", "aria-label": "Filter the rules by code or title", placeholder: "Filter by code or title", value: page.filter.text, oninput: filterText }),
      filters.length
        ? el(
            "div",
            { class: "row group-buttons", role: "group", "aria-label": "Show one group" },
            el("button", { type: "button", "aria-pressed": !page.filter.group, onclick: () => filterGroup("") }, "All"),
            filters.map((f) => el("button", { type: "button", "aria-pressed": page.filter.group === f.prefix, title: f.title || f.prefix, onclick: () => filterGroup(f.prefix) }, f.title ? `${f.title} (${f.prefix})` : f.prefix))
          )
        : null
    ),
    el("p", { id: "rule-count", class: "hint" }, countText()),
    el("ul", { id: "rule-list", class: "rules" }, ruleItems()),
    page.mode === "edit"
      ? el(
          "div",
          { class: "row" },
          groups.length
            ? el("select", { id: "new-group", "aria-label": "Group of the new rule" }, groups.map((g) => el("option", { value: g.prefix, selected: g.prefix === preferred }, `${g.prefix}: ${g.title}`)))
            : null,
          el("button", { onclick: newRule }, "New rule")
        )
      : null
  );
}

function ruleItems() {
  return shown().map((r) => {
    const selected = r.index === page.selected;
    return el(
      "li",
      { "aria-current": selected },
      el(
        "button",
        { type: "button", class: "rule-row", "aria-expanded": selected, onclick: () => select(selected ? null : r.index) },
        el("span", { class: `chip ${r.level}` }, r.level),
        el("span", { class: "code" }, r.code),
        el("span", { class: "title" }, r.title),
        r.edge ? edgeTag() : null,
        r.problem ? el("span", { class: "problem", title: r.problem }, "⚠") : null
      ),
      selected ? (page.mode === "edit" ? ruleForm(r) : ruleCard(r)) : null
    );
  });
}

// ---- a rule as people read it, in Check mode --------------------------------------
function ruleCard(rule) {
  const dims = Object.entries(rule.dimensions).filter(([, text]) => text);
  const facts = [rule.confidence && `Confidence: ${rule.confidence}`, rule.status && `Status: ${rule.status}`].filter(Boolean);
  return el(
    "div",
    { class: "rule-card" },
    el("p", {}, rule.message),
    rule.instruction ? el("p", { class: "instruction" }, el("strong", {}, "What to do: "), rule.instruction) : null,
    rule.changes.length
      ? [el("h3", {}, "Changes"), el("ul", { class: "plain" }, rule.changes.map((c) => el("li", { class: "change" }, `${c.target} ${c.key} = ${c.value}`, c.rationale ? el("span", { class: "hint" }, ` (${c.rationale})`) : null)))]
      : null,
    el("h3", {}, "Where"),
    el("p", {}, rule.fill ? (rule.edge ? "Where a domain's edge crosses the area shown on the globe." : "In the area shown on the globe.") : "Anywhere."),
    el("h3", {}, "When"),
    el("p", {}, timeText(rule.time)),
    dims.length ? [el("h3", {}, "What it applies to"), el("ul", { class: "plain" }, dims.map(([name, text]) => el("li", {}, el("strong", {}, `${name}: `), text)))] : null,
    rule.references.length ? [el("h3", {}, "References"), el("ul", { class: "plain" }, rule.references.map((ref) => el("li", {}, linked(ref.title || ref.citation || ref.url || ref.doi || JSON.stringify(ref), ref.url || (ref.doi ? `https://doi.org/${ref.doi}` : "")))))] : null,
    rule.evidence.length ? [el("h3", {}, "Evidence"), rule.evidence.map((ev) => el("blockquote", {}, ev.quote || ev.text || JSON.stringify(ev), ev.url ? [" ", linked("source", ev.url)] : null))] : null,
    facts.length ? el("p", { class: "hint" }, facts.join(" · ")) : null,
    rule.problem ? el("p", { class: "problem" }, rule.problem) : null
  );
}

function timeText(time) {
  const range = time.start && time.end ? `From ${time.start} to ${time.end}` : time.start ? `From ${time.start}` : time.end ? `Until ${time.end}` : "";
  const months = time.months.length ? `${range ? "in" : "In"} ${time.months.map((m) => MONTHS[m - 1]).join(", ")}` : "";
  const text = [range, months].filter(Boolean).join(", ");
  return [text ? `${text}.` : time.kept ? "" : "Any time.", time.kept ? `Also: ${time.kept}.` : ""].filter(Boolean).join(" ");
}

// A link only for a web address, never for script or data URLs from a file.
function linked(text, url) {
  let href = null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") href = parsed.href;
  } catch {}
  return href ? el("a", { href, target: "_blank", rel: "noopener noreferrer" }, text) : String(text);
}

function ruleForm(rule) {
  const months = new Set(rule.time.months);
  const dims = page.state.dimensions;
  const declared = new Set(dims.map((d) => d.name));
  const shapeText = rule.fill
    ? rule.editable
      ? "This rule has a shape. Move its corners, or draw a new one."
      : "This rule's shape crosses the date line, reaches a pole or has holes: draw a new one to change it."
    : "No shape: the rule applies anywhere.";
  const dimInput = (name, kind, problem) =>
    field(
      `f-dim-${name}`,
      [name, kind ? unit(dims.find((d) => d.name === name)) : null],
      [
        el("input", { id: `f-dim-${name}`, "data-rule-dim": name, value: rule.dimensions[name] || "", placeholder: HINTS[kind] || "", title: HINTS[kind] || "", "aria-invalid": Boolean(problem), onchange: edit((e) => ({ dimensions: { [name]: e.target.value } })) }),
        problem ? el("p", { class: "problem" }, problem) : null,
      ]
    );
  return el(
    "div",
    { class: "rule-form" },
    el(
      "div",
      { class: "two" },
      field("f-code", "Code", el("input", { id: "f-code", value: rule.code, onchange: edit((e) => ({ code: e.target.value })) })),
      field(
        "f-level",
        "Level",
        el("select", { id: "f-level", onchange: edit((e) => ({ level: e.target.value })) }, LEVELS.map(([value, text]) => el("option", { value, selected: value === rule.declared_level }, value ? text : `default (${rule.changes.length ? "info" : "warning"})`)))
      )
    ),
    field("f-title", "Title", el("input", { id: "f-title", value: rule.title, onchange: edit((e) => ({ title: e.target.value })) })),
    field("f-message", "Message", el("textarea", { id: "f-message", onchange: edit((e) => ({ message: e.target.value })) }, rule.message)),
    rule.problem ? el("p", { class: "problem" }, rule.problem) : null,

    el("h3", {}, "Where"),
    el("p", { class: "hint" }, shapeText),
    page.drawing === "corners"
      ? el(
          "div",
          { class: "notice" },
          el("p", {}, `Moving the corners of ${rule.code}: drag a corner, or the middle of an edge to add one.`),
          el("div", { class: "row" }, el("button", { class: "primary", onclick: () => finishCorners(true) }, "Done"), el("button", { onclick: () => finishCorners(false) }, "Cancel"))
        )
      : el(
          "div",
          { class: "row" },
          el("button", { onclick: () => startDrawing("rectangle", "rule") }, "Draw rectangle"),
          el("button", { onclick: () => startDrawing("polygon", "rule") }, "Draw polygon"),
          el("button", { onclick: moveCorners, disabled: !rule.editable }, "Move corners"),
          el("button", { onclick: () => shapeCall("clear", {}), disabled: !rule.fill }, "Remove shape")
        ),
    el(
      "div",
      { class: "row" },
      el("button", { onclick: () => shapeCall("cap", { pole: "north", latitude: Number(document.getElementById("cap-north").value) }) }, "Arctic cap from"),
      el("input", { id: "cap-north", class: "inline-number", type: "number", value: 66.5, step: 0.5, min: 0, max: 89, "aria-label": "Arctic cap latitude" }),
      el("span", {}, "°N")
    ),
    el(
      "div",
      { class: "row" },
      el("button", { onclick: () => shapeCall("cap", { pole: "south", latitude: Number(document.getElementById("cap-south").value) }) }, "Antarctic cap from"),
      el("input", { id: "cap-south", class: "inline-number", type: "number", value: -60, step: 0.5, min: -89, max: 0, "aria-label": "Antarctic cap latitude" }),
      el("span", {}, "°")
    ),
    el(
      "div",
      { class: "row" },
      el("input", { id: "f-edge", type: "checkbox", style: "width:auto", checked: rule.edge, onchange: edit((e) => ({ edge: e.target.checked })) }),
      el("label", { for: "f-edge" }, "Applies where a domain's edge crosses this area")
    ),

    el("h3", {}, "When"),
    el(
      "div",
      { class: "two" },
      field("f-start", "From", el("input", { id: "f-start", type: "date", value: rule.time.start, onchange: edit(timeFields) })),
      field("f-end", "To", el("input", { id: "f-end", type: "date", value: rule.time.end, onchange: edit(timeFields) }))
    ),
    rule.time.kept ? el("p", { class: "hint" }, `Also in the file: ${rule.time.kept}. Changing the dates replaces it.`) : null,
    el(
      "fieldset",
      { class: "months" },
      el("legend", {}, "Months of every year (none ticked: all)"),
      MONTHS.map((name, i) => el("label", {}, el("input", { type: "checkbox", value: i + 1, checked: months.has(i + 1), onchange: edit(monthFields) }), name))
    ),

    dims.length || Object.keys(rule.dimensions).length ? el("h3", {}, "What it applies to") : null,
    dims.map((d) => dimInput(d.name, d.kind, null)),
    Object.keys(rule.dimensions)
      .filter((name) => !declared.has(name))
      .map((name) => dimInput(name, null, `${name} is not declared: add it under Dimensions, or empty this field.`)),

    el("h3", {}, "Changes"),
    el("p", { class: "hint" }, 'What to change when this rule applies. The value is JSON, such as 900, true or "CICE"; plain text is taken as text.'),
    el("div", { id: "f-changes" }, rule.changes.map(changeRow)),
    el("div", { class: "row" }, el("button", { onclick: addChange }, "Add change")),

    el("div", { class: "row danger-row" }, deleteButton(rule))
  );
}

function timeFields() {
  return { time: [document.getElementById("f-start").value, document.getElementById("f-end").value] };
}

function monthFields() {
  return { months: [...document.querySelectorAll(".months input:checked")].map((input) => Number(input.value)) };
}

function changeFields() {
  const part = (row, name) => row.querySelector(`[data-part=${name}]`).value;
  return {
    changes: [...document.querySelectorAll("#f-changes .change-row")].map((row) => ({
      target: part(row, "target"),
      key: part(row, "key"),
      value: part(row, "value"),
      rationale: part(row, "rationale"),
    })),
  };
}

function changeRow(change = { target: "", key: "", value: "", rationale: "" }) {
  const input = (name, label) => el("input", { "data-part": name, "aria-label": label, placeholder: label, value: change[name], onchange: edit(changeFields) });
  const row = el(
    "div",
    { class: "change-row" },
    input("target", "target"),
    input("key", "key"),
    input("value", "value"),
    el("button", { type: "button", class: "remove", "aria-label": "Remove this change", title: "Remove this change", onclick: () => (row.remove(), edit(changeFields)({ target: row })) }, "×"),
    input("rationale", "why (optional)")
  );
  return row;
}

function addChange() {
  const row = changeRow();
  document.getElementById("f-changes").append(row);
  row.querySelector("input").focus();
}

function deleteButton(rule) {
  // Two clicks delete: the first asks, the second deletes; asking ends after a while.
  const button = el("button", { class: "danger" }, `Delete ${rule.code}`);
  button.onclick = () => {
    if (button.dataset.asking) return deleteRule(rule);
    button.dataset.asking = "1";
    button.textContent = `Click again to delete ${rule.code}`;
    setTimeout(() => {
      delete button.dataset.asking;
      button.textContent = `Delete ${rule.code}`;
    }, 5000);
  };
  return button;
}

// Keep one edit of the selected rule. If queryearth refuses it, the field keeps
// what was typed, marked, and the status line says why.
function edit(fields) {
  return async (event) => {
    const index = page.selected;
    try {
      page.state = await call("update", { index, fields: fields(event) });
      saveDraft();
      say(`Kept ${page.state.rules[index].code}.`);
      render();
    } catch (err) {
      if (event.target.type === "checkbox") event.target.checked = !event.target.checked;
      else event.target.setAttribute?.("aria-invalid", "true");
      say(`Not kept: ${err.message}`, true);
    }
  };
}

function select(index, { reveal = false } = {}) {
  stopDrawing();
  page.selected = index;
  render();
  const rule = page.state?.rules[index];
  if (rule?.extent) fitExtent(rule.extent);
  if (reveal) document.querySelector(".rules li[aria-current='true']")?.scrollIntoView({ block: "nearest" });
}

async function newRule() {
  try {
    const out = await call("new", { prefix: document.getElementById("new-group")?.value || null });
    page.state = out.state;
    saveDraft();
    select(out.index, { reveal: true });
    say(`Added ${page.state.rules[out.index].code}: fill in its fields and draw its shape.`);
  } catch (err) {
    say(err.message, true);
  }
}

async function deleteRule(rule) {
  try {
    page.state = await call("delete", { index: rule.index });
  } catch (err) {
    return say(err.message, true);
  }
  page.selected = null;
  saveDraft();
  say(`Deleted ${rule.code}.`);
  render();
}

async function shapeCall(name, args) {
  try {
    page.state = await call(name, { index: page.selected, ...args });
    saveDraft();
    say(`Kept the shape of ${page.state.rules[page.selected].code}.`);
  } catch (err) {
    say(err.message, true);
  }
  render();
}

// ---- groups: the prefixes of the codes, with titles ------------------------------
function groupsSection() {
  const state = page.state;
  const groups = state?.groups || [];
  const ungrouped = !groups.length && state?.prefixes.length ? state.prefixes : null;
  const listed = groups.map(({ prefix, title }) => ({ prefix, title }));
  return el(
    "section",
    { id: "groups" },
    el("h2", {}, "Groups"),
    el("p", { class: "hint" }, "A rule's group is the prefix of its code: OBC for OBC001. Once a file has groups, every rule's code uses one, and a new rule takes the next number in its group."),
    el(
      "ul",
      { class: "dims" },
      groups.map((g) =>
        el(
          "li",
          {},
          el("strong", {}, g.prefix),
          el("input", { "aria-label": `Title of ${g.prefix}`, value: g.title, onchange: (e) => setGroups(listed.map((h) => (h.prefix === g.prefix ? { ...h, title: e.target.value } : h))) }),
          el("span", { class: "count" }, `${g.rules} rule${g.rules === 1 ? "" : "s"}`),
          el("button", { type: "button", class: "remove", "aria-label": `Remove ${g.prefix}`, title: g.rules ? `${g.prefix} has rules` : `Remove ${g.prefix}`, disabled: g.rules > 0, onclick: () => setGroups(listed.filter((h) => h.prefix !== g.prefix)) }, "×")
        )
      )
    ),
    ungrouped
      ? el(
          "div",
          { class: "notice" },
          el("p", {}, `These rules have no groups. Once there are groups, every rule's prefix must be one, so groups start with one for each prefix in use: ${ungrouped.join(", ")}.`),
          el("div", { class: "row" }, el("button", { onclick: () => setGroups(ungrouped.map((prefix) => ({ prefix, title: prefix }))) }, "Make a group for each prefix"))
        )
      : el(
          "form",
          { class: "row add-dim", onsubmit: addGroup },
          el("input", { id: "g-prefix", "aria-label": "Prefix of the group", placeholder: "prefix, such as OBC", required: true, autocapitalize: "characters" }),
          el("input", { id: "g-title", "aria-label": "Title of the group", placeholder: "title, such as Open boundaries", required: true }),
          el("button", { type: "submit" }, "Add")
        )
  );
}

async function addGroup(event) {
  event.preventDefault();
  const prefix = document.getElementById("g-prefix").value.trim().toUpperCase();
  const title = document.getElementById("g-title").value.trim();
  const listed = (page.state?.groups || []).map(({ prefix, title }) => ({ prefix, title }));
  await setGroups([...listed, { prefix, title }]);
}

async function setGroups(groups) {
  try {
    page.state = await call("groups", { groups });
    saveDraft();
    say("Kept the groups.");
    render();
  } catch (err) {
    say(`Not kept: ${err.message}`, true);
  }
}

// ---- dimensions: what rules can depend on besides place and time ----------------
function dimensionsSection() {
  const dims = page.state?.dimensions || [];
  return el(
    "section",
    { id: "dimensions" },
    el("h2", {}, "Dimensions"),
    el("p", { class: "hint" }, "What rules can depend on besides place and time: labels are names, such as a product; an axis is numbers with a unit, such as a resolution in km; versions are such as 4.07. The rules file keeps this list."),
    el(
      "ul",
      { class: "dims" },
      dims.map((d, i) =>
        el(
          "li",
          {},
          el("strong", {}, d.name),
          el("span", {}, ` ${d.kind}${d.kind === "axis" ? `, in ${d.unit}` : ""}`),
          el("button", { type: "button", class: "remove", "aria-label": `Remove ${d.name}`, title: `Remove ${d.name}`, onclick: () => setDimensions(dims.filter((_, j) => j !== i)) }, "×")
        )
      )
    ),
    el(
      "form",
      { class: "row add-dim", onsubmit: addDimension },
      el("input", { id: "d-name", "aria-label": "Name of the dimension", placeholder: "name, such as product", required: true }),
      el("select", { id: "d-kind", "aria-label": "Kind", onchange: (e) => (document.getElementById("d-unit").disabled = e.target.value !== "axis") }, KINDS.map((k) => el("option", { value: k }, k))),
      el("input", { id: "d-unit", "aria-label": "Unit", placeholder: "unit, such as km", disabled: true }),
      el("button", { type: "submit" }, "Add")
    )
  );
}

async function addDimension(event) {
  event.preventDefault();
  const kind = document.getElementById("d-kind").value;
  const added = { name: document.getElementById("d-name").value.trim(), kind };
  if (kind === "axis") added.unit = document.getElementById("d-unit").value.trim();
  await setDimensions([...(page.state?.dimensions || []), added]);
}

async function setDimensions(dimensions) {
  try {
    page.state = await call("dimensions", { dimensions });
    saveDraft();
    say(page.state.problems.length ? "Kept the dimensions. Some rules now have problems: see File." : "Kept the dimensions.");
    render();
  } catch (err) {
    say(`Not kept: ${err.message}`, true);
  }
}

// ---- file: download the rules, or a web page that shows them ---------------------
function fileSection() {
  const state = page.state;
  return el(
    "section",
    { id: "file" },
    el("h2", {}, "File"),
    el("p", { class: "hint" }, `${state?.name || "rules.geojson"}: download it to keep your changes, and open it again later.`),
    (state?.problems || []).map((p) => el("p", { class: "problem" }, p)),
    el("div", { class: "row" }, el("button", { class: "primary", onclick: downloadRules }, "Download rules file")),
    field("page-title", "Title of the web page", el("input", { id: "page-title", value: page.pageTitle, oninput: (e) => (page.pageTitle = e.target.value) })),
    el("div", { class: "row" }, el("button", { onclick: downloadPage }, "Download as web page")),
    el("p", { class: "hint" }, "The web page shows these rules on the globe, as you see them now, wherever you put it: GitHub Pages, any web host, or a folder on your computer.")
  );
}

async function downloadRules() {
  let text;
  try {
    text = await call("text");
  } catch (err) {
    return say(`Not downloaded: ${err.message}`, true);
  }
  const name = page.state?.name || "rules.geojson";
  const warning = download(name, text, "application/geo+json");
  if (warning === false) return;
  if (!EMBEDDED) store.clear(); // kept where downloads may be blocked
  say(`Downloaded ${name}.${warning}`);
}

async function downloadPage() {
  let text;
  try {
    text = await call("text");
  } catch (err) {
    return say(`Not downloaded: ${err.message}`, true);
  }
  const title = page.pageTitle.trim() || "My rules";
  const view = map ? { center: map.getCenter().toArray().map((v) => Math.round(v * 100) / 100), zoom: Math.round(map.getZoom() * 10) / 10 } : page.settings.view || DEFAULT_VIEW;
  const site = { title, description: page.settings.description, view, rules: JSON.parse(text) };
  const json = JSON.stringify(site, null, 1).replaceAll("</", "<\\/");
  const escaped = title.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const html = [
    "<!doctype html>",
    '<html lang="en">',
    "<head>",
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<title>${escaped}</title>`,
    `<link rel="stylesheet" href="${new URL("app.css", APP).href}">`,
    `<script type="module" src="${new URL("app.js", APP).href}"></script>`,
    "</head>",
    "<body>",
    '<script type="application/json" id="vizqueryearth-site">',
    json,
    "</script>",
    "</body>",
    "</html>",
    "",
  ].join("\n");
  const warning = download("index.html", html, "text/html");
  if (warning === false) return;
  say(`Downloaded index.html: put it on any web host, such as GitHub Pages, to share these rules.${warning}`);
}

function saveDraft() {
  call("text")
    .then((text) => store.set({ name: page.state.name, text, saved: new Date().toISOString() }))
    .catch(() => {}); // a file with problems is kept as it was last valid
}

function draftNotice() {
  const draft = page.draft;
  return el(
    "div",
    { class: "notice" },
    el("p", {}, `You have edits from ${new Date(draft.saved).toLocaleString()} that were not downloaded.`),
    el(
      "div",
      { class: "row" },
      el("button", { class: "primary", onclick: async () => ((page.draft = null), await open(draft.text, draft.name, { fit: true })) }, "Restore them"),
      el("button", { onclick: () => (store.clear(), (page.draft = null), render()) }, "Discard")
    )
  );
}

// In Check mode, a pointer to the edits waiting in Edit mode.
function draftPointer() {
  return el(
    "div",
    { class: "notice" },
    el("p", {}, `You have edits from ${new Date(page.draft.saved).toLocaleString()} that were not downloaded.`),
    el("div", { class: "row" }, el("button", { class: "primary", onclick: () => setMode("edit") }, "Go to Edit to restore them"))
  );
}

// ---- opening files --------------------------------------------------------------
async function open(text, name, { fit = true } = {}) {
  page.state = await call("open", { text, name, dimensions: page.settings.dimensions });
  page.selected = null;
  page.results = null;
  if (page.filter.group && !page.state.filters.some((f) => f.prefix === page.filter.group)) setFilter({ group: "" });
  const n = page.state.rules.length;
  say(`Opened ${name}: ${n} rule${n === 1 ? "" : "s"}${page.state.problems.length ? ", with problems (see File)" : ""}.`);
  render();
  if (fit) fitExtent(page.state.extent, { animate: false });
}

async function openFile(event) {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  try {
    await open(await file.text(), file.name);
  } catch (err) {
    say(`Could not open ${file.name}: ${err.message}`, true);
  }
}

function showLinkBar(show) {
  document.getElementById("linkbar").hidden = !show;
  document.getElementById("open-link").setAttribute("aria-expanded", String(show));
  if (show) document.getElementById("link-url").focus();
}

async function submitLink(event) {
  event.preventDefault();
  const url = document.getElementById("link-url").value.trim();
  if (!url) return;
  showLinkBar(false);
  if (await openUrl(url)) {
    const params = new URLSearchParams(location.search);
    params.set("src", url);
    history.replaceState(null, "", `?${params}${location.hash}`); // this page's address now shows these rules
  }
}

async function openUrl(url, options) {
  say(`Opening ${url}…`);
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`the server said ${response.status}`);
    await open(await response.text(), decodeURIComponent(new URL(url, location.href).pathname.split("/").pop() || "rules.geojson"), options);
    return true;
  } catch (err) {
    say(`Could not open ${url}: ${err.message}`, true);
    return false;
  }
}

// ---- the globe ------------------------------------------------------------------
async function startMap() {
  document.head.append(el("link", { rel: "stylesheet", href: LIBS.maplibreCss }));
  maplibregl = await import(LIBS.maplibre);
  const land = landForGlobe(await (await fetch(LIBS.land)).json());
  const css = getComputedStyle(document.documentElement);
  const view = page.settings.view || DEFAULT_VIEW;
  const color = ["match", ["get", "level"], "error", LEVEL_COLOR.error, "warning", LEVEL_COLOR.warning, LEVEL_COLOR.info];
  const selected = ["boolean", ["feature-state", "selected"], false];
  const hit = ["boolean", ["feature-state", "hit"], false];
  const edge = ["==", ["get", "edge"], true];
  map = new maplibregl.Map({
    container: "map",
    center: view.center,
    zoom: view.zoom,
    minZoom: -2, // looking down on a pole needs it: the globe's zoom grows with latitude
    attributionControl: { compact: true, customAttribution: "Land: Natural Earth" },
    style: {
      version: 8,
      projection: { type: "globe" },
      sources: {
        land: { type: "geojson", data: land },
        rules: { type: "geojson", data: collection([]), promoteId: "index" },
        outlines: { type: "geojson", data: collection([]), promoteId: "index" },
        area: { type: "geojson", data: collection([]) },
      },
      layers: [
        { id: "ocean", type: "background", paint: { "background-color": css.getPropertyValue("--ocean").trim() || "#d3e4f1" } },
        { id: "land", type: "fill", source: "land", paint: { "fill-color": css.getPropertyValue("--land").trim() || "#efece3" } },
        {
          id: "rules-fill",
          type: "fill",
          source: "rules",
          paint: {
            "fill-color": color,
            // an edge rule is lighter: it applies along a domain's edge, not all over
            "fill-opacity": ["*", ["case", edge, 0.45, 1], ["case", selected, 0.45, hit, 0.4, ["boolean", ["feature-state", "dim"], false], 0.05, 0.2]],
            "fill-antialias": false, // no faint edge where the globe cuts shapes near the poles
          },
        },
        { id: "rules-line", type: "line", source: "outlines", filter: ["!", edge], paint: { "line-color": color, "line-width": ["case", selected, 3.5, hit, 2.5, 1.2] } },
        { id: "rules-edge", type: "line", source: "outlines", filter: edge, paint: { "line-color": color, "line-width": ["case", selected, 3.5, hit, 2.5, 1.5], "line-dasharray": [2, 1.5] } },
        { id: "area-fill", type: "fill", source: "area", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#111", "fill-opacity": 0.12, "fill-antialias": false } },
        { id: "area-line", type: "line", source: "area", paint: { "line-color": "#111", "line-width": 2, "line-dasharray": [2, 1] } },
      ],
    },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
  map.addControl(
    {
      onAdd: () => el("div", { class: "maplibregl-ctrl maplibregl-ctrl-group" }, el("button", { type: "button", class: "fit", title: "Fit to rules", "aria-label": "Fit to rules", onclick: fitRules }, "Fit")),
      onRemove: () => {},
    },
    "top-left"
  );
  await new Promise((resolve) => map.on("load", resolve));
  map.on("click", "rules-fill", ruleClicked);
  map.on("mouseenter", "rules-fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "rules-fill", () => (map.getCanvas().style.cursor = ""));

  await loadScript(LIBS.terraDraw);
  await loadScript(LIBS.terraDrawAdapter);
  const TD = globalThis.terraDraw;
  draw = new TD.TerraDraw({
    adapter: new globalThis.terraDrawMaplibreGlAdapter.TerraDrawMapLibreGLAdapter({ map }),
    modes: [
      new TD.TerraDrawPolygonMode(),
      new TD.TerraDrawRectangleMode(),
      new TD.TerraDrawSelectMode({
        flags: { polygon: { feature: { draggable: true, coordinates: { midpoints: true, draggable: true, deletable: true } } } },
      }),
    ],
  });
  draw.start();
  draw.on("finish", (id, context) => {
    if (context?.action === "draw") finishDrawing();
  });
}

// The globe draws data only to about 85° north and south, and covers the rest
// from shapes whose edge reaches the pole. Antarctica in Natural Earth runs to
// the pole along 89.99°S, which the globe draws badly, so it is cut at 84°S and
// a band of land from there to the pole takes its place (it also covers the
// last degree of the Ross Ice Shelf, which Natural Earth counts as sea).
function landForGlobe(land) {
  const SOUTH = -84;
  const cut = (ring) => {
    const kept = [];
    for (let i = 0; i < ring.length - 1; i++) {
      const [x1, y1] = ring[i];
      const [x2, y2] = ring[i + 1];
      if (y1 >= SOUTH) kept.push([x1, y1]);
      if (y1 >= SOUTH !== y2 >= SOUTH) kept.push([x1 + ((SOUTH - y1) / (y2 - y1)) * (x2 - x1), SOUTH]);
    }
    return kept.length >= 3 ? [...kept, kept[0]] : null;
  };
  for (const feature of land.features) {
    const geometry = feature.geometry;
    const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
    for (const polygon of polygons) {
      if (Math.min(...polygon[0].map((p) => p[1])) < SOUTH) polygon[0] = cut(polygon[0]);
    }
    const kept = polygons.filter((polygon) => polygon[0]);
    if (geometry.type === "Polygon") geometry.coordinates = kept[0] || [];
    else geometry.coordinates = kept;
  }
  const band = [[-180, -90], [180, -90], [180, SOUTH], [-180, SOUTH], [-180, -90]];
  land.features.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [band] } });
  return land;
}

function drawRules() {
  if (!map?.getSource("rules") || !page.state) return;
  const rules = shown().filter((r) => r.fill);
  const properties = (r) => ({ index: r.index, level: r.level, edge: r.edge });
  map.getSource("rules").setData(collection(rules.map((r) => ({ type: "Feature", geometry: r.fill, properties: properties(r) }))));
  map.getSource("outlines").setData(collection(rules.filter((r) => r.outline).map((r) => ({ type: "Feature", geometry: r.outline, properties: properties(r) }))));
  const results = page.mode === "check" ? page.results : null; // the check belongs to Check mode
  const hits = new Set(results?.findings.map((f) => f.code) || []);
  for (const r of rules) {
    const state = { selected: r.index === page.selected, hit: hits.has(r.code), dim: results !== null && !hits.has(r.code) };
    map.setFeatureState({ source: "rules", id: r.index }, state);
    map.setFeatureState({ source: "outlines", id: r.index }, state);
  }
  for (const marker of page.markers) marker.remove();
  page.markers = rules
    .filter((r) => r.label)
    .map((r) =>
      new maplibregl.Marker({
        element: el("div", { class: `label ${r.level}${r.index === page.selected ? " selected" : ""}`, title: r.title, onclick: (e) => (e.stopPropagation(), labelClicked(r)) }, r.code),
        opacityWhenCovered: 0, // labels on the far side of the globe are hidden
      })
        .setLngLat(r.label)
        .addTo(map)
    );
}

function drawArea() {
  if (!map?.getSource("area")) return;
  const shape = page.mode === "check" ? page.areaShape : null; // kept, but shown only in Check
  const features = shape ? [{ type: "Feature", geometry: shape.fill, properties: {} }] : [];
  if (shape?.outline) features.push({ type: "Feature", geometry: shape.outline, properties: {} });
  map.getSource("area").setData(collection(features));
}

function labelClicked(rule) {
  if (page.drawing) return;
  select(rule.index, { reveal: true });
}

function ruleClicked(event) {
  // a click that draws, or finishes a drawing, is not a click on the rule below
  if (page.drawing || performance.now() - page.drawingEnded < 500) return;
  const indexes = [...new Set(event.features.map((f) => f.properties.index))];
  // clicking again where rules overlap selects the next one
  select(indexes[(indexes.indexOf(page.selected) + 1) % indexes.length], { reveal: true });
}

function focusRule(code) {
  const rule = page.state.rules.find((r) => r.code === code);
  if (rule) select(rule.index, { reveal: true });
}

async function fitRules({ quiet = false } = {}) {
  const extent = page.state ? await call("extent", { indexes: shown().map((r) => r.index) }) : null;
  if (extent) fitExtent(extent);
  else if (!quiet) say("No rule shown has a shape.");
}

// Turn the globe to an extent [west, south, east, north] from Python, where
// east is past 180 for an extent across the date line.
function fitExtent(extent, { animate = true } = {}) {
  if (!map || !extent) return;
  const [west, south, east, north] = extent;
  let camera;
  if (east - west > 180) {
    // more than half way round, which a globe cannot show at once: look down
    // on the pole the rules are about, or at the side of the globe they centre on
    if (south >= 30) camera = cameraShowing([0, 85], [0, 90, 180, -90].map((lon) => [lon, south]));
    else if (north <= -30) camera = cameraShowing([0, -85], [0, 90, 180, -90].map((lon) => [lon, north]));
    else {
      const center = [(west + east) / 2, Math.max(-60, Math.min(60, (south + north) / 2))];
      const [lon, lat] = center;
      camera = cameraShowing(center, [[lon - 80, lat], [lon + 80, lat], [lon, Math.min(lat + 80, 85)], [lon, Math.max(lat - 80, -85)]]);
    }
  } else {
    camera = map.cameraForBounds([[west, Math.max(south, -85)], [east, Math.min(north, 85)]], { padding: 40, maxZoom: 6 });
  }
  if (!camera) return;
  map.stop();
  if (animate) map.flyTo({ ...camera, pitch: 0 });
  else map.jumpTo({ ...camera, pitch: 0 });
}

// The closest view from above center that shows every point, found by trying
// zoom levels: the globe's zoom depends on latitude, so it is hard to compute.
function cameraShowing(center, points) {
  const before = { center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() };
  const { width, height } = map.getContainer().getBoundingClientRect();
  let low = map.getMinZoom();
  let high = 8;
  for (let i = 0; i < 12; i++) {
    const zoom = (low + high) / 2;
    map.jumpTo({ center, zoom, bearing: 0, pitch: 0 });
    const fits = points.every((point) => {
      const p = map.project(point);
      return p.x >= 30 && p.x <= width - 30 && p.y >= 30 && p.y <= height - 30;
    });
    if (fits) low = zoom;
    else high = zoom;
  }
  map.jumpTo(before);
  return { center, zoom: low, bearing: 0 };
}

// ---- drawing ----------------------------------------------------------------------
function startDrawing(kind, purpose) {
  if (!draw) return say("The globe is still loading.", true);
  stopDrawing();
  page.drawing = purpose;
  draw.setMode(kind);
  say(
    kind === "rectangle"
      ? "Click one corner, then the opposite corner."
      : "Click to add corners; click the first corner again to finish. Esc cancels."
  );
}

function stopDrawing() {
  if (!draw) return;
  if (page.drawing) page.drawingEnded = performance.now();
  page.drawing = null;
  draw.clear();
  draw.setMode("static");
}

function drawn() {
  return draw.getSnapshot().filter((f) => f.geometry.type === "Polygon").map((f) => ({ type: "Feature", properties: {}, geometry: f.geometry }));
}

async function finishDrawing() {
  const purpose = page.drawing;
  const features = drawn();
  stopDrawing();
  if (purpose === "area") {
    page.area = features;
    try {
      page.areaShape = await call("area", { features });
    } catch (err) {
      page.area = [];
      page.areaShape = null;
      say(err.message, true);
    }
    page.results = null;
    drawArea();
    if (page.areaShape) say("Area drawn. Fill in the rest and click Check.");
    render();
  } else if (purpose === "rule") {
    await keepShape(features);
  }
}

async function keepShape(features) {
  try {
    page.state = await call("draw", { index: page.selected, features });
    saveDraft();
    say(`Kept the shape of ${page.state.rules[page.selected].code}.`);
  } catch (err) {
    say(err.message, true);
  }
  render();
}

function moveCorners() {
  const rule = page.state.rules[page.selected];
  stopDrawing();
  page.drawing = "corners";
  draw.addFeatures(rule.editable.map((geometry) => ({ type: "Feature", properties: { mode: "polygon" }, geometry })));
  draw.setMode("select");
  say("Drag corners, or the middle of an edge to add one. Click Done when finished.");
  render();
}

async function finishCorners(keep) {
  const features = drawn();
  stopDrawing();
  if (keep) return keepShape(features);
  say("Left the shape as it was.");
  render();
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (page.drawing && page.drawing !== "corners") {
    stopDrawing();
    say("Stopped drawing.");
  } else if (!document.getElementById("linkbar")?.hidden) {
    showLinkBar(false);
  }
});

// ---- start ----------------------------------------------------------------------
async function main() {
  page.settings = await readSettings();
  const kept = filterStore.get();
  if (typeof kept?.text === "string" && typeof kept?.group === "string") page.filter = { text: kept.text, group: kept.group };
  const chosen = chosenMode();
  page.mode = chosen.mode;
  document.body.dataset.mode = chosen.mode;
  build();
  for (const button of document.querySelectorAll(".modes button")) button.setAttribute("aria-pressed", String(button.dataset.mode === page.mode));
  window.addEventListener("hashchange", () => setMode(location.hash.slice(1)));
  say("Starting… The first visit downloads Python and queryearth (about 20 MB); later visits are quicker.");
  pythonReady = startPython();
  const mapReady = startMap().catch((err) => say(`The globe could not start: ${err.message}`, true));
  render();
  try {
    await pythonReady;
  } catch (err) {
    say(`Python could not start: ${err.message}`, true);
    return;
  }
  await mapReady;
  const source = page.settings.source;
  const fit = !page.settings.view; // a page that sets its view keeps it
  if (source?.url) await openUrl(source.url, { fit });
  else if (source?.text) await open(source.text, source.name, { fit }).catch((err) => say(`Could not open the rules: ${err.message}`, true));
  if (!page.state) {
    // nothing to open, or it could not be opened: the status line says why
    page.state = await call("state");
    if (!source) say("Ready. Open a rules file, or click New rule to start one.");
    render();
  }
  const draft = store.get();
  if (draft && page.state && draft.text !== (await call("text").catch(() => null))) {
    // edits waiting: show them in Edit mode, unless the address asked for Check,
    // where a notice points to them
    page.draft = draft;
    if (page.mode !== "edit" && !chosen.asked) setMode("edit");
    else render();
    say("You have edits that were not downloaded: restore or discard them in Edit.");
  }
  window.__vizqueryearth = { page, call, map: () => map, draw: () => draw }; // for tests
}

main();
