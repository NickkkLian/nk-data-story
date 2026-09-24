#!/usr/bin/env python3
"""render.py — turn a checked report.json and its data file into one self-contained HTML page: the headline as the
conclusion, every cited number followed by what it was computed on, up to three charts, the next step, and what
the report does not answer. Every number is recomputed from the data here; report.json holds no numbers to show.

    python3 render.py report.json [--data PATH] [--out report.html] [--min-n 30]
    python3 render.py --selftest

It runs report_check first and refuses to render while that finds errors; warnings are printed and listed on the
page. The page inlines ../assets/design-tokens.css (three palettes, light and dark, restored before first paint)
and loads its fonts from Google Fonts when online, falling back to local faces offline.
Exit: 0 written · 1 the report has check errors · 2 unreadable input or usage.
"""
import hashlib, html, json, os, re, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import datafile  # noqa: E402
import report_check  # noqa: E402

TOKENS = os.path.join(HERE, "..", "assets", "design-tokens.css")
SOURCE = "https://github.com/NickkkLian/nk-data-story"
OPNAME = {"==": "=", "!=": "≠", ">": ">", ">=": "≥", "<": "<", "<=": "≤", "in": "in", "not in": "not in"}
MAX_BARS = 12
esc = html.escape


def value_text(fig, r):
    v = r.get("value")
    if v is None:
        return "n/a"
    kind = fig.get("format") or ("percent" if fig.get("measure") in ("share", "change") else
                                 "integer" if fig.get("measure") == "count" else "number")
    if kind == "percent":
        s = f"{v * 100:+.1f}%" if fig.get("measure") == "change" else f"{v * 100:.1f}%"
        s = s.replace("-", "−")
    elif kind == "integer":
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.2f}"
    return f"{fig.get('prefix', '')}{s}{fig.get('suffix', '')}"


def column_text(name):
    base, _, part = (name or "").partition(":")
    return f"{part} of {base}" if part else (name or "")


def where_text(where):
    return ", ".join(f"{column_text(name)} {OPNAME.get(op, op)} {', '.join(map(str, target)) if isinstance(target, list) else target}"
                     for name, op, target in where or [])


def window_text(w):
    return f"{w['from']} → {w['to']}" if w else None


def aperture(fig, r, table):
    """What a number was computed on, in the order a reader asks: what, how many, when, which rows, out of what."""
    parts = [fig.get("label", "")]
    n = f"n {r['n']:,} {r['unit_of_n']}"
    if r.get("skipped"):
        n += f" ({r['skipped']:,} skipped: missing value)"
    parts.append(n)
    if fig.get("measure") == "change":
        parts.append(f"{window_text(fig['from_window'])} vs {window_text(fig['window'])}")
    elif fig.get("window"):
        parts.append(window_text(fig["window"]))
    else:
        dated = [c for c in table.header if table.kinds.get(c) == "date"]
        if dated:
            lo, hi = datafile.date_range(table, dated[0])
            parts.append(f"every date in the file ({lo} → {hi})")
    if fig.get("where"):
        parts.append("where " + where_text(fig["where"]))
    if fig.get("measure") == "share":
        den = (fig.get("denominator") or {}).get("where")
        parts.append(("out of rows where " + where_text(den)) if den else "out of all rows")
        if fig.get("of") == "sum":
            parts.append(f"share of the sum of {fig.get('column')}")
    if fig.get("level", "row") != "row":
        parts.append(f"{fig.get('measure')} per {fig['level']}")
    return " · ".join(p for p in parts if p)


def bind(text, figs, results, table, cited):
    """Replace {fig:id} with the computed value; remember which figures a sentence cited."""
    out, last = [], 0
    for m in report_check.FIG.finditer(text):
        out.append(esc(text[last:m.start()]))
        fid = m.group(1)
        cited.append(fid)
        out.append(f'<b class="fig" title="{esc(aperture(figs[fid], results[fid], table))}">{esc(value_text(figs[fid], results[fid]))}</b>')
        last = m.end()
    out.append(esc(text[last:]))
    return "".join(out)


def apertures_html(fids, figs, results, table):
    seen, items = set(), []
    for fid in fids:
        if fid in seen:
            continue
        seen.add(fid)
        items.append(f'<li><b>{esc(value_text(figs[fid], results[fid]))}</b> {esc(aperture(figs[fid], results[fid], table))}</li>')
    return f'<ul class="aperture">{"".join(items)}</ul>' if items else ""


