# Relational evaluation v1 — synthetic regression data

Four tables, 29 source rows:5 customers,9 orders,11 item lines,4 refunds.
All people/transactions are synthetic. This is a public regression fixture,
not an unseen model benchmark or reconstruction of private research data.
The separate four-row installation demo at `deploy/sample.sql` is unchanged.

## Frozen interpretation

- As-of is **2026-02-01T00:00:00Z**. January is the half-open date interval
  `[2026-01-01, 2026-02-01)`. Dates are fixed; never use today's date/clock.
- Only active customers (`active=1`) and completed orders qualify for sales
  and conversion. Net sales use USD only. A cancelled, inactive, previous-day,
  next-month or EUR order must not enter that USD metric.
- Item/refund values are **integer cents**. No FX conversion. Aggregate item
  lines and refund lines independently at order grain before joining them.
  Only refunds strictly before as-of reduce net sales, including refunds of
  earlier qualifying orders. The February2 refund is not yet effective.
- Conversion numerator counts distinct customers with at least one qualifying
  order. Denominator counts all active customers, including no-order customers.
  Overall conversion uses total numerator/total denominator, not the mean of
  regional rates. Percentage, not ratio, rounded to two decimals in SQL.
- `COUNT` on a supported empty set is0. `SUM` for a no-order customer is NULL;
  an absent/zero denominator yields NULL percentage, not zero or infinity.
  A review-rating question is unsupported: no reviews/ratings table exists.
  The support validator control is explicitly authored; no model abstained.
- All reference outputs declare row order. Customer/item pairs require all55
  rows, in `(customer_id,item_id)` order. A50-row preview is incomplete.

## Independently derived reference arithmetic

These values were written from the literal source transactions before candidate
execution; no model/product output supplies a golden.

- Eligible orders are101,102,105,109.101 has1500 gross and300 refunds =>1200;
  102 has2000 gross and no effective refund =>2000;105 has5000 gross and1000
  refund =>4000;109 has1000 and no refund =>1000. North4200, South4000 cents.
- Active North customers1,2,5:2 convert out of3 =>66.67%. Active South
  customer3:1/1 =>100.00%. Total3/4 =>75.00%; macro average83.33 is wrong here.
- Active customer sums:1=>3200 over2 orders;2=>1000 over1;3=>4000 over1;
  5=>NULL over0. Customer4 is inactive.
- January gross at active customers: EUR7000; USD1500+2000+5000+1000=9500.
- West has no customers =>population0/converters0/percentageNULL. There are
  no refunds in `[January26,February1)` =>real refund_count0.
- Five customer IDs crossed with eleven item IDs give55 explicit pairs in
  `cases.json`. These are enumerated from the ID domains, not query output.

Each negative SQL control must execute successfully on the same immutable
fixture and produce a discriminating wrong output/order. Execution errors or
an accidentally equal result fail the harness; they never count as rejection.
Reports retain the actual SQL, complete rows and rejection reason.

## Numeric and answer policy

Column names bind values to entities; complete rows and multiplicity matter.
Wire metadata, exact row_count and `truncated=false` are required. Column
reordering is accepted only through correct names/association. Row order is
required only when explicitly requested; unordered comparisons preserve
multiplicity through one-to-one matching, including opted-in absolute tolerance.

Numbers accept finite JSON numbers or decimal numeric strings via Decimal;
booleans never count as numbers. Integers must be integral, text stays text,
NULL is accepted only where declared, booleans require actual boolean values.
Default tolerance is zero; no relative tolerance. Decimal scale defaults to
exact (extra nonzero precision is rejected). Optional half-even rounding and
absolute tolerance are explicit per-column policies tested independently; v1
reference percentages are already rounded and use exact scale2/tolerance0.
Money in v1 uses exact integer cents. The existing demo uses exact USD decimals
at scale2. Units come from these case definitions; explicit conflicting wire
units are rejected. Missing wire unit metadata does not independently prove
the SQL's units—reference arithmetic/filters provide that fixture-specific check.

The existing demo's natural-language checker is deliberately narrow: one North
and one South amount, correct association, no negation/extra numbers/units.
Bare amounts inherit USD from the demo question/context; explicit cents, other
currency, percentages or scaling are rejected. Simple Markdown rows/emphasis
and short English amount statements are recognized. Correct prose with another
format, additional valid facts or a grand total can be rejected as **evaluator
unsupported format requiring manual review**. This is not proof a model is
factually wrong, nor a general natural-language semantic judge.

## Identity, leakage and scope

`manifest.json` pins all fixture/reference/rule/expected-output bytes plus the
canonical initialized content hash (tables sorted by primary key; dates ISO;
compact JSON with sorted table names). PostgreSQL and SQLite must match that
content fingerprint and the independently authored complete expected rows.
v1 is immutable after acceptance; new meanings/data belong in a new version.

No fixture/reference/expected-output file is used by application prompts,
retrieval, few-shot examples or the existing model smoke request. This harness
has no provider runner. If a later held-out model evaluation is approved,
construct inputs from schema/questions/approved rules only; withhold reference
SQL, goldens and prior answers/memory, and label this public regression fixture
as seen rather than claiming unseen generalization. CI/comparator passes do
not upgrade historical research verdicts, choose models, prove API/UI behavior,
or establish arbitrary SQL semantic equivalence. SQLite is a local check;
the isolated PostgreSQL job is required for PostgreSQL execution evidence.
