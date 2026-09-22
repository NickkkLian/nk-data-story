---
name: nk-data-story
description: Turn a CSV or Excel file into a one-page data report whose headline is the conclusion and where every figure states its denominator, window and filter. The agent profiles the table, then writes report.json - the decision the report serves, figures defined as computations (count, sum, mean, median, share, change, over filters, date windows, groups and per-day, week or month levels), up to three charts, a next step and what the data cannot answer. scripts/report_check.py refuses typed numbers in the prose, shares without a denominator, changes without two periods, a missing decision and data that does not match its pinned sha256; scripts/render.py recomputes every number from the file into a single HTML page in three palettes, light and dark. Standard library only; the data never leaves the machine. Use when someone hands over a spreadsheet and asks what it says, or needs a one-page summary they can share. Not a dashboard and not a statistics package.
license: MIT
metadata:
  provenance: the author's own analysis reviews and data-analysis rules (2026), written after reports that quoted percentages without a sample size and growth without a window; the XLSX reader is ported from the author's MIT-licensed bill-categoriser; see Provenance
---

# Data story

A spreadsheet becomes one page a person can act on: the headline says what the data shows, every number on the page
is recomputed from the file and followed by what it was computed on, and the page ends with what the data cannot
answer. The agent never types a number into the report. It defines each number as a computation, and the scripts do
the arithmetic, check the plan, and render the page.

> **Paths.** Commands in this skill start with `${…SKILL_DIR}`: this skill's own folder, the one that contains this SKILL.md. Claude Code fills it in. If your agent shows the placeholder as written (Codex, Cursor, Gemini CLI and others), replace it with that folder's absolute path before you run the command. Left as it is, it expands to nothing and the path breaks.

## When this applies

- Someone shares a CSV or an Excel export (sales, bookings, tickets, survey answers) and asks what it says.
- A summary has to go to a person who will decide something, and they need to trust the numbers without the file.
- A chart or a figure is being passed around without the sample size, the period or the filter behind it.
- Not for live dashboards, statistical inference (no tests, no confidence intervals), or data that cannot leave a
  controlled system: the scripts run locally, but the report you share contains the figures.

## Procedure

Write everything into `report.json` (fields in [references/schema.md](references/schema.md); a complete example with
its data is `assets/example/report.json` and `assets/example/bakery-2025.csv`).

1. **Profile before reading.** `python3 ${CLAUDE_SKILL_DIR}/scripts/profile.py data.csv --json profile.json`. Read
   the flags first: duplicate rows, mixed columns, dates whose day/month order is not settled, columns mostly missing.
   Work from the profile; do not paste the raw rows into the conversation, and do not copy numbers from the profile
   into the report.
2. **Name the decision.** Write in `decision` which decision this report can change ("whether to keep opening on
   Mondays in winter"). If no decision comes to mind, stop and ask: an analysis that cannot change a decision is not
   worth a page.
3. **Choose two to four figures that could change it.** Each is a computation, not a value: a measure over rows
   filtered by `where`, inside a date `window`, optionally grouped `by` a column, at a `level` (row, day, week,
   month). Every share names its whole in `denominator`; every change names both periods (`from_window`, `window`);
   the level matches the question (an average day is per day, not per sale). Pin the file in `data`: name, sha256,
   row count.
4. **Write the prose with numbers only as references.** `headline` (the judgement, citing at least one figure as
   `{fig:id}`), `evidence` sentences, `next_step` (the smallest experiment that would settle it), `does_not_answer`
   (at least one question this data cannot settle), `limits` (what is wrong or thin in the data). Years, dates, Q1–Q4
   and H1/H2 may be written; every other number enters as `{fig:id}`.
5. **At most three charts.** A bar for categories (sorted largest first), a line for periods (in time order). The
   title says what the reader should see, not what the chart contains.
6. **Check.** `python3 ${CLAUDE_SKILL_DIR}/scripts/report_check.py report.json` exits 0 only without errors. Read
   the warnings as questions: a share of exactly 0% or 100% usually means a wrong filter; a small group is either
   worth a sentence in `limits` or a wider window.
7. **Render and look at it.** `python3 ${CLAUDE_SKILL_DIR}/scripts/render.py report.json --out report.html` refuses
   while the check has errors. Open the page: a check cannot see a crowded chart or a headline that overstates.
8. **Share the page, not retyped numbers.** The footer pins the file name, its sha256 and the row count, so anyone
   holding the file can recompute every figure.

## Checks (`report_check.py`)

| Code | Level | What it refuses or flags |
|---|---|---|
| D01 | error | a share without a denominator |
| D02 | error / warning | a change without both periods · a figure with no window on a table that has dates |
| D03 | error | a figure without a label saying what was counted |
| D04 | error | a typed number in the prose, or a headline that cites no figure |
| D05 | error | no decision, or nothing under does_not_answer |
| D06 | error / warning | a figure that matched no rows · a share of exactly 0% or 100%, a grouping with one group |
| D07 | warning | a share, mean or median (or one of its groups) on fewer than `--min-n` rows or periods (30 by default, a starting value) |
| D08 | error | an unknown figure id, column, operator, measure or window; prose citing a grouped figure; an id used twice |
| D09 | error | more than three charts, an untitled chart, a chart type other than bar or line, a chart of a figure with no `by` |
| D10 | error | a report whose pinned file name, sha256 or row count does not match the data |

Every check was broken on purpose and the self-test went red for each one — 26 mutations in this checker, 19 in the
reader, 10 in the profiler, 22 in the renderer, none missed; in the checker and the reader the first run found rules
with no sample of their own (5 and 13), and those samples were added. Run them yourself:
`python3 ${CLAUDE_SKILL_DIR}/scripts/report_check.py --selftest`, and the same with
`${CLAUDE_SKILL_DIR}/scripts/profile.py`, `${CLAUDE_SKILL_DIR}/scripts/render.py` and
`${CLAUDE_SKILL_DIR}/scripts/datafile.py` (the shared reader and calculator the other three import).

## Boundaries

- Reads CSV (UTF-8, cp1252 as a fallback; delimiter guessed among comma, semicolon, tab, pipe) and XLSX read-only:
  the value saved in each cell is read, formulas are not recalculated. A workbook that unzips to more than 200 MB, or
  whose XML declares a DOCTYPE, is refused. The whole table is held in memory.
- Numbers with a decimal comma (1.234,56) stay text on purpose: guessing the decimal mark silently changes every
  sum. Dates like 03/04/2025 are read only when another cell in the column settles the day/month order.
- The checks read the plan's structure. A report with zero findings can still answer the wrong question or phrase a
  claim more strongly than its figures allow; the person reading the page is the last check.
- No statistics: small samples are flagged, not modelled, and a change between two periods is not a trend.
- The example data is invented (a fictional bakery, seed 7), and marked as synthetic on its page.

## Provenance

The author's own rules for analyses (2026), each written after a report went wrong in a way the reader could not see:
percentages with no sample size, "growth" with no period, "the data shows" with no file behind it, and a number
measured at the wrong level of aggregation, which happened four times before "say where, what statistic and at what
level" became a rule. The habit of naming the decision first comes from the same reviews: an analysis that cannot
change a decision was cut. The XLSX reader is ported from the author's MIT-licensed bill-categoriser and extended
with date styles, both date systems and the refusals above. No external data or text is included.
