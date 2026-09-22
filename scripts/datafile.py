#!/usr/bin/env python3
"""datafile.py — the shared data layer of the data-story skill: read a CSV or XLSX table with the standard library,
infer what each column holds, and compute the figures a report cites. profile.py, report_check.py and render.py
import it; on its own it only runs its self-test.

    python3 datafile.py --selftest

Reading
  CSV   UTF-8 (a BOM is fine; cp1252 as a fallback), delimiter guessed among , ; tab |, blank lines dropped.
  XLSX  read-only: shared strings, inline strings, numbers, booleans; a number styled as a date becomes a date
        (built-in formats 14–22 and 45–47, or a custom format with d, m or y outside quotes); 1900 and 1904 date
        systems. A workbook whose parts unzip to more than 200 MB, or whose XML declares a DOCTYPE, is refused.
Column kinds  number · date · category · text · id · empty. A column gets a kind when at least 95% of its
        non-empty cells parse as it; otherwise it is "mixed" and the profile says how the cells split.
        Numbers accept a leading currency sign and 1,234.56 grouping; 1.234,56 is left as text on purpose
        (guessing the decimal mark silently changes every sum). Day/month order in 03/04/2025 is taken only
        when some cell in the column settles it; otherwise the column stays text and is flagged ambiguous.
Figures  count · sum · mean · median · share · change, each over rows filtered by `where` and a date `window`,
        optionally grouped `by` a column, at a `level` of row, day, week or month. A share counts rows, or sums a
        column with "of": "sum". A date column can be read as "<column>:month", ":week" or ":weekday" in `by` and
        `where`. Every result carries the n it was computed on and how many rows were skipped for a missing value.
"""
import csv, datetime as dt, io, math, os, posixpath, re, statistics, sys, tempfile, zipfile
from xml.etree import ElementTree as ET

