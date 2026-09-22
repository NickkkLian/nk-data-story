#!/usr/bin/env python3
"""report_check.py — check a data-story report spec against its data before anything is rendered: every number
must come from a computed figure, every share must say what the whole is, every change must say which two periods,
and the report must say which decision it serves and what it cannot answer.

    python3 report_check.py report.json [--data PATH] [--min-n 30] [--strict]
    python3 report_check.py --selftest

report.json is described in references/schema.md. The data file is `data.file`, relative to report.json, unless
--data is given.
  D01 error    a share without a denominator (which rows are the whole?)
  D02 error    a change without both windows · warning: a figure with no window on a table that has a date column
  D03 error    a figure without a label saying, in words, what was counted
  D04 error    a typed number in the prose (headline, evidence, next step, does-not-answer, limits): numbers enter
               only as {fig:id}; years, ISO dates, Q1–Q4 and H1/H2 are allowed · error: a headline citing no figure
  D05 error    no decision, or an empty does_not_answer
  D06 error    a figure that matched no rows · warning: a share of exactly 0% or 100%, or a grouping that found one
               group: check the filter before believing it
  D07 warning  a share, mean or median (or one of its groups) computed on fewer than --min-n rows or periods;
               30 is a starting value to tune, not a measured limit
  D08 error    anything the data layer refuses: an unknown {fig:id}, figure id, column, operator, measure or window;
               a {fig:id} in the prose that points at a grouped figure; a figure or chart id used twice
  D09 error    more than 3 charts, a chart without a title, a chart type other than bar or line, or a chart whose
               figure has no `by`
  D10 error    the report does not pin its data: no file, or a sha256 or row count that differs from the file
Exit: 0 no errors (warnings allowed unless --strict) · 1 errors, or warnings with --strict · 2 unreadable input or usage.
"""
import hashlib, json, os, re, sys, tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datafile  # noqa: E402

FIG = re.compile(r"\{fig:([A-Za-z0-9_-]+)\}")
ALLOWED = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b|\bQ[1-4]\b|\bH[12]\b")
TYPED = re.compile(r"\d[\d,.]*%?")


def prose(report):
    items = [("headline", report.get("headline") or ""), ("next_step", report.get("next_step") or "")]
    for key in ("evidence", "does_not_answer", "limits"):
        items += [(f"{key}[{i}]", s or "") for i, s in enumerate(report.get(key) or [])]
    return items


