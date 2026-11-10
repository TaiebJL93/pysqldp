# pysqldp

Differential privacy for SQL queries, by query rewriting, in pure Python.

`pysqldp` takes an ordinary analytics query and rewrites it into an
**intrinsically private query**: the rewritten SQL embeds the privacy mechanism
itself — noise, clipping, histogram bin filling — so it can be executed
unchanged on any standard SQL engine. Nothing needs to be installed in the
database, and no trusted query proxy sits in the data path.

This is a Python port of a Scala/Maven library descended from
[Uber's Chorus](https://github.com/uber-archive/sql-differential-privacy)
(`sql-differential-privacy`). The original runs on the JVM and is built on
Apache Calcite; this port runs on [sqlglot](https://github.com/tobymao/sqlglot),
so it installs with `pip`/`uv` and needs no JVM, no Maven, and no Docker.

> **Status: walking skeleton.** The framework, schema layer, relational IR,
> histogram and global-sensitivity analyses, and the clipping + Laplace
> mechanisms for `COUNT`/`SUM`/`AVG` on single-table queries are implemented.
> Joins, elastic sensitivity, percentile mechanisms and the remaining analyses
> are staged next — see [Roadmap](#roadmap).

## Install

```bash
uv sync          # or: pip install -e ".[dev]"
```

Requires Python 3.11+.

## Use

```python
from pysqldp import Schema, rewrite_fixed_pipeline

db = Schema.load("tests/fixtures/schema.yaml").database("experiments")

sql, epsilon_spent = rewrite_fixed_pipeline(
    db,
    """
    SELECT g1, g2, SUM(v1) AS total_v1
    FROM table_b
    WHERE g0 = 'xxx'
    GROUP BY 1, 2
    """,
    epsilon=0.1,
)
```

`sql` is the private query, ready to run against the database. `epsilon_spent`
is the privacy budget the query consumes, which the caller is responsible for
deducting from the analyst's remaining budget.

To check the cost without rewriting:

```python
from pysqldp import budget_usage
budget_usage(db, query, epsilon=0.1)
```

From the command line:

```bash
uv run pysqldp --schema tests/fixtures/schema.yaml --database experiments \
    --epsilon 0.1 --query "SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1"
```

## How it works

```
SQL text
  │  sqlglot parse, in the schema's dialect
  ▼
relational IR          Scan / Filter / Project / Aggregate / Join / Sort
  │                    (a small stand-in for Calcite's RelNode)
  ├─► static analyses  histogram shape, taint, stability, sensitivity
  │
  │  rewriters consume the analyses and transform the IR
  ▼
rewritten IR           clipping CASE → bin fill → + scale × Laplace sample
  │  sqlglot generate, in the schema's dialect
  ▼
private SQL
```

The privacy metadata lives in a schema file, not in the query. Column bounds
(`clipLower`/`clipUpper`), join key frequencies (`maxFreq`), domain tables for
histogram bins (`domainSet`) and release permissions (`canRelease`, `isPublic`,
`isTainted`) all come from there. The format is unchanged from the Scala
project, so existing schema files load as-is — see `tests/fixtures/schema.yaml`.

## Mechanisms

| Aggregation | Mechanism | Status |
|---|---|---|
| `COUNT` | PINQ-style stability analysis + Laplace noise | implemented |
| `SUM` | clipping to `[clipLower, clipUpper]` + Laplace noise | implemented |
| `AVG` | decomposed into `SUM`/`COUNT`, budget split in two | implemented |
| histogram bin filling | right join against a `domainSet` table | implemented |
| `VAR` / `STDDEV` | decomposed, budget split in three | roadmap |
| `MIN` / `MAX` / percentile | noisy binned PDF/CDF | roadmap |
| joins | elastic sensitivity, with `maxFreq` truncation | roadmap |

Queries using a construct that has no sound mechanism raise
`UnsupportedQueryException` rather than returning weakly-noised SQL. Emitting a
query with too little noise is a privacy failure, so refusing is the only safe
default.

## Tests

```bash
uv run pytest
```

Three layers:

- **Unit tests** per module — schema parsing, IR round-tripping, each analysis,
  each rewriter.
- **Golden tests** against `tests/golden/*.sql`, the rewritten-SQL outputs
  committed by the Scala project's smoke tests. Comparison is on the parsed
  sqlglot AST, so formatting differences do not cause failures.
- **Executable tests** that build a small synthetic dataset in DuckDB, run the
  rewritten SQL, and check the result is correctly shaped and within a few
  noise standard deviations of the non-private answer.

## Roadmap

1. Joins in the IR, elastic sensitivity analysis and rewriter
2. `maxFreq` truncation: truncating, pretruncated and truncated-elastic variants
3. Percentile mechanisms, including the union and union-max bin-fill routines
4. Mixed histogram/percentile pipeline, `VAR`/`STDDEV`, sign fixing, count casts
5. Sample-and-aggregate, weighted PINQ, restricted sensitivity
6. Remaining analyses: columns-used, join keys, name resolution, arithmetic,
   coverage reporting
7. StatDP statistical validation of each mechanism, then accuracy benchmarks

## License and provenance

See [`LICENSE`](LICENSE) and [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
Read the notices file before redistributing: the upstream Chorus code is MIT,
but some mechanisms in the Scala original this port follows are not, and that
governs what may be published.