MAX_UNZIPPED = 200 * 1024 * 1024
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DATE_BUILTIN = set(range(14, 23)) | {45, 46, 47}
NUM = re.compile(r"^[+-]?(?:[$€£¥]\s?)?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
ISO = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
DMY = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$")
KINDS = ("number", "date", "category", "text", "id", "empty")


class Table:
    def __init__(self, header, rows, source):
        self.header, self.rows, self.source = header, rows, source
        self.kinds, self.notes = {}, {}

    def column(self, name):
        if name not in self.header:
            raise KeyError(f"no column named {name!r}; columns are {self.header}")
        i = self.header.index(name)
        return [r[i] if i < len(r) else None for r in self.rows]


# ---------------------------------------------------------------- reading

def read_table(path, sheet=None):
    ext = os.path.splitext(path)[1].lower()
    header, rows = (read_xlsx(path, sheet) if ext in (".xlsx", ".xlsm") else read_csv(path))
    header = clean_header(header)
    width = len(header)
    rows = [list(r[:width]) + [None] * (width - len(r)) for r in rows]
    t = Table(header, rows, os.path.basename(path))
    infer(t)
    return t


def clean_header(header):
    out, seen = [], {}
    for i, h in enumerate(header):
        name = (str(h).strip() if h is not None else "") or f"column {i + 1}"
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return out


def read_csv(path):
    raw = open(path, "rb").read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError(f"{os.path.basename(path)} has no rows")
    return rows[0], [[c if c.strip() else None for c in r] for r in rows[1:]]


def _xml(parts, name):
    data = parts[name]
    if b"<!DOCTYPE" in data[:4096].upper():
        raise ValueError(f"{name} declares a DOCTYPE; refused")
    return ET.fromstring(data)


def read_xlsx(path, sheet=None):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_UNZIPPED:
            raise ValueError("workbook unzips to more than 200 MB; refused")
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise ValueError("duplicate member name in workbook")
        parts = {n: z.read(n) for n in names if n.endswith(".xml") or n.endswith(".rels")}
    wb = _xml(parts, "xl/workbook.xml")
    pr = wb.find(f"{NS}workbookPr")
    epoch = dt.datetime(1904, 1, 1) if pr is not None and pr.get("date1904") in ("1", "true") else dt.datetime(1899, 12, 30)
    rels = {r.get("Id"): r.get("Target") for r in _xml(parts, "xl/_rels/workbook.xml.rels")}
    sheets = [(s.get("name"), rels[s.get(RID)]) for s in wb.find(f"{NS}sheets")]
    if not sheets:
        raise ValueError("workbook has no sheets")
    names = [n for n, _ in sheets]
    if sheet is not None and sheet not in names:
        raise ValueError(f"no sheet named {sheet!r}; sheets are {names}")
    target = dict(sheets)[sheet] if sheet else sheets[0][1]
    target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
    strings = []
    if "xl/sharedStrings.xml" in parts:
        strings = ["".join(si.itertext()) for si in _xml(parts, "xl/sharedStrings.xml")]
    date_styles = set()
    if "xl/styles.xml" in parts:
        st = _xml(parts, "xl/styles.xml")
        custom = {}
        fmts = st.find(f"{NS}numFmts")
        for f in (fmts if fmts is not None else []):
            code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", f.get("formatCode", ""))
            custom[int(f.get("numFmtId"))] = bool(re.search(r"[dmy]", code, re.I))
        xfs = st.find(f"{NS}cellXfs")
        for i, xf in enumerate(xfs if xfs is not None else []):
            fid = int(xf.get("numFmtId", "0"))
            if fid in DATE_BUILTIN or custom.get(fid):
                date_styles.add(i)
    grid = []
    for row in _xml(parts, target).find(f"{NS}sheetData"):
        values = []
        for c in row:
            ref = c.get("r")
            col = _col_index(ref) if ref else len(values)
            values.extend([None] * (col + 1 - len(values)))
            kind, v = c.get("t"), c.find(f"{NS}v")
            text = v.text if v is not None else None
            if kind == "s" and text is not None:
                value = strings[int(text)]
            elif kind == "inlineStr":
                node = c.find(f"{NS}is")
                value = "".join(node.itertext()) if node is not None else None
            elif kind == "b" and text is not None:
                value = text == "1"
            elif kind in ("str", "e"):
                value = text
            elif text is not None:
                num = float(text)
                if c.get("s") is not None and int(c.get("s")) in date_styles:
                    value = epoch + dt.timedelta(days=num)
                    value = value.date() if value.time() == dt.time(0) else value
                else:
                    value = int(num) if num.is_integer() else num
            else:
                value = None
            values[col] = value if value != "" else None
        grid.append(values)
    grid = [r for r in grid if any(x is not None for x in r)]
    if not grid:
        raise ValueError("the sheet is empty")
    return grid[0], grid[1:]


def _col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


# ---------------------------------------------------------------- parsing and kinds

def parse_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str) and NUM.match(v.strip()):
        return float(re.sub(r"[,$€£¥\s]", "", v.strip()))
    return None


def parse_date(v, dayfirst=None):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip()
    m = ISO.match(s)
    try:
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = DMY.match(s)
        if m and dayfirst is not None:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return dt.date(y, b, a) if dayfirst else dt.date(y, a, b)
    except ValueError:
        return None
    return None


def _dayfirst(cells):
    first = second = False
    for s in cells:
        m = DMY.match(s.strip()) if isinstance(s, str) else None
        if m:
            first |= int(m.group(1)) > 12
            second |= int(m.group(2)) > 12
    return True if first and not second else False if second and not first else None