def check(report, table, sha256, min_n=30):
    errs, warns = [], []

    def E(code, msg):
        errs.append((code, msg))

    def W(code, msg):
        warns.append((code, msg))

    data = report.get("data") or {}
    if not data.get("file"):
        E("D10", "data.file is missing: name the file this report was computed from")
    else:
        if data.get("sha256") != sha256:
            E("D10", f"data.sha256 does not match {data['file']} (the file hashes to {sha256[:12]}…)")
        if data.get("rows") != len(table.rows):
            E("D10", f"data.rows says {data.get('rows')!r}, the file has {len(table.rows)} rows")
    if not (report.get("decision") or "").strip():
        E("D05", "no decision: write which decision this report can change, or do not write the report")
    if not [x for x in report.get("does_not_answer") or [] if (x or "").strip()]:
        E("D05", "does_not_answer is empty: name at least one question this data cannot settle")

    figures = report.get("figures") or []
    ids = [f.get("id") for f in figures]
    for fid in sorted({i for i in ids if ids.count(i) > 1}):
        E("D08", f"figure id {fid!r} is used more than once")
    has_date = any(k == "date" for k in table.kinds.values())
    for f in figures:
        fid, measure = f.get("id"), f.get("measure")
        if not (f.get("label") or "").strip():
            E("D03", f"{fid}: no label; say in words what was counted")
        if measure == "share" and "denominator" not in f:
            E("D01", f"{fid}: a share needs a denominator (which rows are the whole?)")
            continue
        if measure == "change" and not (f.get("window") and f.get("from_window")):
            E("D02", f"{fid}: a change needs both periods, window and from_window")
            continue
        if measure != "change" and not f.get("window") and has_date:
            W("D02", f"{fid}: no window, so the figure covers every date in the file")
        try:
            r = datafile.compute(table, f)
        except ValueError as e:
            E("D08", str(e))
            continue
        if r["n"] == 0:
            E("D06", f"{fid}: matched no rows; check the filter and the window before anything else")
            continue
        if measure == "share" and r["value"] in (0.0, 1.0):
            W("D06", f"{fid}: the share is exactly {r['value']:.0%}; check the filter before believing it")
        if f.get("by") and len(r["groups"]) == 1:
            W("D06", f"{fid}: grouping by {f['by']!r} found a single group")
        if measure in ("share", "mean", "median"):
            if r["n"] < min_n and not f.get("by"):
                W("D07", f"{fid}: computed on {r['n']} {r['unit_of_n']}, under {min_n}")
            small = [g for g, x in (r.get("groups") or {}).items() if 0 < x["n"] < min_n]
            if small:
                W("D07", f"{fid}: group(s) {', '.join(map(str, small))} computed on fewer than {min_n} {r['unit_of_n']}")

    grouped = {f.get("id") for f in figures if f.get("by")}
    for where, text in prose(report):
        for m in FIG.finditer(text):
            if m.group(1) not in ids:
                E("D08", f"{where}: {{fig:{m.group(1)}}} is not a figure id")
            elif m.group(1) in grouped:
                E("D08", f"{where}: {{fig:{m.group(1)}}} is grouped by a column, so it has no single value to print; chart it instead")
        typed = TYPED.findall(ALLOWED.sub("", FIG.sub("", text)))
        if typed:
            E("D04", f"{where}: typed number(s) {typed}; cite a computed figure as {{fig:id}} instead")
    if not FIG.search(report.get("headline") or ""):
        E("D04", "the headline cites no figure; a conclusion needs at least one computed number behind it")

    charts = report.get("charts") or []
    cids = [c.get("id") for c in charts]
    for cid in sorted({str(i) for i in cids if cids.count(i) > 1}):
        E("D08", f"chart id {cid!r} is used more than once")
    if len(charts) > 3:
        E("D09", f"{len(charts)} charts; at most 3")
    for c in charts:
        cid = c.get("id")
        if not (c.get("title") or "").strip():
            E("D09", f"chart {cid}: no title; write what the reader should see in it")
        if c.get("type") not in ("bar", "line"):
            E("D09", f"chart {cid}: type must be bar or line, got {c.get('type')!r}")
        f = next((x for x in figures if x.get("id") == c.get("figure")), None)
        if f is None:
            E("D08", f"chart {cid}: figure {c.get('figure')!r} does not exist")
        elif not f.get("by"):
            E("D09", f"chart {cid}: figure {f.get('id')!r} has no `by`, so there is nothing to draw")
    return errs, warns


def run(report_path, data_path=None, min_n=30):
    report = json.load(open(report_path, encoding="utf-8"))
    data = report.get("data") or {}
    path = data_path or os.path.join(os.path.dirname(os.path.abspath(report_path)), data.get("file") or "")
    table = datafile.read_table(path, data.get("sheet"))
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    return check(report, table, sha, min_n)


# ---------------------------------------------------------------- self-test

SAMPLE = "date,shop,amount,status\n" + "".join(
    f"2025-{m:02d}-{d:02d},{'North' if (m + d) % 3 else 'South'},{(m * 7 + d * 3) % 40 + 5}.50,{'paid' if d % 4 else 'refunded'}\n"
    for m in (1, 2, 3) for d in range(1, 29))


