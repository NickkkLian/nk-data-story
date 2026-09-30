"""Build, embed, and check clickable number provenance (Python 3.8+)."""

import argparse
import copy
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"computation", "formula", "command", "input", "stated"}
VOID = set("area base br col embed hr img input link meta param source track wbr".split())
IGNORED = {"script", "style", "template"}


def _string(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value, required=False):
    return (isinstance(value, list) and (bool(value) or not required)
            and all(_string(item) for item in value))


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _input_errors(inputs):
    errors, seen = [], set()
    if not isinstance(inputs, list):
        return ["inputs must be a list"]
    for index, item in enumerate(inputs):
        prefix = "inputs[{}]".format(index)
        if not isinstance(item, dict):
            errors.append(prefix + " must be an object")
            continue
        ident = item.get("id")
        if not _string(ident):
            errors.append(prefix + ".id must be non-empty")
        elif ident in seen:
            errors.append(prefix + ".id is duplicated")
        else:
            seen.add(ident)
        if not _string(item.get("name")):
            errors.append(prefix + ".name must be non-empty")
        if "sha256" in item and not (isinstance(item["sha256"], str) and SHA.fullmatch(item["sha256"])):
            errors.append(prefix + ".sha256 must be 64 lowercase hex characters")
        if "rows" in item and not _int(item["rows"]):
            errors.append(prefix + ".rows must be an integer >= 0")
        if "synthetic" in item and type(item["synthetic"]) is not bool:
            errors.append(prefix + ".synthetic must be a boolean")
    return errors


def _entry_errors(entry):
    errors = []
    if not isinstance(entry, dict):
        return ["entry must be an object"]
    if not _string(entry.get("label")):
        errors.append("label must be non-empty")
    if "live" in entry and type(entry["live"]) is not bool:
        errors.append("live must be a boolean")
    how = entry.get("how")
    if not isinstance(how, dict):
        errors.append("how must contain kind and text")
    else:
        if not isinstance(how.get("kind"), str) or how["kind"] not in KINDS:
            errors.append("how.kind is unknown or missing")
        if not _string(how.get("text")):
            errors.append("how.text must be non-empty")
        if "command" in how and not _string(how["command"]):
            errors.append("how.command must be non-empty")
    if not _strings(entry.get("not_checked"), required=True):
        errors.append("not_checked must contain non-empty strings")
    origins = entry.get("from")
    if not isinstance(origins, list) or not origins:
        errors.append("from must contain at least one item")
    else:
        for index, origin in enumerate(origins):
            prefix = "from[{}]".format(index)
            if not isinstance(origin, dict) or not any(
                    field in origin for field in ("input", "rows", "rows_total", "cells", "text")):
                errors.append(prefix + " must contain a source field")
                continue
            for field in ("input", "text"):
                if field in origin and not _string(origin[field]):
                    errors.append(prefix + "." + field + " must be non-empty")
            if "rows" in origin and not (isinstance(origin["rows"], list)
                    and len(origin["rows"]) <= 50
                    and all(_int(row, 1) for row in origin["rows"])):
                errors.append(prefix + ".rows must list at most 50 positive integers")
            if "rows_total" in origin:
                if not _int(origin["rows_total"]):
                    errors.append(prefix + ".rows_total must be an integer >= 0")
                elif isinstance(origin.get("rows"), list) and origin["rows_total"] < len(origin["rows"]):
                    errors.append(prefix + ".rows_total cannot be less than the listed count")
            if "cells" in origin and not (_string(origin["cells"]) or _strings(origin["cells"], True)):
                errors.append(prefix + ".cells must name one or more cells")
    return errors


def _unknown_inputs(entry, inputs):
    known = {item.get("id") for item in inputs if isinstance(item, dict) and _string(item.get("id"))}
    origins = entry.get("from", []) if isinstance(entry, dict) else []
    if not isinstance(origins, list):
        return []
    return ["from[{}].input names no input".format(index)
            for index, item in enumerate(origins)
            if isinstance(item, dict) and "input" in item
            and (not _string(item["input"]) or item["input"] not in known)]


