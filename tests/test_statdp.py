"""Statistical privacy check of the emitted SQL, with StatDP on DuckDB.

Port of the Scala project's ``tests/statdp_tests_sqlite.py``. StatDP (Ding et
al., "Detecting Violations of Differential Privacy", CCS 2018,
https://arxiv.org/abs/1805.10277) runs a mechanism many times on neighbouring
inputs and hypothesis-tests whether the output distributions differ by more
than ``e^epsilon`` allows. It is the only test here that can catch a wrong
noise scale: every other test checks structure, and an under-noised query is
structurally identical to a correct one.

Differences from the Scala script, and why:

* The Scala script ran *hand-pasted* rewriter output; a port that did the same
  would test the Scala SQL, not this one. Each mechanism here runs whatever
  ``rewrite_fixed_pipeline`` emits, and the claimed epsilon is the budget the
  pipeline reports, so budget accounting is under test too.
* DuckDB instead of SQLite: DuckDB has ``LN`` natively, so the SQLite math
  extension (``tests/sqlite-extension-functions/``) is not needed.
* The Scala script only printed StatDP's result. Here a p-value below
  ``P_THRESHOLD`` fails the test, and a deliberately under-noised control
  shows the check can fail at all.

StatDP's inputs are vectors of small integers (0, 1, 2) where the first entry
differs between the two neighbours. They are materialised as rows of a
``queries`` table: as per-category row counts for COUNT, and as one ``val`` row
per entry for SUM/AVG (so neighbours differ in one row's value, the bounded-DP
neighbour that clipping to ``[0, 2]`` protects).

Slow — each mechanism runs the rewritten SQL on DuckDB tens of thousands of
times — so it is deselected by default. Run on demand with::

    uv sync --group statdp
    uv run --group statdp pytest -m slow tests/test_statdp.py
"""

from __future__ import annotations

import typing

import pytest

from pysqldp import rewrite_fixed_pipeline
from pysqldp.schema import Schema

statdp = pytest.importorskip("statdp", reason="install with `uv sync --group statdp`")
duckdb = pytest.importorskip("duckdb", reason="duckdb is a dev dependency")

pytestmark = pytest.mark.slow

EPSILON = 0.1

#: StatDP reports the p-value of "the mechanism satisfies epsilon-DP"; the
#: paper treats p < 0.05 as a detected violation.
P_THRESHOLD = 0.05

#: StatDP generates inputs of length 5 and 10; one domain covers both.
MAX_INPUT = 10

#: A fifth of StatDP's defaults (100k/500k). Every call executes real SQL, so
#: the defaults cost ~45 minutes per mechanism; at these counts a correct
#: mechanism measures p ≈ 0.98 and a fourfold under-noised one p = 0.0, which
#: is the separation the gate needs. Raise them when investigating a borderline
#: p-value — a *lower* count is what would make a violation easy to miss.
EVENT_ITERATIONS = 20_000
DETECT_ITERATIONS = 100_000

SCHEMA = """
databases:
- database: "statdp"
  dialect: "duckdb"
  namespace: ""
  tables:
  - table: "queries"
    columns:
    - name: "category"
      canRelease: true
      domainSet: "category_domain.category"
    - name: "val"
      typeName: "DOUBLE"
      clipLower: 0
      clipUpper: 2
  - table: "category_domain"
    isPublic: true
    columns:
    - name: "category"
"""

COUNT_QUERY = "SELECT category, COUNT(*) AS n FROM queries GROUP BY 1"
SUM_QUERY = "SELECT SUM(val) AS total_val FROM queries"
AVG_QUERY = "SELECT AVG(val) AS avg_val FROM queries"


def rewrite(query: str) -> tuple[str, float]:
    return rewrite_fixed_pipeline(Schema.loads(SCHEMA).database("statdp"), query, EPSILON)


# StatDP calls the mechanisms in worker processes, so they must be module-level
# functions, and each worker lazily opens its own connection.
_conn = None