def good_report(sha, rows):
    return {
        "data": {"file": "shops.csv", "sha256": sha, "rows": rows},
        "question": "Is the South shop worth its own weekly stock run?",
        "decision": "Whether to keep a separate weekly stock run for the South shop",
        "headline": "South took {fig:south_share} of paid sales in Q1 2025",
        "figures": [
            {"id": "south_share", "label": "South's share of paid sales", "measure": "share", "of": "sum", "column": "amount",
             "where": [["shop", "==", "South"]], "denominator": {"where": [["status", "==", "paid"]]},
             "window": {"column": "date", "from": "2025-01-01", "to": "2025-03-31"}},
            {"id": "sales_by_month", "label": "Paid sales per month", "measure": "sum", "column": "amount", "by": "date:month",
             "where": [["status", "==", "paid"]], "window": {"column": "date", "from": "2025-01-01", "to": "2025-03-31"}},
            {"id": "refund_change", "label": "Refunds, February against January", "measure": "change", "of": "count",
             "where": [["status", "==", "refunded"]],
             "from_window": {"column": "date", "from": "2025-01-01", "to": "2025-01-31"},
             "window": {"column": "date", "from": "2025-02-01", "to": "2025-02-28"}},
        ],
        "evidence": ["Refunds moved {fig:refund_change} from January to February."],
        "charts": [{"id": "c1", "type": "bar", "figure": "sales_by_month", "title": "Paid sales held steady across the quarter"}],
        "next_step": "Run the South stock every other week for a month and compare waste.",
        "does_not_answer": ["Whether South customers would buy at North instead"],
        "limits": ["One quarter only; no holiday season in the window."],
    }