def _escaped_json(data):
    return (json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


class Sources:
    def __init__(self, generator, inputs=None, not_checked=None):
        if not _string(generator):
            raise ValueError("generator must be non-empty")
        inputs = [] if inputs is None else inputs
        not_checked = [] if not_checked is None else not_checked
        errors = _input_errors(inputs)
        if not _strings(not_checked):
            errors.append("not_checked must be a list of non-empty strings")
        if errors:
            raise ValueError("; ".join(errors))
        self._data = {"nk_sources": 1, "generator": generator,
                      "inputs": copy.deepcopy(inputs), "not_checked": list(not_checked), "sources": {}}

    def add(self, id, label, from_, how_kind, how_text, not_checked,
            value=None, command=None, live=False):
        if not isinstance(id, str) or not ID.fullmatch(id):
            raise ValueError("id must match " + ID.pattern)
        entry = {"label": label, "from": from_, "how": {"kind": how_kind, "text": how_text},
                 "not_checked": not_checked, "live": live}
        if value is not None:
            entry["value"] = value
        if command is not None:
            entry["how"]["command"] = command
        errors = _entry_errors(entry) + _unknown_inputs(entry, self._data["inputs"])
        if not live and not _string(value):
            errors.append("value must be non-empty unless live")
        elif value is not None and not _string(value):
            errors.append("value must be a non-empty string")
        if errors:
            raise ValueError("; ".join(errors))
        self._data["sources"][id] = copy.deepcopy(entry)
        return self

    def to_dict(self):
        return copy.deepcopy(self._data)

    def to_json(self):
        if not self._data["sources"]:
            raise ValueError("sources must contain at least one entry")
        return _escaped_json(self._data)

    def manifest_block(self):
        return '<script type="application/json" id="nk-sources">' + self.to_json() + '</script>'


def _asset(name):
    root = Path(__file__).resolve().parent
    for path in (root / name, root.parent / "assets" / name):
        if path.is_file():
            return path.read_bytes().decode("utf-8")
    raise FileNotFoundError("Missing asset: " + name)


def runtime_js():
    return _asset("numsrc.js")


def runtime_css():
    return _asset("numsrc.css")


class _Node:
    def __init__(self, tag, attrs, parent, start):
        self.tag, self.attrs, self.parent, self.start = tag, dict(attrs), parent, start
        self.end = None
        self.parts = []

    def text(self):
        return "".join(part.text() if isinstance(part, _Node) else part for part in self.parts)


class _Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", [], None, 0)
        self.stack, self.nodes, self.runs = [self.root], [], []
        self.offsets = [0]
        for match in re.finditer("\n", html):
            self.offsets.append(match.end())
        self.feed(html)
        self.close()

    def source_offset(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        child = _Node(tag, attrs, self.stack[-1], self.source_offset())
        self.stack[-1].parts.append(child)
        self.nodes.append(child)
        if tag == "br":
            self.handle_data(" ")
        if tag not in VOID:
            self.stack.append(child)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].end = self.source_offset()
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].parts.append(data)
        self.runs.append((self.stack[-1], data))


def _ancestors(node):
    while node:
        yield node
        node = node.parent


def _manifest_block(data):
    if isinstance(data, Sources):
        return data.manifest_block()
    return '<script type="application/json" id="nk-sources">' + _escaped_json(data) + '</script>'


def inject(html, sources, runtime=True):
    ids = {"nk-sources": "script"}
    if runtime:
        ids.update({"nk-sources-style": "style", "nk-sources-runtime": "script"})
    page = _Page(html)
    ranges = []
    for node in page.nodes:
        if ids.get(node.attrs.get("id")) == node.tag and node.end is not None:
            end = html.find(">", node.end)
            if end >= 0:
                ranges.append((node.start, end + 1))
    for start, end in sorted(ranges, reverse=True):
        html = html[:start] + html[end:]
    if runtime:
        head = next((node for node in _Page(html).nodes if node.tag == "head" and node.end is not None), None)
        if head is None:
            raise ValueError("html must have a closing head for runtime styles")
        css = '<style id="nk-sources-style">' + runtime_css() + '</style>'
        html = html[:head.end] + css + html[head.end:]
    body = next((node for node in _Page(html).nodes if node.tag == "body" and node.end is not None), None)
    if body is None:
        raise ValueError("html must have a closing body for the manifest")
    blocks = _manifest_block(sources)
    if runtime:
        blocks += '<script id="nk-sources-runtime">' + runtime_js() + '</script>'
    return html[:body.end] + blocks + html[body.end:]