def infer(t):
    n = len(t.rows)
    for name in t.header:
        cells = [c for c in t.column(name) if c is not None]
        note = {"non_empty": len(cells), "missing": n - len(cells)}
        if not cells:
            t.kinds[name], t.notes[name] = "empty", note
            continue
        dayfirst = _dayfirst(cells)
        nums = sum(parse_number(c) is not None for c in cells)
        dates = sum(parse_date(c, dayfirst) is not None for c in cells)
        dmy = sum(1 for c in cells if isinstance(c, str) and DMY.match(c.strip()))
        distinct = len({str(c) for c in cells})
        need = 0.95 * len(cells)
        if dates >= need and dates > 0:
            kind = "date"
            note["dayfirst"] = dayfirst
        elif nums >= need:
            kind = "number"
        elif dmy >= need and dayfirst is None:
            kind = "text"
            note["ambiguous_dates"] = "looks like dates, but no cell settles day/month order"
        elif max(nums, dates) >= 0.5 * len(cells):
            kind = "mixed"
            note["split"] = {"number": nums, "date": dates, "other": len(cells) - max(nums, dates)}
        elif distinct == len(cells) and len(cells) >= 20:
            kind = "id"
        elif distinct <= max(2, min(50, len(cells) // 2)):
            kind = "category"
        else:
            kind = "text"
        note["distinct"] = distinct
        t.kinds[name], t.notes[name] = kind, note


# ---------------------------------------------------------------- figures

OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, "in": lambda a, b: a in b, "not in": lambda a, b: a not in b}
MEASURES = ("count", "sum", "mean", "median", "share", "change")
LEVELS = ("row", "day", "week", "month")


DERIVED = ("month", "week", "weekday")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def known(t, name):
    base, _, part = name.partition(":")
    return name in t.header or (part in DERIVED and t.kinds.get(base) == "date")


def _value(t, row, name):
    if name not in t.header and ":" in name:
        base, _, part = name.partition(":")
        d = _value(t, row, base)
        if d is None:
            return None
        return d.strftime("%Y-%m") if part == "month" else (d - dt.timedelta(days=d.weekday())).isoformat() if part == "week" else WEEKDAYS[d.weekday()]
    i = t.header.index(name)
    v = row[i]
    kind = t.kinds.get(name)
    if kind == "number":
        return parse_number(v)
    if kind == "date":
        return parse_date(v, t.notes[name].get("dayfirst"))
    return v if v is None else str(v).strip()


def _match(t, row, where):
    for name, op, target in where or []:
        v = _value(t, row, name)
        if v is None:
            return False
        if t.kinds.get(name) == "number":
            target = [parse_number(x) for x in target] if op in ("in", "not in") else parse_number(target)
        elif t.kinds.get(name) == "date":
            target = [parse_date(x) for x in target] if op in ("in", "not in") else parse_date(target)
        if not OPS[op](v, target):
            return False
    return True


def select(t, where=None, window=None):
    """Rows matching `where` and inside `window` ({"column", "from", "to"}, both ends inclusive)."""
    out = []
    lo = parse_date(window["from"]) if window else None
    hi = parse_date(window["to"]) if window else None
    for row in t.rows:
        if not _match(t, row, where):
            continue
        if window:
            d = _value(t, row, window["column"])
            if d is None or d < lo or d > hi:
                continue
        out.append(row)
    return out


def _bucket(d, level):
    if level == "day":
        return d
    if level == "week":
        return d - dt.timedelta(days=d.weekday())
    return d.replace(day=1)


def _aggregate(t, rows, measure, column, level, window):
    """One number for `rows`; returns (value, n, skipped)."""
    if measure == "count" and level == "row":
        return float(len(rows)), len(rows), 0
    if level == "row":
        vals = [_value(t, r, column) for r in rows]
        got = [v for v in vals if v is not None]
        skipped = len(vals) - len(got)
        if not got:
            return None, 0, skipped
        fn = {"sum": sum, "mean": statistics.fmean, "median": statistics.median}[measure]
        return float(fn(got)), len(got), skipped
    buckets, skipped = {}, 0
    for r in rows:
        d = _value(t, r, window["column"])
        v = 1.0 if measure == "count" else _value(t, r, column)
        if d is None or v is None:
            skipped += 1
            continue
        buckets.setdefault(_bucket(d, level), []).append(v)
    per = [sum(vs) for vs in buckets.values()]
    if not per:
        return None, 0, skipped
    if measure in ("count", "sum"):
        return float(sum(per)), len(per), skipped
    fn = {"mean": statistics.fmean, "median": statistics.median}[measure]
    return float(fn(per)), len(per), skipped


def compute(t, fig):
    """Evaluate one figure spec. Returns {"value", "n", "skipped", "unit_of_n", "groups"?, ...}; raises ValueError on a bad spec."""
    measure, level = fig.get("measure"), fig.get("level", "row")
    if measure not in MEASURES:
        raise ValueError(f"{fig.get('id')}: measure must be one of {MEASURES}")
    if level not in LEVELS:
        raise ValueError(f"{fig.get('id')}: level must be one of {LEVELS}")
    wheres = (fig.get("where") or []) + ((fig.get("denominator") or {}).get("where") or [])
    windows = [w for w in (fig.get("window"), fig.get("from_window")) if w]
    for name in [w[0] for w in wheres] + [fig.get("column"), fig.get("by")] + [w.get("column") for w in windows]:
        if name is not None and not known(t, name):
            raise ValueError(f"{fig.get('id')}: no column named {name!r}")
    for w in windows:
        if t.kinds.get(w.get("column")) != "date":
            raise ValueError(f"{fig.get('id')}: window column {w.get('column')!r} is not a date column")
        if parse_date(w.get("from")) is None or parse_date(w.get("to")) is None:
            raise ValueError(f"{fig.get('id')}: window needs from and to as YYYY-MM-DD, got {w.get('from')!r} to {w.get('to')!r}")
    for name, op, target in wheres:
        if op not in OPS:
            raise ValueError(f"{fig.get('id')}: operator {op!r} is not one of {list(OPS)}")
        kind = t.kinds.get(name)
        targets = target if op in ("in", "not in") else [target]
        parse = parse_number if kind == "number" else parse_date if kind == "date" else None
        if parse and any(parse(x) is None for x in targets):
            raise ValueError(f"{fig.get('id')}: {target!r} is not a {kind} for column {name!r}")
    if measure in ("sum", "mean", "median") and (fig.get("column") is None or t.kinds.get(fig.get("column")) != "number"):
        raise ValueError(f"{fig.get('id')}: {measure} needs a number column, got {fig.get('column')!r}")
    if measure == "change" and not (fig.get("window") and fig.get("from_window")):
        raise ValueError(f"{fig.get('id')}: change needs window and from_window")
    if level != "row" and not fig.get("window"):
        raise ValueError(f"{fig.get('id')}: level {level!r} needs a window with a date column")
    unit_of_n = "rows" if level == "row" else f"{level}s"
    if measure == "share":
        whole = select(t, (fig.get("denominator") or {}).get("where"), fig.get("window"))
        part = [r for r in whole if _match(t, r, fig.get("where"))]
        if fig.get("of", "count") == "sum":
            if t.kinds.get(fig.get("column")) != "number":
                raise ValueError(f"{fig.get('id')}: a share of a sum needs a number column, got {fig.get('column')!r}")
            wv = [v for v in (_value(t, r, fig["column"]) for r in whole) if v is not None]
            pv = [v for v in (_value(t, r, fig["column"]) for r in part) if v is not None]
            value = sum(pv) / sum(wv) if wv and sum(wv) else None
            return {"value": value, "n": len(wv), "part": len(pv), "skipped": len(whole) - len(wv), "unit_of_n": "rows"}
        value = len(part) / len(whole) if whole else None
        return {"value": value, "n": len(whole), "part": len(part), "skipped": 0, "unit_of_n": "rows"}
    if measure == "change":
        base = dict(fig, measure=fig.get("of", "sum"), window=fig.get("from_window"))
        now = dict(fig, measure=fig.get("of", "sum"), window=fig.get("window"))
        a, b = compute(t, base), compute(t, now)
        value = (b["value"] - a["value"]) / abs(a["value"]) if a["value"] not in (None, 0) and b["value"] is not None else None
        return {"value": value, "n": min(a["n"], b["n"]), "before": a, "after": b, "skipped": a["skipped"] + b["skipped"], "unit_of_n": a["unit_of_n"]}
    rows = select(t, fig.get("where"), fig.get("window"))
    if fig.get("by"):
        groups = {}
        for r in rows:
            groups.setdefault(_value(t, r, fig["by"]), []).append(r)
        out = {}
        for g, rs in groups.items():
            v, n, sk = _aggregate(t, rs, measure, fig.get("column"), level, fig.get("window"))
            out["(missing)" if g is None else str(g)] = {"value": v, "n": n, "skipped": sk}
        total_n = sum(x["n"] for x in out.values())
        return {"value": None, "groups": out, "n": total_n, "skipped": sum(x["skipped"] for x in out.values()), "unit_of_n": unit_of_n}
    v, n, sk = _aggregate(t, rows, measure, fig.get("column"), level, fig.get("window"))
    return {"value": v, "n": n, "skipped": sk, "unit_of_n": unit_of_n}


def date_range(t, name):
    ds = [d for d in (_value(t, r, name) for r in t.rows) if d is not None]
    return (min(ds), max(ds)) if ds else (None, None)


# ---------------------------------------------------------------- self-test

CSV_SAMPLE = """﻿date;item;amount;status;ref
2025-01-03;bread;"1,204.50";paid;A1
2025-01-03;cake;12.00;paid;A2

2025-01-10;bread;;unpaid;A3
2025-02-01;bread;$30;paid;A4
2025-02-14;cake;7.5;paid;A5
"""


def _xlsx_bytes():
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>amount</t></is></c><c r="C1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" s="1"><v>45658</v></c><c r="B2"><v>3.25</v></c><c r="C2" t="b"><v>1</v></c></row>'
             '<row r="3"><c r="A3" s="2"><v>45689</v></c><c r="C3" t="b"><v>0</v></c></row>'
             '<row r="4"><c r="A4" s="1"><v>45690</v></c><c r="B4" s="3"><v>2.5</v></c></row>'
             '</sheetData></worksheet>')
    styles = ('<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="2"><numFmt numFmtId="164" formatCode="&quot;Day &quot;dd/mm/yyyy"/><numFmt numFmtId="165" formatCode="0.0&quot; days&quot;"/></numFmts>'
              '<cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="165"/></cellXfs></styleSheet>')
    wb = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          '<sheet name="Sales" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    shared = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<si><t>date</t></si><si><r><t>pa</t></r><r><t>id</t></r></si></sst>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in {"xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels, "xl/worksheets/sheet1.xml": sheet,
                           "xl/styles.xml": styles, "xl/sharedStrings.xml": shared}.items():
            z.writestr(name, data)
    return buf.getvalue()