def selftest():
    ok, lines = True, []

    def chk(c, label):
        nonlocal ok
        ok &= bool(c)
        lines.append(f"  {'✔' if c else '✘'} {label}")

    def codes(rep, table, sha, min_n=30):
        e, w = check(rep, table, sha, min_n)
        return sorted({c for c, _ in e}), sorted({c for c, _ in w})

    try:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shops.csv")
            open(path, "w").write(SAMPLE)
            sha = hashlib.sha256(SAMPLE.encode()).hexdigest()
            t = datafile.read_table(path)
            base = good_report(sha, len(t.rows))
            e, w = codes(base, t, sha)
            chk(e == [] and w == [], f"control report → 0 errors, 0 warnings (errors {e}, warnings {w})")

            def mutated(fn):
                rep = json.loads(json.dumps(base))
                fn(rep)
                return rep

            def only_error(code, fn, label):
                e, w = codes(mutated(fn), t, sha)
                chk(e == [code], f"{code} sample → exactly one error code {code}: {label} (got errors {e}, warnings {w})")

            only_error("D01", lambda r: r["figures"][0].pop("denominator"), "a share without a denominator")
            only_error("D02", lambda r: r["figures"][2].pop("from_window"), "a change without its earlier period")
            only_error("D03", lambda r: r["figures"][1].update(label=" "), "a figure without a label")
            only_error("D04", lambda r: r.update(headline="South took {fig:south_share} of paid sales, up 12% on last year"), "a typed 12% in the headline")
            only_error("D04", lambda r: r.update(headline="South shop sales, first quarter"), "a headline citing no figure")
            only_error("D05", lambda r: r.update(decision=""), "no decision")
            only_error("D05", lambda r: r.update(does_not_answer=[" "]), "an empty does_not_answer")
            only_error("D06", lambda r: r["figures"][1]["where"].append(["shop", "==", "East"]), "a filter that matches no rows")
            only_error("D08", lambda r: r.update(evidence=["Refunds moved {fig:refunds} from January to February."]), "an unknown {fig:id}")
            only_error("D08", lambda r: r["figures"][1].update(column="price"), "an unknown column")
            only_error("D09", lambda r: r["charts"][0].update(title=""), "a chart without a title")
            only_error("D09", lambda r: r.update(charts=[dict(r["charts"][0], id=f"c{i}") for i in range(4)]), "four charts")
            only_error("D09", lambda r: r["charts"][0].update(figure="south_share"), "a chart whose figure has no by")
            only_error("D10", lambda r: r["data"].update(sha256="0" * 64), "a sha256 that does not match the file")
            only_error("D10", lambda r: r["data"].update(rows=10), "a row count that does not match the file")
            only_error("D10", lambda r: r["data"].pop("file"), "no data file named")
            only_error("D08", lambda r: r["figures"].append(dict(r["figures"][1])), "a figure id used twice")
            only_error("D08", lambda r: r["charts"][0].update(figure="nope"), "a chart pointing at a figure that does not exist")
            only_error("D08", lambda r: r.update(evidence=["Sales by month were {fig:sales_by_month}."]), "prose citing a grouped figure")
            only_error("D08", lambda r: r["charts"].append(dict(r["charts"][0], title="Again")), "a chart id used twice")
            e, w = codes(mutated(lambda r: r["figures"][1].update(by="shop", where=[["status", "==", "paid"], ["shop", "==", "North"]])), t, sha)
            chk(e == [] and w == ["D06"], f"D06 warning: a grouping that found a single group (errors {e}, warnings {w})")
            e, w = codes(mutated(lambda r: r["figures"].append({"id": "avg_by_month", "label": "Average paid sale per month", "measure": "mean", "column": "amount",
                                                                 "by": "date:month", "where": [["status", "==", "paid"]],
                                                                 "window": {"column": "date", "from": "2025-01-01", "to": "2025-03-31"}})), t, sha)
            chk(e == [] and w == ["D07"], f"D07 warning: a mean whose groups each have fewer than 30 rows (errors {e}, warnings {w})")

            e, w = codes(mutated(lambda r: r["figures"][0].update(where=[["status", "==", "paid"]])), t, sha)
            chk(e == [] and w == ["D06"], f"D06 warning: a share of exactly 100% (errors {e}, warnings {w})")
            _, wl = check(base, t, sha, 100)
            d07 = [m for c, m in wl if c == "D07"]
            chk(len(d07) == 1 and d07[0].startswith("south_share:"), f"D07 at min-n 100 names only the share (n 63), never the sum or the change: {d07}")
            e, w = codes(mutated(lambda r: r["figures"][0].update(where=[["shop", "==", "South"]], window={"column": "date", "from": "2025-01-01", "to": "2025-01-10"})), t, sha)
            chk(e == [] and w == ["D07"], f"D07 warning: a share on fewer than 30 rows (errors {e}, warnings {w})")
            e, w = codes(mutated(lambda r: r["figures"][1].pop("window")), t, sha)
            chk(e == [] and w == ["D02"], f"D02 warning: a figure with no window on a dated table (errors {e}, warnings {w})")
            e, w = codes(mutated(lambda r: r.update(evidence=["Between 2025-01-01 and 2025-02-28, in Q1 and H1, refunds moved {fig:refund_change}."])), t, sha)
            chk(e == [], f"D04 allows ISO dates, years, Q1 and H1 in prose (errors {e})")
            e, w = codes(mutated(lambda r: r["charts"][0].update(type="pie")), t, sha)
            chk(e == ["D09"], f"D09: a pie chart is refused (errors {e})")
            rp = os.path.join(d, "report.json")
            json.dump(base, open(rp, "w"))
            e, w = run(rp)
            chk(e == [] and w == [], "run(): data.file is resolved next to report.json and hashed")
    except Exception as e:
        chk(False, f"self-test stopped early: {type(e).__name__}: {e}")
    return ok, lines


def main(argv):
    if "--selftest" in argv:
        ok, lines = selftest()
        print(f"report_check selftest · {sum(l.startswith('  ✔') for l in lines)}/{len(lines)} passed")
        print("\n".join(lines))
        return 0 if ok else 2
    args, opts, i = [], {"--data": None, "--min-n": "30"}, 0
    while i < len(argv):
        if argv[i] in opts and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
        elif argv[i] == "--strict":
            i += 1
        else:
            args.append(argv[i])
            i += 1
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        errs, warns = run(args[0], opts["--data"], int(opts["--min-n"]))
    except (OSError, ValueError, KeyError) as e:
        print(f"✘ cannot check {args[0]}: {e}")
        return 2
    for code, msg in errs:
        print(f"✘ {code}  {msg}")
    for code, msg in warns:
        print(f"⚠ {code}  {msg}")
    print(f"{len(errs)} error(s), {len(warns)} warning(s)")
    return 1 if errs or ("--strict" in argv and warns) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