def check(html, allow_live=True, runtime=True):
    """Return (code, level, message) tuples; warnings do not fail the CLI."""
    findings = []
    page = _Page(html)
    blocks = [node for node in page.nodes if node.attrs.get("id") == "nk-sources"]
    data = None
    if len(blocks) != 1 or blocks[0].tag != "script" or blocks[0].attrs.get("type", "").lower() != "application/json":
        findings.append(("N01", "error", "Expected exactly one application/json manifest"))
    else:
        try:
            data = json.loads(blocks[0].text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, TypeError):
            findings.append(("N01", "error", "Manifest is not valid JSON"))
    if data is not None and (not isinstance(data, dict) or type(data.get("nk_sources")) is not int
            or data.get("nk_sources") != 1 or not _string(data.get("generator"))
            or not isinstance(data.get("sources"), dict) or not data["sources"]):
        findings.append(("N01", "error", "Manifest requires nk_sources=1, generator, and non-empty sources"))
        data = None
    # JSON null is valid JSON but is not a manifest.
    if len(blocks) == 1 and blocks[0].text().strip() == "null":
        findings.append(("N01", "error", "Manifest cannot be null"))
    entries = data.get("sources", {}) if data else {}
    inputs = data.get("inputs", []) if data else []
    if data and not _strings(data.get("not_checked", [])):
        findings.append(("N03", "error", "Page not_checked must be a list of non-empty strings"))
    for error in _input_errors(inputs):
        findings.append(("N08", "error", error))
    for ident, entry in entries.items():
        if not ID.fullmatch(ident):
            findings.append(("N02", "error", "Invalid source id: " + ident))
        for error in _entry_errors(entry):
            findings.append(("N03", "error", ident + ": " + error))
        if isinstance(entry, dict):
            if entry.get("live") is True and not allow_live:
                findings.append(("N03", "error", ident + ": live entries are disabled"))
            if (entry.get("live") is not True and not _string(entry.get("value"))) or (
                    "value" in entry and not _string(entry["value"])):
                findings.append(("N04", "error", ident + ": value must be a non-empty string unless live"))
        for error in _unknown_inputs(entry, inputs if isinstance(inputs, list) else []):
            findings.append(("N08", "error", ident + ": " + error))
    traces = [node for node in page.nodes if "data-nk-src" in node.attrs
              and not any(ancestor.tag in IGNORED for ancestor in _ancestors(node))]
    text = {node: [] for node in traces}
    for node, run in page.runs:
        ancestors = list(_ancestors(node))
        if any(ancestor.tag in IGNORED for ancestor in ancestors):
            continue
        owner = next((ancestor for ancestor in ancestors if ancestor in text), None)
        if owner:
            text[owner].append(run)
        if (re.search(r"[0-9]", run) and any("data-nk-scope" in a.attrs for a in ancestors)
                and owner is None and not any(_string(a.attrs.get("data-nk-plain")) for a in ancestors)):
            findings.append(("N06", "error", "Untraced digit text: " + " ".join(run.split())))
    used = set()
    for node in traces:
        ident = node.attrs["data-nk-src"]
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident not in entries:
            findings.append(("N02", "error", "Unknown or invalid data-nk-src: " + str(ident)))
            continue
        used.add(ident)
        entry = entries[ident]
        value = " ".join("".join(text[node]).split())
        if isinstance(entry, dict) and entry.get("live") is not True and "value" in entry and entry["value"] != value:
            findings.append(("N04", "error", ident + ": element text " + repr(value) + " differs from value"))
    for ident in entries.keys() - used:
        findings.append(("N05", "warning", ident + ": source is unused"))
    if runtime:
        for ident, tag, expected in (("nk-sources-runtime", "script", runtime_js()),
                                     ("nk-sources-style", "style", runtime_css())):
            matches = [node for node in page.nodes if node.attrs.get("id") == ident]
            if (len(matches) != 1 or matches[0].tag != tag or matches[0].text() != expected
                    or (tag == "script" and ("src" in matches[0].attrs
                        or matches[0].attrs.get("type", "").lower() not in ("", "text/javascript", "application/javascript")))):
                findings.append(("N07", "error", ident + ": missing or differs from shared asset"))
    return findings


