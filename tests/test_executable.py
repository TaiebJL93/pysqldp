"""End-to-end: the rewritten SQL actually runs, and the answers are usable.

The Scala project verified this with Docker, Presto and MySQL
(``scripts/create-container.sh``, ``scripts/run-exp.sh``). DuckDB does the same
job in-process, so the check runs anywhere ``pytest`` does.

Two things are being checked, and they pull against each other. The rewritten
query must be *syntactically valid* on a real engine — no amount of unit
testing the IR proves that. And its answers must stay *close enough to the
truth to be worth releasing*, which is the accuracy half of the privacy
trade-off. These tests use a deliberately large epsilon so the noise is small
enough to assert on; production values are far smaller and far noisier.

The rows are hand-written on purpose. ``tests/data/`` (copied from the Scala
project) holds the *outputs* of its accuracy and perf experiments — true
per-bin answers, noisy samples, timings, plots — from MySQL databases that
were never committed, so there are no input rows there to load. Those files
are baselines for the accuracy harness, not fixtures for this module.
"""

from __future__ import annotations

import pytest

from pysqldp import rewrite_fixed_pipeline
from pysqldp.schema import Database, Schema

duckdb = pytest.importorskip("duckdb", reason="duckdb is a dev dependency")

SCHEMA = """
databases:
- database: "exec"
  dialect: "duckdb"
  namespace: ""
  tables:
  - table: "events"
    columns:
    - name: "region"
      canRelease: true
      domainSet: "region_domain.region"
    - name: "amount"
      typeName: "DOUBLE"
      clipLower: 0
      clipUpper: 10
  - table: "region_domain"
    isPublic: true
    columns:
    - name: "region"
"""

#: Synthetic rows: 3 in north, 2 in south, none in west.
ROWS = [
    ("north", 1.0),
    ("north", 2.0),
    ("north", 3.0),
    ("south", 4.0),
    ("south", 5.0),
]

TRUE_COUNTS = {"north": 3, "south": 2, "west": 0}
TRUE_SUMS = {"north": 6.0, "south": 9.0, "west": 0.0}

#: Large enough that noise is a fraction of a unit, so results can be asserted
#: on. Real deployments use values near 0.1, where noise dominates small counts
#: entirely.
LOW_NOISE_EPSILON = 50.0


@pytest.fixture()
def database() -> Database:
    return Schema.loads(SCHEMA).database("exec")


@pytest.fixture()
def connection():
    con = duckdb.connect()
    con.execute("CREATE TABLE events (region VARCHAR, amount DOUBLE)")
    con.executemany("INSERT INTO events VALUES (?, ?)", ROWS)
    con.execute("CREATE TABLE region_domain (region VARCHAR)")
    # 'west' exists in the domain but has no rows, so bin filling has to
    # invent it.
    con.executemany(
        "INSERT INTO region_domain VALUES (?)", [("north",), ("south",), ("west",)]
    )
    try:
        yield con
    finally:
        con.close()


def test_rewritten_count_runs_and_returns_every_bin(database, connection) -> None:
    query = "SELECT region, COUNT(*) AS n FROM events GROUP BY 1"
    sql, _ = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    results = dict(connection.execute(sql).fetchall())

    # Every bin in the domain appears, including the one with no data: that is
    # what stops the result set from revealing which values exist.
    assert set(results) == {"north", "south", "west"}
    for region, expected in TRUE_COUNTS.items():
        assert results[region] == pytest.approx(expected, abs=1.0)


def test_rewritten_sum_runs_and_stays_near_the_truth(database, connection) -> None:
    query = "SELECT region, SUM(amount) AS total FROM events GROUP BY 1"
    sql, _ = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    results = dict(connection.execute(sql).fetchall())

    assert set(results) == {"north", "south", "west"}
    for region, expected in TRUE_SUMS.items():
        # Noise scale here is stability 2 * range 10 / epsilon 50 = 0.4.
        assert results[region] == pytest.approx(expected, abs=4.0)


def test_rewritten_average_runs(database, connection) -> None:
    query = "SELECT region, AVG(amount) AS mean FROM events GROUP BY 1"
    sql, spent = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    results = dict(connection.execute(sql).fetchall())

    assert spent == pytest.approx(2 * LOW_NOISE_EPSILON)
    # north averages 2.0 and south 4.5; west divides noise by noise, so only
    # the populated bins are worth asserting on.
    assert results["north"] == pytest.approx(2.0, abs=2.0)
    assert results["south"] == pytest.approx(4.5, abs=2.0)


def test_ungrouped_count_runs(database, connection) -> None:
    sql, _ = rewrite_fixed_pipeline(
        database, "SELECT COUNT(*) AS n FROM events", LOW_NOISE_EPSILON
    )
    (value,) = connection.execute(sql).fetchone()
    assert value == pytest.approx(len(ROWS), abs=1.0)


def test_clipping_bounds_the_influence_of_one_extreme_row(database, connection) -> None:
    """A single outlier must not move the released sum beyond the clip bound.

    This is the property clipping exists for: without it one row could carry an
    arbitrary value and no finite noise would hide it.
    """
    query = "SELECT region, SUM(amount) AS total FROM events GROUP BY 1"
    sql, _ = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    before = dict(connection.execute(sql).fetchall())
    connection.execute("INSERT INTO events VALUES ('north', 1000000.0)")
    after = dict(connection.execute(sql).fetchall())

    # The outlier is clipped to 10, so north can rise by at most 10 plus noise
    # rather than by a million.
    assert after["north"] - before["north"] < 20.0


def test_noise_is_redrawn_on_each_execution(database, connection) -> None:
    """The same rewritten query must not return the same answer every time.

    A cached or constant-folded RAND() would make the query deterministic,
    which would let an analyst average the noise away by repeating it.
    """
    sql, _ = rewrite_fixed_pipeline(
        database, "SELECT COUNT(*) AS n FROM events", epsilon=0.1
    )
    values = {connection.execute(sql).fetchone()[0] for _ in range(10)}
    assert len(values) > 1