def _connection():
    global _conn
    if _conn is None:
        _conn = duckdb.connect()
        _conn.execute(
            "CREATE TABLE category_domain AS SELECT 'dummy' || i AS category "
            f"FROM range({MAX_INPUT}) t(i)"
        )
    return _conn


def _load(rows: list[tuple[str, float]]):
    # One statement per call: StatDP makes ~10^6 calls per test, and a table
    # rebuilt with executemany costs ~5x more. Values are generated here
    # (category names and floats), so inlining them is safe.
    con = _connection()
    values = ", ".join(f"('{c}', {v!r})" for c, v in rows)
    con.execute(
        "CREATE OR REPLACE TEMP VIEW queries AS SELECT category, CAST(val AS DOUBLE) AS val "
        f"FROM (VALUES {values}) t(category, val)"
    )
    return con


_sql_cache: dict[str, str] = {}


def _sql(query: str) -> str:
    if query not in _sql_cache:
        _sql_cache[query] = rewrite(query)[0]
    return _sql_cache[query]


def _noisy_count(sql: str, queries: typing.List[int]) -> float:
    # Entry i is the count of category dummy<i>; StatDP varies entry 0.
    rows = [(f"dummy{i}", 0.0) for i, n in enumerate(queries) for _ in range(int(n))]
    result = dict(_load(rows).execute(sql).fetchall())
    return result["dummy0"]


def _noisy_scalar(sql: str, queries: typing.List[int]) -> float:
    rows = [(f"dummy{i}", float(v)) for i, v in enumerate(queries)]
    return _load(rows).execute(sql).fetchone()[0]


def global_sensitivity_count(prng, queries: typing.List[int], epsilon: float):
    return _noisy_count(_sql(COUNT_QUERY), queries)


def clip_global_sensitivity_sum(prng, queries: typing.List[int], epsilon: float):
    return _noisy_scalar(_sql(SUM_QUERY), queries)


def reduce_clip_global_sensitivity_avg(prng, queries: typing.List[int], epsilon: float):
    return _noisy_scalar(_sql(AVG_QUERY), queries)


def underscaled_count(prng, queries: typing.List[int], epsilon: float):
    """Negative control: the emitted COUNT with its noise scale cut fourfold.

    Scale 20 on a sensitivity-1 count is 0.05-DP; scale 5 is only 0.2-DP, so
    claiming 0.1 is a real violation StatDP must flag.
    """
    sql = _sql(COUNT_QUERY)
    assert sql.count("20.0 *") == 1
    return _noisy_count(sql.replace("20.0 *", "5.0 *"), queries)


def _p_values(mechanism, epsilon: float) -> list[float]:
    result = statdp.detect_counterexample(
        mechanism,
        (epsilon,),
        {"epsilon": epsilon},
        sensitivity=statdp.generators.ONE_DIFFER,
        event_iterations=EVENT_ITERATIONS,
        detect_iterations=DETECT_ITERATIONS,
        quiet=True,
    )
    return [p for _, p, *_ in result]


@pytest.mark.parametrize(
    "mechanism, query",
    [
        (global_sensitivity_count, COUNT_QUERY),
        (clip_global_sensitivity_sum, SUM_QUERY),
        (reduce_clip_global_sensitivity_avg, AVG_QUERY),
    ],
)
def test_mechanism_satisfies_claimed_epsilon(mechanism, query) -> None:
    _, claimed = rewrite(query)
    for p in _p_values(mechanism, claimed):
        assert p >= P_THRESHOLD, f"{mechanism.__name__} violates {claimed}-DP (p={p})"


def test_underscaled_noise_is_detected() -> None:
    """Without this, a gate that never fails would look the same as one that works."""
    assert min(_p_values(underscaled_count, EPSILON)) < P_THRESHOLD


@pytest.mark.parametrize("name", ["census_percentile_10", "census_percentile_90"])
def test_census_percentile(name: str) -> None:
    pytest.skip(f"{name} needs the census percentile mechanism (phase 3)")