def chart_svg(chart, fig, r, timeish=False):
    groups = list(r["groups"].items())
    if timeish or chart.get("type") == "line":                 # periods and lines read left to right in time, never by size
        groups.sort(key=lambda kv: kv[0])
    else:
        groups.sort(key=lambda kv: (-(kv[1]["value"] or 0), kv[0]))
    hidden = max(0, len(groups) - MAX_BARS) if chart.get("type") != "line" else 0   # a line keeps every period
    groups = groups[:MAX_BARS] if chart.get("type") != "line" else groups
    vals = [g[1]["value"] or 0 for g in groups]
    top = max(vals) if vals and max(vals) > 0 else 1
    label = lambda v: value_text(fig, {"value": v})
    if chart.get("type") == "line":
        # zero baseline kept (no y-axis to read a cut-off baseline against), so the chart is short rather than tall
        w, h, pad_l, pad_r, pad_t, pad_b = 640, 170, 12, 12, 26, 30
        n = len(groups)
        step = (w - pad_l - pad_r) / max(1, n - 1)
        pts = [(pad_l + i * step, pad_t + (h - pad_t - pad_b) * (1 - (v / top))) for i, v in enumerate(vals)]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        dots = "".join(f'<circle class="dot{" max" if v == top else ""}" cx="{x:.1f}" cy="{y:.1f}" r="4"/>' for (x, y), v in zip(pts, vals))

        def anchor(i):                                   # labels at the two ends grow inward, so nothing is clipped
            return "start" if i == 0 and n > 1 else "end" if i == n - 1 and n > 1 else "middle"
        shown = sorted({0, n - 1, vals.index(top)})
        labels = "".join(f'<text class="val" x="{pts[i][0]:.1f}" y="{pts[i][1] - 10:.1f}" text-anchor="{anchor(i)}">{esc(label(vals[i]))}</text>' for i in shown)
        every = max(1, -(-n // 6))                       # at most about six period labels
        keyed = list(range(0, n, every))
        if keyed[-1] != n - 1:                           # the last period is always labelled; it replaces a neighbour that would touch it
            if (n - 1) - keyed[-1] < every:
                keyed[-1] = n - 1
            else:
                keyed.append(n - 1)
        keys = "".join(f'<text class="key" x="{pts[i][0]:.1f}" y="{h - 10}" text-anchor="{anchor(i)}">{esc(groups[i][0])}</text>' for i in keyed)
        body = (f'<line class="axis" x1="{pad_l}" y1="{h - pad_b}" x2="{w - pad_r}" y2="{h - pad_b}"/>'
                f'<text class="key" x="{pad_l}" y="{h - pad_b - 4}">0</text><polyline class="line" points="{poly}"/>{dots}{labels}{keys}')
    else:
        w, row, key_w, pad_t = 640, 30, 150, 8
        h = pad_t * 2 + row * len(groups)
        bars = []
        for i, ((k, g), v) in enumerate(zip(groups, vals)):
            y = pad_t + i * row
            bw = max(1.0, (w - key_w - 90) * (v / top))
            bars.append(f'<text class="key" x="{key_w - 10}" y="{y + row / 2 + 4:.1f}" text-anchor="end">{esc(k[:22])}</text>'
                        f'<rect class="bar{" max" if v == top else ""}" x="{key_w}" y="{y + 5}" width="{bw:.1f}" height="{row - 10}" rx="2"/>'
                        f'<text class="val" x="{key_w + bw + 8:.1f}" y="{y + row / 2 + 4:.1f}">{esc(label(v))}</text>')
        body = "".join(bars)
    summary = "; ".join(f"{k}: {label(g['value'] or 0)}" for k, g in groups)
    more = f'<p class="more">{hidden} more group(s) not shown; the table below lists all of them.</p>' if hidden else ""
    rows = "".join(f'<tr><td>{esc(k)}</td><td class="num">{esc(label(g["value"] or 0))}</td><td class="num">{g["n"]:,}</td></tr>'
                   for k, g in sorted(r["groups"].items(), key=lambda kv: kv[0]))
    return (f'<figure class="chart"><figcaption><b>{esc(chart.get("title", ""))}</b><span>{esc(chart.get("subtitle", ""))}</span></figcaption>'
            f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(chart.get("title", ""))}: {esc(summary)}">{body}</svg>{more}'
            f'<details><summary>Show the numbers</summary><div class="scroll"><table><thead><tr><th>{esc(column_text(fig.get("by", "")))}</th>'
            f'<th class="num">value</th><th class="num">n</th></tr></thead><tbody>{rows}</tbody></table></div></details></figure>')


CSS = """
@font-face{font-family:"Fraunces Fallback";src:local("Georgia"),local("Times New Roman");size-adjust:93.3%}
@font-face{font-family:"Inter Fallback";src:local("Helvetica Neue"),local("Arial"),local("Segoe UI");size-adjust:106.5%}
@font-face{font-family:"Space Mono Fallback";src:local("Menlo Regular"),local("Menlo-Regular"),local("Consolas"),local("DejaVu Sans Mono");size-adjust:101.7%}
*,*::before,*::after{box-sizing:border-box}
:root{accent-color:var(--accent)}
html{color-scheme:light}
html[data-scheme="dark"]{color-scheme:dark}
@media (prefers-color-scheme: dark){html:not([data-scheme="light"]){color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--text);font:var(--text-md)/var(--leading-relaxed) var(--font-sans)}
body::before{content:"";position:fixed;inset:0;background-image:var(--grain);opacity:var(--grain-opacity);pointer-events:none;z-index:0}
.band{background:var(--band);color:var(--on-band)}
.topbar{position:relative;z-index:2;display:flex;align-items:center;gap:var(--space-3);padding:var(--space-2) var(--gutter);border-bottom:1px solid var(--band-line)}
.topbar .mark{font:600 var(--text-sm)/1 var(--font-mono);letter-spacing:.02em;white-space:nowrap} .topbar .mark b,.topbar .mark svg{color:var(--point)} .topbar .mark svg{vertical-align:-1px}
.topbar .spacer{flex:1}
.pill{font:var(--text-2xs)/1 var(--font-mono);color:var(--on-band-2);border:1px solid var(--band-line);border-radius:999px;padding:5px 9px;white-space:nowrap}
.appearance{position:relative} .appearance summary{cursor:pointer;list-style:none;font:500 var(--text-xs)/1 var(--font-mono);padding:8px 12px;border:1px solid var(--band-line);border-radius:999px;color:var(--on-band)}
.appearance summary::-webkit-details-marker{display:none}
.appearance summary:focus-visible,.fig:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.band .appearance summary:focus-visible{outline-color:var(--on-band)}
.appearance-panel{position:absolute;right:0;top:calc(100% + 8px);background:var(--surface-raised);color:var(--text);border:1px solid var(--border);border-radius:var(--radius-md);box-shadow:var(--shadow-2);padding:var(--space-3);display:grid;gap:var(--space-3);min-width:min(300px,calc(100vw - 32px));z-index:3}
.appearance fieldset{border:0;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:var(--space-2)} .appearance legend{font-size:var(--text-2xs);color:var(--text-2);margin-bottom:6px;width:100%}
.appearance p{margin:0;font-size:var(--text-2xs);color:var(--text-3)}
.pick,.seg{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--text-xs)}
.pick:has(input:checked),.seg:has(input:checked){border-color:var(--accent-text);background:var(--accent-tint)}
.pick input,.seg input{position:absolute;opacity:0;width:1px;height:1px} .pick:has(input:focus-visible),.seg:has(input:focus-visible){outline:2px solid var(--focus);outline-offset:2px}
.swatch{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));width:36px;height:20px;border-radius:4px;overflow:hidden;border:1px solid var(--border)}
.swatch i{display:block} .swatch i:nth-child(1){background:var(--bg)} .swatch i:nth-child(2){background:var(--anchor)} .swatch i:nth-child(3){background:var(--point)}
.plate{position:relative;z-index:1;padding:var(--space-10) var(--gutter) var(--space-8)}
.plate-in{max-width:980px;margin:0 auto}
.eyebrow{font:600 var(--text-2xs)/1.3 var(--font-mono);letter-spacing:var(--tracking-caps);text-transform:uppercase;color:var(--on-band-2);margin:0 0 var(--space-3)}
h1,h2{font-family:var(--font-display);font-weight:var(--display-weight);line-height:var(--leading-tight);margin:0}
h1{font-size:var(--text-4xl);letter-spacing:var(--tracking-display);max-width:22ch}
.plate .fig{color:var(--point);font-weight:inherit}
.plate .aperture{color:var(--on-band-2);border-top:1px solid var(--band-line);margin-top:var(--space-5);padding-top:var(--space-3)}
.plate .aperture b{color:var(--on-band)}
.decision{margin:var(--space-5) 0 0;max-width:var(--measure);color:var(--on-band)} .decision span{display:block;font:600 var(--text-2xs)/1.3 var(--font-mono);letter-spacing:var(--tracking-caps);text-transform:uppercase;color:var(--on-band-2);margin-bottom:4px}
main{position:relative;z-index:1;max-width:calc(980px + 2 * var(--gutter));margin:0 auto;padding:var(--space-8) var(--gutter) var(--space-10);display:grid;gap:var(--space-8)}
h2{font-size:var(--text-2xl);margin-bottom:var(--space-3)}
.evidence p{font-size:var(--text-lg);max-width:var(--measure);margin:0}
.evidence .fig{color:var(--accent-text)}
.aperture{list-style:none;margin:var(--space-2) 0 var(--space-5);padding:0;font:var(--text-xs)/1.5 var(--font-mono);color:var(--text-3)}
.aperture li{margin:2px 0} .aperture b{color:var(--text-2);font-weight:700}
.chart{margin:var(--space-5) 0 0;background:var(--paper);border:1px solid var(--border);border-radius:var(--radius-md);padding:var(--space-4)}
.chart figcaption{display:grid;gap:2px;margin-bottom:var(--space-3)} .chart figcaption b{font-family:var(--font-display);font-size:var(--text-xl);font-weight:var(--display-weight)} .chart figcaption span{font:var(--text-xs)/1.5 var(--font-mono);color:var(--text-3)}
.chart svg{width:100%;height:auto;display:block}
.chart .bar{fill:var(--sage-text)} .chart .bar.max,.chart .dot.max{fill:var(--accent)}
.chart .line{fill:none;stroke:var(--accent);stroke-width:2.5} .chart .dot{fill:var(--sage-text)} .chart .axis{stroke:var(--border-strong)}
.chart .key{font:11px var(--font-sans);fill:var(--text-2)} .chart .val{font:11px var(--font-mono);fill:var(--text)}
.chart .more{font-size:var(--text-xs);color:var(--text-3);margin:var(--space-2) 0 0}
.chart details{margin-top:var(--space-3);font-size:var(--text-sm)} .chart summary{cursor:pointer;color:var(--text-2)}
.next{background:var(--accent-tint);color:var(--accent-tint-text);border-radius:var(--radius-md);padding:var(--space-5)} .next h2{color:inherit} .next p{margin:0;font-size:var(--text-lg);max-width:var(--measure)}
.unanswered ul,.limits ul{margin:0;padding-left:1.2em;max-width:var(--measure)} .unanswered li,.limits li{margin:6px 0}
.unanswered{border-left:3px solid var(--point);padding-left:var(--space-4)}
table{border-collapse:collapse;width:100%;background:var(--paper);font-size:var(--text-sm)}
th,td{text-align:left;padding:var(--space-2) var(--space-3);border-top:1px solid var(--border);vertical-align:top}
th{background:var(--surface-2);color:var(--text-2);font-size:var(--text-xs);border-top:0} td.num,th.num{text-align:right;font-family:var(--font-mono);font-variant-numeric:tabular-nums;white-space:nowrap}
td.mono{font-family:var(--font-mono);font-size:var(--text-xs)}
.scroll{overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius-md)}
.checks li{font:var(--text-xs)/1.5 var(--font-mono)} .checks .warn{color:var(--warning-tint-text)}
.checks .warn::before{content:"";display:inline-block;width:.9em;height:.9em;margin-right:.4em;vertical-align:-.1em;background:currentColor;-webkit-mask:var(--glyph) center/contain no-repeat;mask:var(--glyph) center/contain no-repeat;--glyph:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M6 1.6 11 10.4H1z' fill='none' stroke='black' stroke-width='1.3' stroke-linejoin='round'/%3E%3Cpath d='M6 4.8v2.6' stroke='black' stroke-width='1.3' stroke-linecap='round'/%3E%3Ccircle cx='6' cy='8.9' r='.7'/%3E%3C/svg%3E")}
footer{position:relative;z-index:1;padding:var(--space-6) var(--gutter) var(--space-10);font-size:var(--text-xs)}
footer .cols{max-width:980px;margin:0 auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:var(--space-5)}
footer h3{font:600 var(--text-2xs)/1.3 var(--font-mono);letter-spacing:var(--tracking-caps);text-transform:uppercase;color:var(--on-band-2);margin:0 0 var(--space-2)}
footer p{margin:0;color:var(--on-band)} footer a{color:var(--on-band)} footer code{font-family:var(--font-mono);word-break:break-all}
@media (prefers-reduced-motion: reduce){*{transition-duration:1ms!important;animation-duration:1ms!important}}
"""

BOOT = """<script>
/* appearance contract (nl-theme / nl-scheme): plaster (shown as Water lilies) and System are the defaults and write no attribute */
(function () {
  var d = document.documentElement, q = new URLSearchParams(location.search), t, s;
  try { t = q.get('theme') || localStorage.getItem('nl-theme'); s = q.get('scheme') || localStorage.getItem('nl-scheme'); }
  catch (e) { t = q.get('theme'); s = q.get('scheme'); }
  if (t === 'paper' || t === 'ink') d.setAttribute('data-theme', t);
  if (s === 'dark' || s === 'light') d.setAttribute('data-scheme', s);
})();
</script>"""

PICKER = ('<details class="appearance"><summary>Theme</summary><div class="appearance-panel"><fieldset><legend>Palette</legend>'
          '<label class="pick"><input type="radio" name="nl-theme" value="plaster" checked><span class="swatch" aria-hidden="true"><i></i><i></i><i></i></span>Water lilies</label>'
          '<label class="pick"><input type="radio" name="nl-theme" value="paper"><span class="swatch" data-theme="paper" aria-hidden="true"><i></i><i></i><i></i></span>Morning light</label>'
          '<label class="pick"><input type="radio" name="nl-theme" value="ink"><span class="swatch" data-theme="ink" aria-hidden="true"><i></i><i></i><i></i></span>Dusk</label></fieldset>'
          '<fieldset><legend>Appearance</legend><label class="seg"><input type="radio" name="nl-scheme" value="system" checked>System</label>'
          '<label class="seg"><input type="radio" name="nl-scheme" value="light">Light</label><label class="seg"><input type="radio" name="nl-scheme" value="dark">Dark</label></fieldset>'
          '<p>Saved on this device only.</p></div></details>')

TAIL = """<script>
(function () {
  var html = document.documentElement;
  function get() {
    var t = html.getAttribute('data-theme'), s = html.getAttribute('data-scheme');
    return { theme: (t === 'paper' || t === 'ink') ? t : 'plaster', scheme: (s === 'light' || s === 'dark') ? s : 'system' };
  }
  function syncMeta() {
    var bg = getComputedStyle(html).getPropertyValue('--band').trim(), m = document.querySelector('meta[name="theme-color"]');
    if (bg && m) m.setAttribute('content', bg);
  }
  function set(next) {
    var cur = get(), t = next.theme || cur.theme, s = next.scheme || cur.scheme;
    if (t === 'plaster') html.removeAttribute('data-theme'); else html.setAttribute('data-theme', t);
    if (s === 'system') html.removeAttribute('data-scheme'); else html.setAttribute('data-scheme', s);
    try { localStorage.setItem('nl-theme', t); localStorage.setItem('nl-scheme', s); } catch (e) {}
    syncMeta();
  }
  ['nl-theme', 'nl-scheme'].forEach(function (group) {
    document.querySelectorAll('input[name="' + group + '"]').forEach(function (el) {
      var key = group === 'nl-theme' ? 'theme' : 'scheme';
      if (el.value === get()[key]) el.checked = true;
      /* click as well as change: after a ?theme= link the shown radio can already be checked, and choosing it must still save */
      ['change', 'click'].forEach(function (type) {
        el.addEventListener(type, function () { if (el.checked) { var o = {}; o[key] = el.value; set(o); } });
      });
    });
  });
  syncMeta();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', syncMeta);
})();
</script>"""


def build(report, table, sha256, min_n=30, tokens_css=None):
    """Return (html, errors, warnings). html is None when the report has check errors."""
    errs, warns = report_check.check(report, table, sha256, min_n)
    if errs:
        return None, errs, warns
    figs = {f["id"]: f for f in report.get("figures") or []}
    results = {fid: datafile.compute(table, f) for fid, f in figs.items()}
    data = report.get("data") or {}
    cited_head = []
    headline = bind(report.get("headline", ""), figs, results, table, cited_head)
    evidence = []
    for sentence in report.get("evidence") or []:
        cited = []
        evidence.append(f"<p>{bind(sentence, figs, results, table, cited)}</p>{apertures_html(cited, figs, results, table)}")
    def timeish(by):
        return by.endswith((":month", ":week")) or table.kinds.get(by) == "date"
    charts = "".join(chart_svg(dict(c, subtitle=aperture(figs[c["figure"]], results[c["figure"]], table)), figs[c["figure"]], results[c["figure"]],
                               timeish(figs[c["figure"]].get("by", ""))) for c in report.get("charts") or [])
    ledger = "".join(
        f'<tr><td class="mono">{esc(fid)}</td><td>{esc(f.get("label", ""))}</td><td class="num">{esc(value_text(f, results[fid]) if not f.get("by") else "by " + column_text(f["by"]))}</td>'
        f'<td class="num">{results[fid]["n"]:,}</td><td>{esc(aperture(f, results[fid], table))}</td></tr>' for fid, f in figs.items())
    unanswered = "".join(f"<li>{esc(x)}</li>" for x in report.get("does_not_answer") or [] if x.strip())
    limits = "".join(f"<li>{esc(x)}</li>" for x in report.get("limits") or [] if x.strip())
    checks = ("<section class=\"checks\"><h2>Checks</h2><ul>" + "".join(f'<li class="warn">{esc(c)} {esc(m)}</li>' for c, m in warns) + "</ul></section>") if warns else ""
    pill = '<span class="pill">Demo · synthetic data</span>' if data.get("synthetic") else ""
    first_unanswered = next((x for x in report.get("does_not_answer") or [] if x.strip()), "")
    tokens_css = tokens_css if tokens_css is not None else open(TOKENS, encoding="utf-8").read()
    title = re.sub(r"\s+", " ", report_check.FIG.sub(lambda m: value_text(figs[m.group(1)], results[m.group(1)]), report.get("headline", "")))
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(report.get("question", ""))}">
<meta name="theme-color" content="#053333">
{BOOT}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Inter:wght@400;600&family=Space+Mono:wght@400;700&display=swap">
<style>{tokens_css}</style>
<style>{CSS}</style>
</head><body>
<header class="topbar band"><span class="mark"><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg> data story</span>{pill}<span class="spacer"></span>{PICKER}</header>
<section class="plate band" aria-labelledby="headline"><div class="plate-in">
<p class="eyebrow">{esc(report.get("question", ""))}</p>
<h1 id="headline">{headline}</h1>
{apertures_html(cited_head, figs, results, table)}
<p class="decision"><span>Decision this informs</span>{esc(report.get("decision", ""))}</p>
</div></section>
<main>
<section class="evidence"><h2>What the data shows</h2>{"".join(evidence)}{charts}</section>
<section class="next"><h2>Next step</h2><p>{esc(report.get("next_step", ""))}</p></section>
<section class="unanswered"><h2>What this report does not answer</h2><ul>{unanswered}</ul></section>
{f'<section class="limits"><h2>Limits of this data</h2><ul>{limits}</ul></section>' if limits else ""}
<section><h2>How each number was computed</h2><div class="scroll"><table><thead><tr><th>id</th><th>what</th><th class="num">value</th><th class="num">n</th><th>computed on</th></tr></thead><tbody>{ledger}</tbody></table></div></section>
{checks}
</main>
<footer class="band"><div class="cols">
<section><h3>About this data</h3><p>{esc(data.get("file", ""))} · {len(table.rows):,} rows · sha256 <code>{esc(sha256)}</code>. Every number on this page was recomputed from that file when the page was built.</p></section>
<section><h3>Not answered here</h3><p>{esc(first_unanswered)}</p></section>
<section><h3>Source</h3><p><a href="{SOURCE}">github.com/NickkkLian/nk-data-story</a> · MIT</p></section>
</div></footer>
{TAIL}
</body></html>
"""
    return page, errs, warns


def run(report_path, data_path=None, out=None, min_n=30):
    report = json.load(open(report_path, encoding="utf-8"))
    data = report.get("data") or {}
    path = data_path or os.path.join(os.path.dirname(os.path.abspath(report_path)), data.get("file") or "")
    table = datafile.read_table(path, data.get("sheet"))
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    page, errs, warns = build(report, table, sha, min_n)
    if page is not None:
        out = out or os.path.splitext(report_path)[0] + ".html"
        tmp = out + ".tmp"
        open(tmp, "w", encoding="utf-8").write(page)
        os.replace(tmp, out)
    return page, errs, warns, out


# ---------------------------------------------------------------- self-test

def selftest():
    ok, lines = True, []

    def chk(c, label):
        nonlocal ok
        ok &= bool(c)
        lines.append(f"  {'✔' if c else '✘'} {label}")

    try:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shops.csv")
            open(path, "w").write(report_check.SAMPLE)
            sha = hashlib.sha256(report_check.SAMPLE.encode()).hexdigest()
            t = datafile.read_table(path)
            rep = report_check.good_report(sha, len(t.rows))
            page, errs, warns = build(rep, t, sha, tokens_css="/* tokens */")
            chk(page is not None and errs == [], f"control report renders (errors {errs})")
            head = page.split("</head>")[0]
            chk('<html lang="en">' in page and head.index("nl-theme") < head.index("<style>") and "data-theme" not in page.split("<head>")[0],
                "R01 appearance contract: boot script before the first style, no theme attribute on <html>")
            share = datafile.compute(t, rep["figures"][0])
            want = f"{share['value'] * 100:.1f}%"
            h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)
            chk(f'<b class="fig"' in h1 and f">{want}</b>" in h1, f"R02 headline shows the recomputed share {want}")
            chk(f"n {share['n']:,} rows" in page and "2025-01-01 → 2025-03-31" in page and "where shop = South" in page
                and "out of rows where status = paid" in page and "share of the sum of amount" in page,
                "R03 the aperture beside the headline figure: n, window, filter, denominator, what was summed")
            neg = json.loads(json.dumps(rep))
            neg["figures"].append({"id": "south_rows", "label": "South rows, March against February", "measure": "change", "of": "count",
                                   "where": [["shop", "==", "South"]],
                                   "from_window": {"column": "date", "from": "2025-02-01", "to": "2025-02-28"},
                                   "window": {"column": "date", "from": "2025-03-01", "to": "2025-03-31"}})
            neg["evidence"].append("South rows moved {fig:south_rows}.")
            ch = datafile.compute(t, neg["figures"][-1])
            pneg = build(neg, t, sha, tokens_css="")[0]
            chk(ch["before"]["value"] == 10 and ch["after"]["value"] == 9 and ">−10.0%</b>" in pneg
                and "2025-02-01 → 2025-02-28 vs 2025-03-01 → 2025-03-31" in pneg,
                f"R04 a fall from 10 to 9 rows reads −10.0% with a true minus sign, and names both periods")
            svg = re.search(r"<svg viewBox[^>]*>(.*?)</svg>", page, re.S).group(1)
            bars = re.findall(r'<rect class="bar( max)?"', svg)
            months = datafile.compute(t, rep["figures"][1])["groups"]
            chk(len(bars) == len(months) == 3 and bars.count(" max") == 1, f"R05 one bar per month, the largest marked ({len(bars)} bars)")
            keys = re.findall(r'<text class="key"[^>]*>([^<]+)</text>', svg)
            chk(keys == sorted(keys) == ["2025-01", "2025-02", "2025-03"], f"R06 month bars stay in calendar order, not sorted by size: {keys}")
            chk("<h2>What this report does not answer</h2><ul><li>Whether South customers would buy at North instead</li>" in page,
                "R07 the does-not-answer section lists the report's items")
            chk(f"sha256 <code>{sha}</code>" in page and f"{len(t.rows):,} rows" in page, "R08 the footer pins the data: full sha256 and row count")
            ledger = re.search(r"How each number was computed.*?<tbody>(.*?)</tbody>", page, re.S).group(1)
            chk(ledger.count("<tr>") == 3, "R09 the ledger has one row per figure")
            evil = json.loads(json.dumps(rep))
            evil["question"] = "<script>alert('x')</script>"
            page2, e2, _ = build(evil, t, sha, tokens_css="")
            chk(page2 is not None and "<script>alert" not in page2 and "&lt;script&gt;alert" in page2, "R10 report text is HTML-escaped")
            bad = json.loads(json.dumps(rep))
            bad["decision"] = ""
            page3, e3, _ = build(bad, t, sha, tokens_css="")
            chk(page3 is None and [c for c, _ in e3] == ["D05"], f"R11 a report with check errors is not rendered ({[c for c, _ in e3]})")
            small = json.loads(json.dumps(rep))
            small["figures"][0]["window"] = {"column": "date", "from": "2025-01-01", "to": "2025-01-10"}
            page4, _, w4 = build(small, t, sha, tokens_css="")
            chk(page4 is not None and '<li class="warn">D07' in page4 and [c for c, _ in w4] == ["D07"], "R12 check warnings are listed on the page")
            # no emoji on a public page — icons are line SVG. Arrows are punctuation and stay;
            # symbols drawn as icons (checks, crosses, stars, dots, warning signs, circled marks) do not
            pict = re.findall("[\u2295-\u22a1\u2300-\u23ff\u25a0-\u25ff\u2600-\u27bf\u2b00-\u2bff\U0001f000-\U0001faff\ufe0f]", page4 or "")
            chk(page4 is not None and not pict, f"R22 the report page carries no emoji or icon symbols ({''.join(pict)})")
            chk("Demo · synthetic data" not in page, "R13 no Demo marker unless data.synthetic is set")
            syn = json.loads(json.dumps(rep))
            syn["data"]["synthetic"] = True
            chk("Demo · synthetic data" in build(syn, t, sha, tokens_css="")[0], "R14 data.synthetic shows the Demo marker")
            radios = re.findall(r'<input type="radio" name="(nl-theme|nl-scheme)" value="(\w+)"( checked)?>', page)
            names = re.findall(r'</span>([^<]+)</label>', page)
            chk([v for _, v, c in radios if c] == ["plaster", "system"] and len(radios) == 6 and "['change', 'click']" in page
                and names[:3] == ["Water lilies", "Morning light", "Dusk"],
                f"R15 theme picker: Water lilies / Morning light / Dusk (values plaster / paper / ink) and System / Light / Dark, defaults checked, saved on click as well as change ({names[:3]})")
            many = json.loads(json.dumps(rep))
            many["figures"][1]["by"] = "date"
            many["charts"][0]["type"] = "bar"
            page5 = build(many, t, sha, tokens_css="")[0]
            keys5 = re.findall(r'<text class="key"[^>]*>([^<]+)</text>', page5 or "")
            chk(page5 is not None and len(re.findall(r'<rect class="bar', page5)) == MAX_BARS and "more group(s) not shown" in page5
                and keys5 == sorted(keys5) and keys5[0] == "2025-01-01",
                f"R16 more than {MAX_BARS} groups by a date column: the first {MAX_BARS} dates in order, the rest named as not shown ({keys5[:2]}…)")
            cat = json.loads(json.dumps(rep))
            cat["figures"][1]["by"] = "date:weekday"
            keys6 = re.findall(r'<text class="key"[^>]*>([^<]+)</text>', build(cat, t, sha, tokens_css="")[0])
            groups6 = datafile.compute(t, cat["figures"][1])["groups"]
            want6 = sorted(groups6, key=lambda k: (-groups6[k]["value"], k))
            chk(keys6 == want6 and want6 != sorted(want6), f"R18 category bars are sorted largest first, not alphabetically: {keys6}")
            long = json.loads(json.dumps(rep))
            long["figures"][1]["by"] = "date"
            long["charts"][0]["type"] = "line"
            page7 = build(long, t, sha, tokens_css="")[0]
            svg7 = re.search(r"<svg viewBox=\"0 0 (\d+) \d+\"[^>]*>(.*?)</svg>", page7, re.S)
            keys7 = re.findall(r'<text class="key" x="([\d.]+)" y="[\d.]+" text-anchor="(\w+)">([^<]+)</text>', svg7.group(2))
            dates7 = [k for _, _, k in keys7 if k != "0"]
            vals7 = re.findall(r'<text class="val" x="[\d.]+" y="[\d.]+" text-anchor="(\w+)">', svg7.group(2))
            dots7 = len(re.findall(r'<circle class="dot', svg7.group(2)))
            g7 = sorted(datafile.compute(t, long["figures"][1])["groups"])
            chk(dots7 == len(g7) and len(g7) > 12 and len(dates7) <= 7 and dates7[0] == g7[0] and dates7[-1] == g7[-1]
                and [a for _, a, k in keys7 if k != "0"][0] == "start" and [a for _, a, k in keys7 if k != "0"][-1] == "end" and vals7[0] == "start" and vals7[-1] == "end",
                f"R19 a line over {len(g7)} paid days keeps every point ({dots7}), labels at most about six dates plus the last ({dates7}), and grows its end labels inward")
            gaps7 = [float(b[0]) - float(a[0]) for a, b in zip([k for k in keys7 if k[2] != "0"], [k for k in keys7 if k[2] != "0"][1:])]
            months = os.path.join(d, "months.csv")
            open(months, "w").write("date,amount\n" + "".join(f"2025-{m:02d}-15,{100 + m}\n" for m in range(1, 13)))
            tm = datafile.read_table(months)
            shm = hashlib.sha256(open(months, "rb").read()).hexdigest()
            rep12 = {"data": {"file": "months.csv", "sha256": shm, "rows": 12}, "question": "q", "decision": "d", "headline": "Total {fig:total}",
                     "figures": [{"id": "total", "label": "Total", "measure": "sum", "column": "amount", "window": {"column": "date", "from": "2025-01-01", "to": "2025-12-31"}},
                                 {"id": "per_month", "label": "Per month", "measure": "sum", "column": "amount", "by": "date:month", "window": {"column": "date", "from": "2025-01-01", "to": "2025-12-31"}}],
                     "charts": [{"id": "m", "type": "line", "figure": "per_month", "title": "Twelve months"}], "next_step": "n", "does_not_answer": ["x"], "limits": []}
            p12 = build(rep12, tm, shm, tokens_css="")[0]
            k12 = [(float(x), lab) for x, _, lab in re.findall(r'<text class="key" x="([\d.]+)" y="[\d.]+" text-anchor="(\w+)">([^<]+)</text>', p12 or "") if lab != "0"]
            g12 = [b[0] - a[0] for a, b in zip(k12, k12[1:])]
            chk(p12 is not None and k12[0][1] == "2025-01" and k12[-1][1] == "2025-12" and min(g12) >= 100 and min(gaps7) >= 100,
                f"R21 period labels never touch: twelve months give {[lab for _, lab in k12]}, closest gap {min(g12):.0f} units; the long line's closest gap {min(gaps7):.0f}")
            wd = json.loads(json.dumps(rep))
            wd["figures"][0]["where"] = [["date:weekday", "==", "Mon"]]
            chk("where weekday of date = Mon" in build(wd, t, sha, tokens_css="")[0], "R20 a derived date key reads as words in the notes: weekday of date = Mon")
            rp = os.path.join(d, "report.json")
            json.dump(rep, open(rp, "w"))
            _, e6, _, out = run(rp)
            chk(e6 == [] and os.path.isfile(out) and open(out, encoding="utf-8").read().startswith("<!doctype html>"), "R17 run() writes report.html next to report.json")
    except Exception as e:
        chk(False, f"self-test stopped early: {type(e).__name__}: {e}")
    return ok, lines


def main(argv):
    if "--selftest" in argv:
        ok, lines = selftest()
        print(f"render selftest · {sum(l.startswith('  ✔') for l in lines)}/{len(lines)} passed")
        print("\n".join(lines))
        return 0 if ok else 2
    args, opts, i = [], {"--data": None, "--out": None, "--min-n": "30"}, 0
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
        page, errs, warns, out = run(args[0], opts["--data"], opts["--out"], int(opts["--min-n"]))
    except (OSError, ValueError, KeyError) as e:
        print(f"✘ cannot render {args[0]}: {e}")
        return 2
    for code, msg in errs:
        print(f"✘ {code}  {msg}")
    for code, msg in warns:
        print(f"⚠ {code}  {msg}")
    if page is None:
        print(f"{len(errs)} error(s): not rendered; fix report.json and run again")
        return 1
    print(f"written {out} · {len(warns)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
