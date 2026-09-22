#!/usr/bin/env python3
"""profile.py — describe a CSV or XLSX table so a report can be planned without reading every row: what each column
holds, how much is missing, the range of numbers and dates, the most common values, and what looks wrong.

    python3 profile.py <data.csv|data.xlsx> [--sheet NAME] [--json profile.json] [--top 8]
    python3 profile.py --selftest

The profile is for choosing questions and figures. Its numbers are orientation only: a report cites figures that
render.py recomputes from the data, never numbers copied from here.
Flags: duplicate rows · empty columns · mixed columns (how the cells split) · text that looks like dates with an
unsettled day/month order · columns more than 20% missing · id-like columns (every value distinct).
Exit: 0 profile written · 2 unreadable input or usage.
"""
import hashlib, json, os, statistics, sys, tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datafile  # noqa: E402


def quantiles(vals):
    if len(vals) < 2:
        return {"p25": vals[0], "median": vals[0], "p75": vals[0]} if vals else {}
    q = statistics.quantiles(vals, n=4, method="inclusive")
    return {"p25": q[0], "median": q[1], "p75": q[2]}


def profile(path, sheet=None, top=8):
    t = datafile.read_table(path, sheet)
    out = {"source": os.path.basename(path), "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
           "rows": len(t.rows), "columns": [], "flags": []}
    seen, dups = set(), 0
    for r in t.rows:
        key = tuple("" if v is None else str(v) for v in r)
        dups += key in seen
        seen.add(key)
    if dups:
        out["flags"].append(f"{dups} duplicate row(s): identical in every column")
    for name in t.header:
        kind, note = t.kinds[name], t.notes[name]
        col = {"name": name, "kind": kind, "missing": note["missing"], "distinct": note.get("distinct", 0)}
        cells = [c for c in t.column(name) if c is not None]
        if kind == "number":
            vals = sorted(v for v in (datafile.parse_number(c) for c in cells) if v is not None)
            col.update({"min": vals[0], "max": vals[-1], **quantiles(vals)})
        elif kind == "date":
            first, last = datafile.date_range(t, name)
            col.update({"first": first.isoformat(), "last": last.isoformat()})
        if kind in ("category", "text", "mixed", "id") and cells:
            counts = {}
            for c in cells:
                counts[str(c).strip()] = counts.get(str(c).strip(), 0) + 1
            col["top"] = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        if kind == "empty":
            out["flags"].append(f"column {name!r} is empty")
        if kind == "mixed":
            out["flags"].append(f"column {name!r} is mixed: {note['split']}")
            col["split"] = note["split"]
        if "ambiguous_dates" in note:
            out["flags"].append(f"column {name!r} {note['ambiguous_dates']}")
        if t.rows and note["missing"] / len(t.rows) > 0.2 and kind != "empty":
            out["flags"].append(f"column {name!r} is {note['missing'] / len(t.rows):.0%} missing ({note['missing']} of {len(t.rows)})")
        if kind == "id":
            out["flags"].append(f"column {name!r} looks like an id (every value distinct): count it, do not sum or group by it")
        out["columns"].append(col)
    return out


def text(p):
    lines = [f"{p['source']} · {p['rows']} rows · sha256 {p['sha256'][:12]}…"]
    for c in p["columns"]:
        extra = ""
        if c["kind"] == "number":
            extra = f"min {c['min']:g} · median {c['median']:g} · max {c['max']:g}"
        elif c["kind"] == "date":
            extra = f"{c['first']} → {c['last']}"
        elif c.get("top"):
            extra = ", ".join(f"{v} ({n})" for v, n in c["top"][:4])
        lines.append(f"  {c['name']:<20} {c['kind']:<9} missing {c['missing']:<5} distinct {c['distinct']:<6} {extra}")
    lines += [f"  ⚠ {f}" for f in p["flags"]] or ["  no flags"]
    return "\n".join(lines)


SAMPLE = """date,shop,amount,note,ref,blank
2025-03-01,North,10.50,,r1,
2025-03-01,North,10.50,,r1,
2025-03-02,South,n/a,late,r3,
2025-03-03,South,7,,r4,
2025-03-04,North,12,,r5,
"""


def selftest():
    ok, lines = True, []

    def chk(c, label):
        nonlocal ok
        ok &= bool(c)
        lines.append(f"  {'✔' if c else '✘'} {label}")

    try:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shops.csv")
            open(path, "w").write(SAMPLE)
            p = profile(path)
            cols = {c["name"]: c for c in p["columns"]}
            chk(p["rows"] == 5 and p["sha256"] == hashlib.sha256(SAMPLE.encode()).hexdigest(), "rows counted and the file's sha256 recorded")
            chk(any("1 duplicate row" in f for f in p["flags"]), f"the repeated first row is flagged as a duplicate: {p['flags']}")
            chk(any("'blank' is empty" in f for f in p["flags"]), "an empty column is flagged")
            chk(cols["amount"]["kind"] == "mixed" and any("'amount' is mixed" in f for f in p["flags"]), "a number column with an 'n/a' cell is mixed and flagged")
            chk(any("'note' is 80% missing" in f for f in p["flags"]), f"a column more than 20% missing is flagged with its share: {p['flags']}")
            chk(cols["date"]["first"] == "2025-03-01" and cols["date"]["last"] == "2025-03-04", "date range reported")
            chk(cols["shop"]["top"][0] == ("North", 3), f"top values sorted by count: {cols['shop'].get('top')}")
            num = os.path.join(d, "num.csv")
            open(num, "w").write("x\n1\n2\n3\n4\n")
            q = {c["name"]: c for c in profile(num)["columns"]}["x"]
            chk(q["min"] == 1 and q["max"] == 4 and q["median"] == 2.5 and q["p25"] == 1.75 and q["p75"] == 3.25, f"number summary: min, quartiles (inclusive method), max ({q})")
            ids = os.path.join(d, "ids.csv")
            open(ids, "w").write("id\n" + "\n".join(f"u{i:03d}" for i in range(25)) + "\n")
            chk(any("looks like an id" in f for f in profile(ids)["flags"]), "a column of 25 distinct values is flagged as an id")
            amb = os.path.join(d, "amb.csv")
            open(amb, "w").write("when\n03/04/2025\n05/06/2025\n")
            chk(any("no cell settles day/month order" in f for f in profile(amb)["flags"]), "dates with an unsettled day/month order are flagged")
            chk("⚠ 1 duplicate row" in text(p) and "shops.csv · 5 rows" in text(p), "the text summary carries the header line and the flags")
    except Exception as e:
        chk(False, f"self-test stopped early: {type(e).__name__}: {e}")
    return ok, lines


def main(argv):
    if "--selftest" in argv:
        ok, lines = selftest()
        print(f"profile selftest · {sum(l.startswith('  ✔') for l in lines)}/{len(lines)} passed")
        print("\n".join(lines))
        return 0 if ok else 2
    args, opts, i = [], {"--sheet": None, "--json": None, "--top": "8"}, 0
    while i < len(argv):
        if argv[i] in opts and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            args.append(argv[i])
            i += 1
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        p = profile(args[0], opts["--sheet"], int(opts["--top"]))
    except (OSError, ValueError, KeyError) as e:
        print(f"✘ cannot profile {args[0]}: {e}")
        return 2
    print(text(p))
    if opts["--json"]:
        json.dump(p, open(opts["--json"], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"profile written to {opts['--json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
