# Known Issue 1

**`SUM`**

We added a new `GlobalSensitivityRewriter` that can support SUM aggregations, with the broader category of sensitivity
rewriters able to support multiple columns in `GROUP BY`.
Supporting this, we also added a new `ClippingRewriter` for automatically inserting the bounds checks used in the
sensitivity analysis.

# Known Issue 2

**`AVG`**

We added a new `testAvg` sample pipeline in `SampleSmokeTest` to demonstrate how to use Calcite's
`AggregateReduceFunctionsRule` to rewrite a query so that it will be suitable for `GlobalSensitivityRewriter` to
rewrite.

# Known Issue 3

**`COUNT`** (with multiple columns in `GROUP BY`)

We enhanced the `addBinsFromDomain` method in `DPUtil` so that it can generate the domain set relation when a histogram
query groups by multiple columns.
We further added functionality to `addBinsFromDomain` to work with a specific environment, where domain
sets are combined into a single table, with a "breakdown" column.

This enhancement also benefit `SUM` and `AVG` histogram queries, which use the same code for generating the domain
relation.

# Known Issue 4

**`PERCENTILE`**

We added a new `CensusPercentileRewriter` that can support `MIN` and `MAX` aggregations.
The mechanism that this rewriter implements works by aggregating data into bins.
We further added functionality to inline the bins into the rewritten query rather than to access them from a table.

# Known Issue 5

**Multiple aggregation functions**

We enhanced the `addBinsFromDomain` method in `DPUtil` so that it can retain multiple aggregation functions.

# Known Issue 6

**Ability to keep subquery unchanged**

We agreed that instead of keeping the subquery in a nested aggregation unchanged, we should have the subquery
changed and keep the outer query unchanged.

To support rewriting only the inner aggregation of a query with nested aggregations, we corrected
`ElasticSensitivityAnalysis` and `SimpleSensitivityAnalysis` to recognize that aggregated values are suitable for
release (e.g., to be used as the outer aggregation's `GROUP BY`), and we enhanced `SensitivityRewriter`
so that it would keep track of relations that already have noise added and would not add noise a second time.