def selftest():
    ok, lines = True, []

    def chk(c, label):
        nonlocal ok
        ok &= bool(c)
        lines.append(f"  {'✔' if c else '✘'} {label}")

    try:
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sales.csv")
            open(p, "w", encoding="utf-8").write(CSV_SAMPLE)
            t = read_table(p)
            chk(t.header == ["date", "item", "amount", "status", "ref"] and len(t.rows) == 5,
                f"CSV: BOM stripped, ';' guessed, blank line dropped ({t.header}, {len(t.rows)} rows)")
            chk(t.kinds["date"] == "date" and t.kinds["amount"] == "number" and t.kinds["item"] == "category",
                f"kinds: date / number / category ({t.kinds})")
            chk(t.notes["amount"]["missing"] == 1, "a missing amount is counted as missing")
            chk(parse_number("1,204.50") == 1204.5 and parse_number("$30") == 30.0 and parse_number("1.204,50") is None,
                "numbers: grouping and a currency sign accepted; 1.204,50 left as text")
            f = compute(t, {"id": "s", "measure": "sum", "column": "amount", "where": [["status", "==", "paid"]]})
            chk(abs(f["value"] - 1254.0) < 1e-9 and f["n"] == 4 and f["skipped"] == 0, f"sum over paid rows = 1254.0, n 4 ({f})")
            f = compute(t, {"id": "m", "measure": "mean", "column": "amount"})
            chk(f["n"] == 4 and f["skipped"] == 1, f"mean skips the missing amount and says so (n {f['n']}, skipped {f['skipped']})")
            f = compute(t, {"id": "sh", "measure": "share", "where": [["status", "==", "paid"]], "denominator": {"where": []}})
            chk(f["value"] == 0.8 and f["n"] == 5 and f["part"] == 4, f"share = 4 of 5 rows ({f})")
            w = {"column": "date", "from": "2025-01-01", "to": "2025-01-31"}
            f = compute(t, {"id": "c", "measure": "count", "window": w})
            chk(f["value"] == 3.0, f"window keeps January only (count {f['value']})")
            f = compute(t, {"id": "d", "measure": "sum", "column": "amount", "level": "month",
                            "window": {"column": "date", "from": "2025-01-01", "to": "2025-02-28"}})
            chk(f["n"] == 2 and abs(f["value"] - 1254.0) < 1e-9, f"level month: n counts months, not rows ({f})")
            f = compute(t, {"id": "ch", "measure": "change", "of": "sum", "column": "amount",
                            "from_window": {"column": "date", "from": "2025-01-01", "to": "2025-01-31"},
                            "window": {"column": "date", "from": "2025-02-01", "to": "2025-02-28"}})
            chk(abs(f["value"] - (37.5 - 1216.5) / 1216.5) < 1e-9, f"change compares two windows ({f['value']:.4f})")
            f = compute(t, {"id": "sd", "measure": "share", "where": [["status", "==", "paid"]], "denominator": {"where": [["item", "==", "bread"]]}})
            chk(f["n"] == 3 and f["part"] == 2 and abs(f["value"] - 2 / 3) < 1e-9, f"share with a filtered denominator: 2 of the 3 bread rows ({f})")
            f = compute(t, {"id": "edge", "measure": "count", "window": {"column": "date", "from": "2025-01-03", "to": "2025-01-10"}})
            chk(f["value"] == 3.0, f"window ends are inclusive: rows on 01-03 and on 01-10 both count ({f['value']})")
            f = compute(t, {"id": "ss", "measure": "share", "of": "sum", "column": "amount", "where": [["item", "==", "cake"]], "denominator": {"where": []}})
            chk(abs(f["value"] - 19.5 / 1254.0) < 1e-9 and f["n"] == 4 and f["skipped"] == 1, f"share of a sum: cake amounts over all amounts, the missing one skipped ({f})")
            f = compute(t, {"id": "bm", "measure": "sum", "column": "amount", "by": "date:month"})
            chk(set(f["groups"]) == {"2025-01", "2025-02"} and abs(f["groups"]["2025-02"]["value"] - 37.5) < 1e-9, f"by date:month groups a date column by month ({sorted(f['groups'])})")
            f = compute(t, {"id": "wd", "measure": "count", "where": [["date:weekday", "==", "Fri"]]})
            chk(f["value"] == 4.0, f"where date:weekday == Fri keeps the four Friday rows: two on 01-03, one each on 01-10 and 02-14 ({f['value']})")
            f = compute(t, {"id": "g", "measure": "count", "by": "item"})
            chk(f["groups"]["bread"]["value"] == 3.0 and f["groups"]["cake"]["value"] == 2.0 and f["n"] == 5, "by: counts per group")
            try:
                compute(t, {"id": "bad", "measure": "sum", "column": "price"})
                chk(False, "an unknown column is refused")
            except ValueError as e:
                chk("no column named 'price'" in str(e), "an unknown column is refused")
            refusals = [
                ({"id": "w", "measure": "count", "window": {"column": "date", "from": "Jan", "to": "2025-01-31"}}, "window needs from and to"),
                ({"id": "v", "measure": "count", "where": [["amount", ">", "lots"]]}, "is not a number"),
                ({"id": "dn", "measure": "share", "where": [], "denominator": {"where": [["shop", "==", "x"]]}}, "no column named 'shop'"),
                ({"id": "tx", "measure": "sum", "column": "item"}, "needs a number column"),
                ({"id": "ms", "measure": "total", "column": "amount"}, "measure must be one of"),
                ({"id": "lv", "measure": "count", "level": "year", "window": {"column": "date", "from": "2025-01-01", "to": "2025-02-28"}}, "level must be one of"),
                ({"id": "wc", "measure": "count", "window": {"column": "item", "from": "2025-01-01", "to": "2025-02-28"}}, "is not a date column"),
                ({"id": "op", "measure": "count", "where": [["item", "~", "bread"]]}, "is not one of"),
                ({"id": "cw", "measure": "change", "of": "sum", "column": "amount", "window": {"column": "date", "from": "2025-02-01", "to": "2025-02-28"}}, "change needs window and from_window"),
                ({"id": "lw", "measure": "sum", "column": "amount", "level": "day"}, "needs a window with a date column"),
                ({"id": "sn", "measure": "share", "of": "sum", "column": "item", "where": [], "denominator": {"where": []}}, "a share of a sum needs a number column"),
            ]
            for bad, needle in refusals:
                try:
                    compute(t, bad)
                    chk(False, f"refused: {needle}")
                except Exception as e:                       # any other exception means the guard is gone: a named red, not a traceback
                    chk(needle in str(e), f"refused: {needle}")
            mixed = os.path.join(d, "mixed.csv")
            open(mixed, "w").write("v\n1\n2\n3\nn/a\n")
            tm = read_table(mixed)
            chk(tm.kinds["v"] == "mixed" and tm.notes["v"]["split"]["number"] == 3, f"75% numbers is mixed, not number (95% rule): {tm.kinds['v']}")
            amb = os.path.join(d, "amb.csv")
            open(amb, "w").write("when,x\n03/04/2025,1\n05/06/2025,2\n")
            ta = read_table(amb)
            chk(ta.kinds["when"] == "text" and "ambiguous_dates" in ta.notes["when"], "03/04/2025 without a settling cell stays text, flagged")
            settled = os.path.join(d, "dmy.csv")
            open(settled, "w").write("when,x\n03/04/2025,1\n25/06/2025,2\n")
            ts = read_table(settled)
            chk(ts.kinds["when"] == "date" and parse_date("03/04/2025", ts.notes["when"]["dayfirst"]) == dt.date(2025, 4, 3),
                "a day above 12 settles day-first for the whole column")
            x = os.path.join(d, "book.xlsx")
            open(x, "wb").write(_xlsx_bytes())
            tx = read_table(x)
            chk(tx.header == ["date", "amount", "paid"] and tx.rows[0][0] == dt.date(2025, 1, 1) and tx.rows[1][0] == dt.date(2025, 2, 1),
                f"XLSX: shared, rich and inline strings; built-in and custom date formats ({tx.header}, {tx.rows})")
            chk(tx.rows[0][2] is True and tx.rows[1][1] is None, "XLSX: booleans read, a missing cell stays empty")
            chk(tx.rows[2][1] == 2.5, f"XLSX: a d inside a quoted format (0.0\" days\") does not make a number a date ({tx.rows[2][1]!r})")
            def refused(fn, needle, label):
                try:
                    fn()
                    chk(False, label)
                except Exception as e:
                    chk(needle in str(e), label)
            refused(lambda: t.column("nope"), "no column named 'nope'", "Table.column refuses an unknown name")
            empty = os.path.join(d, "empty.csv")
            open(empty, "w").write("\n\n")
            refused(lambda: read_table(empty), "has no rows", "a CSV with no rows is refused")
            refused(lambda: read_table(x, sheet="Nope"), "no sheet named 'Nope'", "an unknown sheet name is refused")
            global MAX_UNZIPPED
            keep, MAX_UNZIPPED = MAX_UNZIPPED, 100
            try:
                refused(lambda: read_table(x), "unzips to more than", "an oversized workbook is refused (limit lowered for the test)")
            finally:
                MAX_UNZIPPED = keep
            def book(path, members):
                with zipfile.ZipFile(path, "w") as z:
                    for name, data in members:
                        z.writestr(name, data)
            ws = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{}</sheetData></worksheet>'
            wbx = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets>{}</sheets></workbook>')
            rel = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
            sheet1 = '<sheet name="S" sheetId="1" r:id="rId1"/>'
            nosheets = os.path.join(d, "nosheets.xlsx")
            book(nosheets, [("xl/workbook.xml", wbx.format("")), ("xl/_rels/workbook.xml.rels", rel)])
            refused(lambda: read_table(nosheets), "has no sheets", "a workbook with no sheets is refused")
            blank = os.path.join(d, "blank.xlsx")
            book(blank, [("xl/workbook.xml", wbx.format(sheet1)), ("xl/_rels/workbook.xml.rels", rel), ("xl/worksheets/sheet1.xml", ws.format(""))])
            refused(lambda: read_table(blank), "the sheet is empty", "an empty sheet is refused")
            dup = os.path.join(d, "dup.xlsx")
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                book(dup, [("xl/workbook.xml", wbx.format(sheet1)), ("xl/workbook.xml", wbx.format(sheet1)), ("xl/_rels/workbook.xml.rels", rel)])
            refused(lambda: read_table(dup), "duplicate member name", "a workbook with duplicate member names is refused")
            bomb = os.path.join(d, "bad.xlsx")
            with zipfile.ZipFile(bomb, "w") as z:
                z.writestr("xl/workbook.xml", '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "a">]><workbook/>')
                z.writestr("xl/_rels/workbook.xml.rels", "<Relationships/>")
            refused(lambda: read_table(bomb), "declares a DOCTYPE", "a workbook declaring a DOCTYPE is refused")
    except Exception as e:                           # a break that makes a later step throw is still a named red line
        chk(False, f"self-test stopped early: {type(e).__name__}: {e}")
    return ok, lines


def main(argv):
    if "--selftest" in argv:
        ok, lines = selftest()
        print(f"datafile selftest · {sum(l.startswith('  ✔') for l in lines)}/{len(lines)} passed")
        print("\n".join(lines))
        return 0 if ok else 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
