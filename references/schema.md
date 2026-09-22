# report.json

One JSON object. `scripts/report_check.py` checks it against the data; `scripts/render.py` turns it into the page.
A complete example: `assets/example/report.json` with `assets/example/bakery-2025.csv`.

## Top level

| Field | Required | What it holds |
|---|---|---|
| `data` | yes | the file the report is computed from: `file` (path relative to report.json), `sha256`, `rows`, optional `sheet` (XLSX; default the first sheet), optional `synthetic: true` (the page then shows `Demo · synthetic data`) |
| `question` | no | the question in the reader's words; shown above the headline |
| `decision` | yes | the decision this report can change |
| `headline` | yes | the judgement, one sentence, citing at least one figure as `{fig:id}` |
| `figures` | yes | the numbers, each defined as a computation (below) |
| `evidence` | no | sentences that cite figures as `{fig:id}` |
| `charts` | no | up to three, each drawing one grouped figure (below) |
| `next_step` | no | the smallest experiment or action that would settle the question |
| `does_not_answer` | yes | at least one question this data cannot settle |
| `limits` | no | what is thin or wrong in the data itself |

Prose fields (`headline`, `evidence`, `next_step`, `does_not_answer`, `limits`) may contain years (2025), ISO dates
(2025-10-01), Q1–Q4 and H1/H2. Every other number is a `{fig:id}`, replaced on the page by the computed value.

## A figure

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | unique; letters, digits, `_`, `-` |
| `label` | yes | what was counted, in words ("Mondays' share of paid sales") |
| `measure` | yes | `count` · `sum` · `mean` · `median` · `share` · `change` |
| `column` | for `sum`, `mean`, `median`, and a share of a sum | a number column |
| `where` | no | a list of `[column, operator, value]`, all of which must hold; operators `==` `!=` `>` `>=` `<` `<=`, and `in` / `not in` with a list; values are read as numbers or dates when the column is one |
| `window` | for `change`, and for any `level` other than row | `{"column": <date column>, "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}`, both ends included |
| `by` | no | group by a column, or by part of a date: `date:month` (2025-03), `date:week` (the Monday that starts it), `date:weekday` (Mon … Sun) |
| `level` | no | `row` (default), `day`, `week` or `month`: sums rows into periods first, then measures the periods, so `mean` at `day` is an average day, not an average row |
| `denominator` | for `share` | `{"where": [...]}`: which rows are the whole; `{"where": []}` means every row in the window |
| `of` | no | for `share`: `count` (default) or `sum` (then `column` is summed); for `change`: the measure compared, `sum` by default |
| `from_window` | for `change` | the earlier period; `window` is the later one |
| `format` | no | `percent`, `integer` or `number`; the default follows the measure |
| `prefix`, `suffix` | no | text around the value, such as `$` |

`{fig:id}` in the prose may cite any figure without `by` (the check refuses a grouped one: it has no single value).
A figure with `by` is drawn by a chart and listed in the table of computed numbers.

What the computation reports, and the page prints beside the value:

- `n`: the rows used, or the periods at a `day` / `week` / `month` level. For a share, the rows in the whole (with a
  value, for a share of a sum). For a change, the smaller of the two periods' n.
- skipped: rows left out because the measured column was empty in them.
- the window, the filter and the denominator, as written above.

## A chart

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | unique among charts |
| `type` | yes | `bar` (groups sorted largest first; at most 12 drawn, the rest named) or `line` (periods in time order, every period kept) |
| `figure` | yes | the id of a figure that has `by` |
| `title` | yes | what the reader should see ("A winter Monday sells the least of any day") |

The subtitle under each chart is generated from the figure: what, n, window, filter, level.
