"""End-to-end on Spark SQL: the Microsoft Fabric Lakehouse path.

``tests/test_executable.py`` proves the emitted SQL runs on DuckDB. That says
nothing about Fabric: DuckDB is permissive, and the properties the mechanism
depends on are engine-specific. This module runs the *same* queries through a
real Spark SQL engine, because a Fabric notebook attached to a Lakehouse
executes Spark SQL and nothing else.

Only the schema differs from the DuckDB gate
(``tests/fixtures/schema_fabric.yaml``): ``dialect: "spark"`` and an empty
namespace, since a notebook resolves unqualified names against its default
Lakehouse. No rewriter, mechanism or analysis code is involved in the
difference -- that is the point of the integration being this small.

The assertion that matters most is :func:`test_noise_differs_between_bins`. The
Laplace term is built from ``RAND()``, and the mechanism is only sound if each
row draws independently. Spark's ``rand()`` is a per-row expression, so it
holds here. T-SQL's ``RAND()`` is a runtime constant per query: every histogram
bin would receive *identical* noise, which an analyst cancels exactly by
subtracting two bins. That is why the Fabric Warehouse / SQL analytics endpoint
is not a supported target, and why this property is asserted rather than
assumed.

Local Spark needs a JVM and takes seconds to start, and ``pyspark`` is a large
download, so these tests are marked ``spark`` and deselected by default. Run on
demand with::

    uv sync --group spark
    uv run --group spark pytest -m spark tests/test_fabric_spark.py
"""

from __future__ import annotations

import os
import sys

import pytest

from pysqldp import rewrite_fixed_pipeline
from pysqldp.schema import Database, Schema

from .conftest import FIXTURES

pytest.importorskip("pyspark", reason="install with `uv sync --group spark`")

from pyspark.sql import SparkSession  # noqa: E402  (guarded by importorskip)
from pyspark.sql.types import (  # noqa: E402
    DoubleType,
    StringType,
    StructField,
    StructType,
)

pytestmark = pytest.mark.spark

#: Synthetic rows: 3 in north, 2 in south, none in west. Same as the DuckDB
#: gate, so a divergence between the engines shows up as a value difference and
#: not as a data difference.
ROWS = [
    ("north", 1.0),
    ("north", 2.0),
    ("north", 3.0),
    ("south", 4.0),
    ("south", 5.0),
]

#: 'west' is in the domain but has no rows, so bin filling has to invent it.
DOMAIN = [("north",), ("south",), ("west",)]

TRUE_COUNTS = {"north": 3, "south": 2, "west": 0}
TRUE_SUMS = {"north": 6.0, "south": 9.0, "west": 0.0}

EVENTS_SCHEMA = StructType(
    [
        StructField("region", StringType(), nullable=False),
        StructField("amount", DoubleType(), nullable=False),
    ]
)
DOMAIN_SCHEMA = StructType([StructField("region", StringType(), nullable=False)])

#: Large enough that noise is a fraction of a unit, so results can be asserted
#: on. Real deployments use values near 0.1, where noise dominates small counts
#: entirely.
LOW_NOISE_EPSILON = 50.0


@pytest.fixture(scope="session")
def database() -> Database:
    return Schema.load(FIXTURES / "schema_fabric.yaml").database("fabric")


