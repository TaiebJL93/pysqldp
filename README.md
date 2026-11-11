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

`docs/` carries the Scala project's written specifications, copied verbatim.
`mechanism_summaries.md` is the normative description of every mechanism and
`schema.md` of every metadata key; the rest cover its test, accuracy and
random-testing reports.

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

## Microsoft Fabric

The rewritten query is ordinary SQL, so Fabric needs no adapter: a notebook
attached to a Lakehouse can run it as it is.

```python
from pysqldp import Schema, rewrite_fixed_pipeline

db = Schema.load("/lakehouse/default/Files/dp/schema.yaml").database("fabric")
sql, epsilon_spent = rewrite_fixed_pipeline(
    db, "SELECT region, SUM(amount) AS total FROM events GROUP BY 1", epsilon=1.0
)
spark.sql(sql).show()
```

- **Install** — either add `pysqldp` to a Fabric Environment's libraries and
  attach the notebook to it, or `%pip install pysqldp` in the first cell.
  Requires Python 3.11+, so Runtime 1.3 (Spark 3.5) or later.
- **Schema** — upload the YAML to the Lakehouse Files area, e.g.
  `Files/dp/schema.yaml`, which the notebook reads at
  `/lakehouse/default/Files/dp/schema.yaml`.
- **`dialect: "spark"` is required**, with `namespace: ""` so table names stay
  unqualified and resolve against the attached Lakehouse. See
  [`tests/fixtures/schema_fabric.yaml`](tests/fixtures/schema_fabric.yaml).

[`notebooks/fabric_dp_demo.ipynb`](notebooks/fabric_dp_demo.ipynb) is a
runnable version of the above — import it with Fabric's *Import notebook*.

The **Warehouse / SQL analytics endpoint is not supported.** T-SQL's `RAND()`
is a runtime constant per query: one draw is reused for every row, so under bin
filling every histogram bin would get *identical* noise, which an analyst
cancels exactly by subtracting two bins. Spark's `rand()` is drawn per row,
which is what the Laplace mechanism needs, and
[`tests/test_fabric_spark.py`](tests/test_fabric_spark.py) asserts that
difference rather than assuming it. A T-SQL dialect would first need a per-row
random source demonstrated on a live warehouse; Microsoft's T-SQL surface-area
and limitations pages document neither `RAND()` nor the alternatives
(`NEWID()`, `CRYPT_GEN_RANDOM()`, `RANGE` window frames), so it cannot be shown
sound from documentation.

## Tests

```bash
uv run pytest
```

Five layers:

- **Unit tests** per module — schema parsing, IR round-tripping, each analysis,
  each rewriter.
- **Golden tests** against the Scala project's committed SQL. Two oracles:
  `tests/golden/pairs/*/` holds `-orig`/`-rw` query pairs, where the analyst's
  input is known, so both the mechanism *and* the noise scale must match;
  `tests/golden/*.sql` is rewritten-only output, which needs a hand-written
  input query. Comparison is on the parsed sqlglot AST, so formatting
  differences do not cause failures. Every golden is either reproduced or
  listed in a `PENDING` dict naming the mechanism it still needs.
- **Executable tests** that build a small synthetic dataset in DuckDB, run the
  rewritten SQL, and check the result is correctly shaped and within a few
  noise standard deviations of the non-private answer.
- **Spark execution tests** (`tests/test_fabric_spark.py`) that run the emitted
  SQL on a local PySpark session — the engine Microsoft Fabric uses — and check
  that every domain bin is present and that noise differs between bins. A local
  Spark session is slow to start and `pyspark` is a large download, so they are
  deselected by default:

  ```bash
  uv sync --group spark
  uv run --group spark pytest -m spark
  ```

- **Statistical tests** (`tests/test_statdp.py`) that run the emitted SQL
  through [StatDP](https://github.com/cmla-psu/statdp) on DuckDB to detect
  violations of the claimed epsilon. This is the only layer that can catch a
  wrong noise scale — an under-noised query is structurally identical to a
  correct one — so it is the correctness gate for every new mechanism. It is
  slow and needs a dependency that is not on PyPI, so it is deselected by
  default:

  ```bash
  uv sync --group statdp
  uv run --group statdp pytest -m slow
  ```

`tests/data/` holds the Scala project's accuracy and performance *results* —
true per-bin answers, noisy samples, timings, plots. They are the baselines the
accuracy harness is compared against; the databases they were produced from
were never committed, so there are no input rows to load there.

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