def _sample_sources():
    return Sources("synthetic-test 1.0", [{"id": "data", "name": "sample.csv", "sha256": "a" * 64}]).add(
        "total", "Total", [{"input": "data", "rows": [1, 2], "rows_total": 3}],
        "computation", "Sum synthetic rows", ["Source accuracy was not checked"], value="42")


def selftest():
    base = _sample_sources().to_dict()
    shell = '<html><head></head><body><main data-nk-scope><span data-nk-src="total">42</span></main></body></html>'
    tests = []

    def broken(name, code, change=None, markup=shell, runtime=True, allow_live=True):
        data = copy.deepcopy(base)
        if change:
            change(data)
        tests.append((name, inject(markup, data, runtime=runtime), code, runtime, allow_live))

    clean = inject(shell, base)
    tests.append(("clean", clean, None, True, True))
    tests.append(("manifest missing", shell, "N01", False, True))
    tests.append(("manifest duplicate", clean.replace('</body>', _manifest_block(base) + '</body>'), "N01", True, True))
    tests.append(("manifest json", clean.replace('"nk_sources": 1', '"nk_sources": ?'), "N01", True, True))
    tests.append(("manifest null", inject(shell, None), "N01", True, True))
    for field, value in (("nk_sources", True), ("generator", ""), ("sources", {}), ("sources", [])):
        broken("manifest " + field, "N01", lambda d, f=field, v=value: d.update({f: v}))
    broken("bad manifest id", "N02", lambda d: d["sources"].update({"bad id": d["sources"]["total"]}))
    broken("unknown element", "N02", markup=shell.replace('src="total"', 'src="absent"'))
    broken("bad element id", "N02", markup=shell.replace('src="total"', 'src="bad id"'))
    broken("page unchecked", "N03", lambda d: d.update(not_checked=[""]))
    for field, value in (("label", ""), ("from", []), ("from", [{}]), ("how", {}),
                         ("how", {"kind": "unknown", "text": "x"}), ("not_checked", [""]),
                         ("from", [{"rows": [0]}]), ("from", [{"rows": list(range(1, 52))}]),
                         ("from", [{"rows_total": -1}]), ("from", [{"cells": ""}]), ("live", "yes")):
        broken("entry " + field, "N03", lambda d, f=field, v=value: d["sources"]["total"].update({f: v}))
    broken("live forbidden", "N03", lambda d: d["sources"]["total"].update(live=True), allow_live=False)
    broken("missing value", "N04", lambda d: d["sources"]["total"].pop("value"))
    broken("different value", "N04", lambda d: d["sources"]["total"].update(value="43"))
    broken("unused entry", "N05", lambda d: d["sources"].update(extra=d["sources"]["total"]))
    broken("untraced digits", "N06", markup=shell.replace(' data-nk-src="total"', ''))
    broken("empty plain", "N06", markup=shell.replace(' data-nk-src="total"', ' data-nk-plain=" "'))
    tests.append(("runtime missing", inject(shell, base, runtime=False), "N07", True, True))
    tests.append(("runtime changed", clean.replace(runtime_js(), runtime_js() + "\n"), "N07", True, True))
    tests.append(("style changed", clean.replace(runtime_css(), runtime_css() + "\n"), "N07", True, True))
    broken("duplicate inputs", "N08", lambda d: d["inputs"].append(d["inputs"][0]))
    broken("bad hash", "N08", lambda d: d["inputs"][0].update(sha256="A" * 64))
    broken("unknown input", "N08", lambda d: d["sources"]["total"]["from"][0].update(input="missing"))
    live = copy.deepcopy(base)
    live["sources"]["total"].update(live=True)
    del live["sources"]["total"]["value"]
    tests.append(("live", inject(shell, live), None, True, True))
    tests.append(("manifest only", inject(shell, base, runtime=False), None, False, True))
    edge = copy.deepcopy(base)
    edge["sources"]["total"]["value"] = "4 & 2"
    markup = "<HTML><HEAD></HEAD><BODY><main DATA-NK-SCOPE><SPAN title='99' DATA-NK-SRC='total'>4 &amp;<br>2</SPAN><b data-nk-plain='year'>2025</b><template>999</template><script>var n=99;</script><style>.x{width:99px}</style></main></BODY></HTML>"
    tests.append(("parser edges", inject(markup, edge), None, True, True))
    nested = copy.deepcopy(base)
    nested["sources"]["inner"] = copy.deepcopy(base["sources"]["total"])
    nested["sources"]["inner"]["value"] = "7"
    tests.append(("innermost trace", inject(shell.replace('42</span>', '4<span data-nk-src="inner">7</span>2</span>'), nested), None, True, True))
    passed = 0
    for name, html, code, runtime, allow_live in tests:
        results = check(html, runtime=runtime, allow_live=allow_live)
        ok = any(item[0] == code for item in results) if code else not results
        if ok:
            passed += 1
        else:
            print("FAIL {}: expected {}, got {}".format(name, code or "clean", results))
    # Helper invariants belong here so their failures also turn the control red.
    helpers = []
    helpers.append(("injection idempotence", inject(clean, base) == clean))
    quoted = shell.replace('<head>', '<head><script>var closing = "</head></body>";</script>')
    quoted_page = inject(quoted, base)
    helpers.append(("injection respects script text", not check(quoted_page)
                    and '<script>var closing = "</head></body>";</script>' in quoted_page))
    escaped = _sample_sources()
    escaped.add("escape", "</script> & >", [{"text": "Synthetic"}], "stated", "x", ["x"], value="1")
    helpers.append(("safe JSON", "</script>" not in escaped.to_json() and "\\u003c" in escaped.to_json()))
    exported = escaped.to_dict()
    exported["sources"].clear()
    helpers.append(("defensive copies", bool(escaped.to_dict()["sources"])))
    for field, kwargs in (("label", {"label": ""}), ("from", {"from_": [{}]}),
                          ("how.kind", {"how_kind": "bad"}), ("not_checked", {"not_checked": []}),
                          ("value", {"value": None}), ("input", {"from_": [{"input": "absent"}]})):
        args = dict(id="x", label="Example", from_=[{"text": "Synthetic"}], how_kind="stated",
                    how_text="Example", not_checked=["Unchecked"], value="1")
        args.update(kwargs)
        try:
            Sources("test 1.0").add(**args)
            ok = False
        except ValueError as error:
            ok = field in str(error)
        helpers.append(("helper rejects " + field, ok))
    for name, ok in helpers:
        if ok:
            passed += 1
        else:
            print("FAIL " + name)
    total = len(tests) + len(helpers)
    print("selftest: {}/{}".format(passed, total))
    return 0 if passed == total else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    commands = parser.add_subparsers(dest="command")
    checker = commands.add_parser("check", help="Check a generated page")
    checker.add_argument("page")
    checker.add_argument("--no-runtime", action="store_true")
    checker.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.command != "check":
        parser.error("choose check or --selftest")
    try:
        html = Path(args.page).read_bytes().decode("utf-8")
        findings = check(html, runtime=not args.no_runtime)
    except (OSError, UnicodeError) as error:
        print("Unable to check page: {}".format(error), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(findings))
    else:
        for code, level, message in findings:
            print("{} {}: {}".format(code, level, message))
    return 1 if any(item[1] == "error" for item in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
