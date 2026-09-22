# Method — why the procedure asks what it asks

Each rule below was written after a report went wrong in a way its reader could not see. The examples use the
fictional bakery in `assets/example/`.

## 1. Name the decision before choosing a number

An analysis that cannot change a decision is not worth doing, however interesting its numbers. Writing the decision
first ("whether to keep opening on Mondays in winter") is what picks the figures: Monday's share of winter sales can
change it; the best-selling pastry cannot. A report with no decision tends to become a tour of the columns.

## 2. A number without its n, period and filter is not evidence

Three phrasings were banned from the author's reports because each hid what a reader needs in order to trust or
dispute them: a percentage with no sample size, "growth" with no period, and "the data shows" with no file behind it.
That is why every figure on the page is followed by its n, its window, its filter and, for a share, its whole
(checks D01, D02, D10), and why the footer pins the file by sha256.

## 3. Say where it was measured and at what level

A measurement needs its aperture: which rows, which statistic, under which filter, and at which level of
aggregation. The last one was missed four times before it became a rule. "Average sales on a Monday" can mean the
average sale made on Mondays (level row) or the average Monday's takings (level day); the two answer different
questions and can move in opposite directions. Pick the level that matches the question, and let the page say which
one it is.

## 4. Numbers are computed, never typed

A number typed into prose drifts: the data is refreshed, a filter changes, and the sentence keeps the old value. In
this skill the prose holds references (`{fig:id}`) and the page recomputes every one from the pinned file each time it
is built (check D04). Years, dates and quarter names are allowed because they name a period rather than measure one.

## 5. A result that is too clean is a question

Zero matching rows, a share of exactly 0% or 100%, a grouping that found a single group: each is far more often a
wrong filter or a misread column than a finding. Suspect the tool and the filter before believing the result (D06).
The same goes for the profile: duplicate rows, mixed columns and day/month orders that cannot be settled are read
before any figure is chosen.

## 6. Small samples are flagged, not modelled

A share or an average over a handful of rows or days can swing on one of them. The check warns below 30 (D07); that
threshold is a starting value to tune, not a measured limit, and the skill does no statistics. When a warning stays,
it belongs in `limits` in plain words ("each weekday average rests on about thirteen days").

## 7. Say what the data cannot answer

Every report states at least one question its data cannot settle (D05): usually the cause behind a pattern, or the
cost of the decision it informs. A pattern in sales does not say why customers came or stayed away. Writing it down
keeps the headline from being read as more than it is.

## 8. One page: judgement, evidence, next step

The page has three parts in that order, and no more: what to decide, the few numbers behind it with their apertures,
and the smallest step that would settle it. Anything that does not serve one of the three is cut, which is also why
there are at most three charts.