@pytest.fixture(scope="session")
def spark(tmp_path_factory: pytest.TempPathFactory):
    """A local single-threaded Spark session, as close to Fabric as fits in CI.

    Fabric runs a managed cluster over Delta tables; what this shares with it
    is the SQL engine, which is the only part the rewritten query depends on.
    The warehouse directory goes to a temp path so no ``spark-warehouse``
    folder is left in the repository.
    """
    # Spark launches its Python workers by name, which finds whatever `python`
    # is on PATH rather than the interpreter running the tests. In a virtualenv
    # that is either missing or a different interpreter, and the worker dies
    # with an opaque "Connection reset". Fabric sets these itself.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

    warehouse = tmp_path_factory.mktemp("spark-warehouse")
    session = (
        SparkSession.builder.master("local[1]")
        .appName("pysqldp-fabric")
        .config("spark.sql.warehouse.dir", str(warehouse))
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    try:
        yield session
    finally:
        session.stop()


def _register_events(spark: SparkSession, rows: list[tuple[str, float]]) -> None:
    spark.createDataFrame(rows, EVENTS_SCHEMA).createOrReplaceTempView("events")


@pytest.fixture()
def lakehouse(spark: SparkSession) -> SparkSession:
    """``events`` and ``region_domain`` as temp views, named as in a Lakehouse.

    Unqualified names resolve against the session, which is what the schema's
    empty namespace emits and what a notebook attached to a Lakehouse does.
    """
    _register_events(spark, list(ROWS))
    spark.createDataFrame(DOMAIN, DOMAIN_SCHEMA).createOrReplaceTempView(
        "region_domain"
    )
    return spark


def _rows_by_region(spark: SparkSession, sql: str) -> dict[str, float]:
    return {row[0]: row[1] for row in spark.sql(sql).collect()}


def test_rewritten_count_runs_on_spark_sql(database, lakehouse) -> None:
    """The emitted SQL executes on a real Spark SQL engine.

    This is the whole point of the module. DuckDB accepting the query proves
    only that *some* engine parses it; Fabric runs Spark, so Spark has to.
    """
    query = "SELECT region, COUNT(*) AS n FROM events GROUP BY 1"
    sql, _ = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    results = _rows_by_region(lakehouse, sql)

    # Every bin in the domain appears, including the one with no data: that is
    # what stops the result set from revealing which values exist.
    assert set(results) == {"north", "south", "west"}
    for region, expected in TRUE_COUNTS.items():
        assert results[region] == pytest.approx(expected, abs=1.0)


def test_rewritten_sum_stays_near_the_truth(database, lakehouse) -> None:
    query = "SELECT region, SUM(amount) AS total FROM events GROUP BY 1"
    sql, _ = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    results = _rows_by_region(lakehouse, sql)

    assert set(results) == {"north", "south", "west"}
    for region, expected in TRUE_SUMS.items():
        # Noise scale here is stability 2 * range 10 / epsilon 50 = 0.4.
        assert results[region] == pytest.approx(expected, abs=4.0)


def test_rewritten_average_runs(database, lakehouse) -> None:
    query = "SELECT region, AVG(amount) AS mean FROM events GROUP BY 1"
    sql, spent = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    results = _rows_by_region(lakehouse, sql)

    # An AVG is a noisy sum over a noisy count, so it costs two releases.
    assert spent == pytest.approx(2 * LOW_NOISE_EPSILON)
    # north averages 2.0 and south 4.5; west divides noise by noise, so only
    # the populated bins are worth asserting on.
    assert results["north"] == pytest.approx(2.0, abs=2.0)
    assert results["south"] == pytest.approx(4.5, abs=2.0)


def test_noise_differs_between_bins(database, lakehouse) -> None:
    """Each bin must get its own Laplace draw, not one draw shared by all.

    Subtracting the true count from each released count leaves exactly the
    noise that was added. If the engine evaluated ``RAND()`` once per query --
    as T-SQL does -- those residuals would be identical, and an analyst could
    cancel the noise by differencing any two bins. On Spark ``rand()`` is a
    per-row expression, so they differ.
    """
    query = "SELECT region, COUNT(*) AS n FROM events GROUP BY 1"
    sql, _ = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    results = _rows_by_region(lakehouse, sql)
    residuals = [results[region] - TRUE_COUNTS[region] for region in TRUE_COUNTS]

    # Continuous noise: two independent draws collide with probability 0, so
    # any equality here means the draws were not independent.
    for index, left in enumerate(residuals):
        for right in residuals[index + 1 :]:
            assert abs(left - right) > 1e-9


def test_clipping_bounds_the_influence_of_one_extreme_row(database, lakehouse) -> None:
    """A single outlier must not move the released sum beyond the clip bound.

    This is the property clipping exists for: without it one row could carry an
    arbitrary value and no finite noise would hide it. Mirrors the DuckDB gate,
    on the engine Fabric actually runs.
    """
    query = "SELECT region, SUM(amount) AS total FROM events GROUP BY 1"
    sql, _ = rewrite_fixed_pipeline(database, query, LOW_NOISE_EPSILON)

    before = _rows_by_region(lakehouse, sql)
    _register_events(lakehouse, [*ROWS, ("north", 1_000_000.0)])
    after = _rows_by_region(lakehouse, sql)

    # The outlier is clipped to 10, so north can rise by at most 10 plus noise
    # rather than by a million.
    assert after["north"] - before["north"] < 20.0
