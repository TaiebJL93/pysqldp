# Fabric integration: run pysqldp's private SQL on a Lakehouse via Spark

**Date:** 2026-11-11
**Status:** implemented; verified on Spark SQL locally, unverified on Fabric itself

## Context

pysqldp rewrites an analytics query into an *intrinsically private* query: the
emitted SQL carries the mechanism — clipping, bin filling, Laplace noise —
inside it, so it runs unchanged on any SQL engine. The open question was
whether Microsoft Fabric can be one of those engines, and how much work that
takes.

The answer is yes for the **Lakehouse + Spark notebook** surface, with **no
change to the rewriter core**:

- `Database.sqlglot_dialect` (`src/pysqldp/schema.py:155`) already feeds both
  the parse side (`src/pysqldp/relalg/from_sql.py`) and the generate side
  (`src/pysqldp/rewriting/rewriter.py`), and `_DIALECTS`
  (`src/pysqldp/schema.py:30`) already maps `spark` → `spark`. Setting
  `dialect: "spark"` in the schema YAML is the whole dialect story.
- The noise term is two independent `RAND()` draws times `LN(...)`
  (`src/pysqldp/rewriting/dputil.py`, `laplace_sample`). Spark evaluates
  `rand()` per row, which is what the mechanism requires.
- Fabric User Data Functions run Python 3.11.9 and accept an uploaded `.whl`,
  so a hosted-service variant is possible later; `requires-python = ">=3.11"`
  fits.

## Decision

Keep the integration minimal: no runtime module, no `pysqldp.fabric`. What
Fabric needs is a schema with the right dialect, a test proving the emitted SQL
really executes on Spark, and documentation. Anything more would be code to
maintain for a capability the rewriter already has.

### What was built

| File | Role |
|---|---|
| `tests/fixtures/schema_fabric.yaml` | Spark-dialect schema, empty namespace |
| `tests/test_fabric_spark.py` | PySpark execution gate, marked `spark` |
| `notebooks/fabric_dp_demo.ipynb` | importable five-cell Fabric notebook |
| `pyproject.toml` | `spark` dependency group, `spark` marker, `addopts` |
| `README.md` | "Microsoft Fabric" section |

The schema differs from the DuckDB gate's inline schema in exactly two keys:

- `dialect: "spark"` — sqlglot emits Spark SQL, and `RAND()` is Spark's per-row
  generator.
- `namespace: ""` — a notebook attached to a Lakehouse resolves unqualified
  table names against it, so a qualified name would be wrong.

The test asserts, in order of what they protect:

1. The SQL runs on Spark SQL. DuckDB accepting it proves nothing about Fabric.
2. Every domain bin appears, including the empty one (bin filling).
3. Grouped `COUNT`, `SUM` and `AVG` land near the true answer.
4. **Noise differs between bins** — the per-row-`RAND()` property.
5. Clipping bounds one extreme row's influence.

Assertion 4 is the one worth having. It subtracts the true count from each
released count, leaving exactly the noise, and requires those residuals to
differ. That is precisely what a T-SQL port would silently break.

## Why the Warehouse / SQL analytics endpoint is excluded

`_DIALECTS` has no T-SQL entry, and T-SQL's `RAND()` is a *runtime constant per
query*: one draw reused for every row. Under bin filling every histogram bin
would receive identical noise, which an analyst cancels exactly by differencing
two bins — the mechanism would look correct and provide no privacy.

Microsoft's T-SQL surface-area and limitations pages for Fabric Warehouse
(<https://learn.microsoft.com/en-us/fabric/data-warehouse/tsql-surface-area>,
<https://learn.microsoft.com/en-us/fabric/data-warehouse/limitations>) say
nothing about `RAND()`, `NEWID()`, `CHECKSUM()`, `CRYPT_GEN_RANDOM()`,
`LOG`/`LN`, `RANGE` window frames, or `VALUES` constructors — they confirm only
CTEs and views. So no per-row random source can be shown sound from
documentation. A T-SQL path needs a probe on a live warehouse first, and is out
of scope.

## Deviations from the plan

- **`pyspark>=3.5,<4`, not `pyspark>=3.5`.** The unbounded constraint resolved
  to PySpark 4.3, which is not the engine Fabric runs. The gate exists to test
  Fabric Runtime 1.3's Spark 3.5; a 4.x engine could accept SQL that 3.5
  rejects, which would make the test misleading in the one direction that
  matters.
- **The `spark` fixture sets `PYSPARK_PYTHON` / `PYSPARK_DRIVER_PYTHON`.** Spark
  launches Python workers by name, so in a virtualenv it finds whatever
  `python` is on `PATH` — a missing or different interpreter — and the worker
  dies with an opaque `SocketException: Connection reset`. Fabric sets these
  itself; a local run has to. Without it all five tests fail with a JVM stack
  trace that names nothing relevant.

## Verification

- **Default suite unchanged:** `uv run pytest` → 119 passed, with the five
  `spark` tests deselected (or the module reported as one skip when `pyspark`
  is not installed, which is the `statdp` precedent).
- **Spark execution gate:** `uv sync --group spark` then
  `uv run --group spark pytest -m spark` → 5 passed on PySpark 3.5.9, Java 17.
  The emitted SQL executes, every bin is present, and noise differs between
  bins.
- **Fabric itself: not verified.** This session has no authorized Fabric
  connector or credentials, so local PySpark proves the *dialect* only. The
  notebook is what proves the *Fabric specifics*: `%pip install` resolution,
  the runtime's Python version, Lakehouse table resolution, and the
  `/lakehouse/default/Files/...` schema path. Until someone imports
  `notebooks/fabric_dp_demo.ipynb` into a workspace and runs it, the honest
  claim is "verified on Spark SQL locally, unverified on Fabric".

## Non-goals

No T-SQL dialect entry, no User Data Function deployment, no Delta-table
metadata catalog, no persisted budget ledger, no `pysqldp.fabric` module, and no
change to any mechanism, analysis or rewriter. This work is orthogonal to the
Phase 1–7 rewriter roadmap.
