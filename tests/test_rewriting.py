"""The rewriters: clipping, AVG reduction, bin filling, and noise injection."""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot import exp

from pysqldp.exceptions import RewritingException
from pysqldp.relalg import AggFunction, Aggregate, Project, parse_to_rel_tree, to_sql
from pysqldp.relalg.nodes import WithTable
from pysqldp.rewriting import (
    ClippingRewriter,
    GlobalSensitivityConfig,
    GlobalSensitivityRewriter,
    RewriterConfig,
    count_releases,
    laplace_sample,
    reduce_aggregate_functions,
)
from pysqldp.schema import Database, Schema

from .conftest import EPSILON

NARROW_RANGE_SCHEMA = """
databases:
- database: "narrow"
  dialect: "hive"
  namespace: ""
  tables:
  - table: "t"
    columns:
    - name: "v"
      clipLower: 0
      clipUpper: 0.5
"""


def lower(query: str, database: Database):
    return parse_to_rel_tree(query, database)


def clip(query: str, database: Database):
    return ClippingRewriter(RewriterConfig(database)).rewrite(lower(query, database))


def noise(rel, database: Database, epsilon: float = EPSILON) -> str:
    config = GlobalSensitivityConfig(database=database, epsilon=epsilon)
    return GlobalSensitivityRewriter(config).run(rel).to_sql()


# --- Laplace sampler --------------------------------------------------------


def test_laplace_sample_matches_the_scala_expression(experiments: Database) -> None:
    sql = to_sql(
        Project(
            lower("SELECT COUNT(*) AS n FROM table_b", experiments),
            (laplace_sample(),),
            ("noise",),
        ),
        dialect=experiments.sqlglot_dialect,
    )
    # The sign and the magnitude come from independent uniform draws, exactly
    # as in DPUtil.laplaceSample.
    assert "CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END" in sql
    assert "LN(1 - 2 * ABS(RAND() - 0.5))" in sql


def test_laplace_sample_uses_the_dialect_random_function(experiments: Database) -> None:
    postgres = Database(
        database="d", dialect="postgresql", tables=experiments.tables
    )
    sql = to_sql(
        Project(
            lower("SELECT COUNT(*) AS n FROM table_b", postgres),
            (laplace_sample(),),
            ("noise",),
        ),
        dialect=postgres.sqlglot_dialect,
    )
    assert "RANDOM()" in sql.upper()


# --- Clipping ---------------------------------------------------------------


def test_clipping_wraps_the_summed_column_in_bounds(experiments: Database) -> None:
    clipped = clip("SELECT SUM(v1) AS total FROM table_b", experiments)
    sql = to_sql(clipped, dialect=experiments.sqlglot_dialect)

    assert "SUM(CASE WHEN" in sql
    assert "< 0.0 THEN 0.0" in sql
    assert "> 10000000.0 THEN 10000000.0" in sql


def test_clipping_preserves_the_output_shape(experiments: Database) -> None:
    rel = lower("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    clipped = ClippingRewriter(RewriterConfig(experiments)).rewrite(rel)
    assert clipped.row_type == rel.row_type


def test_clipping_leaves_count_inputs_alone(experiments: Database) -> None:
    # ja1 has no clipping bounds, so clipping it would fail. COUNT reads rows
    # rather than values, so it must be skipped.
    clipped = clip("SELECT COUNT(ja1) AS n FROM table_b", experiments)
    sql = to_sql(clipped, dialect=experiments.sqlglot_dialect)
    assert "CASE WHEN" not in sql


def test_clipping_requires_declared_bounds(experiments: Database) -> None:
    with pytest.raises(RewritingException, match="clipLower"):
        clip("SELECT SUM(ja1) AS s FROM table_b", experiments)


def test_clipping_rejects_a_degenerate_range() -> None:
    # A range under 1 would let SUM be used to count filtered rows, which would
    # then be released with SUM's sensitivity rather than COUNT's.
    database = Schema.loads(NARROW_RANGE_SCHEMA).database("narrow")
    with pytest.raises(RewritingException, match="at least 1"):
        clip("SELECT SUM(v) AS s FROM t", database)


# --- AVG reduction ----------------------------------------------------------


def test_avg_is_decomposed_into_sum_and_count(experiments: Database) -> None:
    rel = lower("SELECT g1, AVG(v1) AS avg_v1 FROM table_b GROUP BY 1", experiments)
    reduced = reduce_aggregate_functions(rel)

    assert isinstance(reduced, Project)
    assert reduced.row_type == rel.row_type

    aggregate = reduced.input
    assert isinstance(aggregate, Aggregate)
    assert [call.func for call in aggregate.agg_calls] == [
        AggFunction.SUM,
        AggFunction.COUNT,
    ]


def test_queries_without_avg_are_untouched(experiments: Database) -> None:
    rel = lower("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    assert reduce_aggregate_functions(rel) is rel


def test_release_counts_follow_sequential_composition() -> None:
    assert count_releases(AggFunction.COUNT) == 1
    assert count_releases(AggFunction.SUM) == 1
    # An average is a sum and a count, so it is two releases.
    assert count_releases(AggFunction.AVG) == 2
    assert count_releases(AggFunction.VAR) == 3


# --- Noise injection and bin filling ----------------------------------------


def test_ungrouped_count_gets_noise_scaled_to_one_over_epsilon(
    experiments: Database,
) -> None:
    sql = noise(lower("SELECT COUNT(*) AS n FROM table_b", experiments), experiments)
    # sensitivity 1 / epsilon 0.1 = 10
    assert "10.0 *" in sql


def test_grouped_count_noise_accounts_for_the_doubled_stability(
    experiments: Database,
) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    sql = noise(rel, experiments)
    # sensitivity 2 / epsilon 0.1 = 20
    assert "20.0 *" in sql


def test_clipped_sum_noise_uses_the_clipping_range(experiments: Database) -> None:
    rel = clip("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    sql = noise(rel, experiments)
    # stability 2 * range 10000000 / epsilon 0.1 = 200000000
    assert "200000000.0 *" in sql


def test_bins_are_filled_from_the_domain_table(experiments: Database) -> None:
    rel = lower("SELECT g1, g2, COUNT(*) AS n FROM table_b GROUP BY 1, 2", experiments)
    sql = noise(rel, experiments)

    assert sql.startswith("WITH _domain AS")
    assert "g1_g2_domain" in sql
    assert "RIGHT JOIN _domain" in sql
    # Bins with no rows come back NULL and must read as 0 before noise.
    assert "ELSE 0 END" in sql


def test_bin_labels_are_taken_from_the_domain_side(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    sql = noise(rel, experiments)
    select = sqlglot.parse_one(sql, read=experiments.sqlglot_dialect)
    first = select.expressions[0]
    # Reading the label off the aggregated side would make missing bins NULL.
    assert first.find(exp.Column).table == "_domain"


def test_releasable_bins_are_left_un_noised(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    sql = noise(rel, experiments)
    # One noise term, for the count; none for the bin label.
    assert sql.count("LN(1 - 2 * ABS(RAND() - 0.5))") == 1


def test_bin_filling_requires_a_domain_set(test_db: Database) -> None:
    # orders.order_date is marked canRelease, so it passes the bin check, but
    # it declares no domainSet to enumerate its values.
    rel = lower("SELECT order_date, COUNT(*) AS n FROM orders GROUP BY 1", test_db)
    with pytest.raises(RewritingException, match="domainSet"):
        noise(rel, test_db)


def test_bin_filling_can_be_disabled(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    config = GlobalSensitivityConfig(
        database=experiments, epsilon=EPSILON, fill_missing_bins=False
    )
    sql = GlobalSensitivityRewriter(config).run(rel).to_sql()
    assert "_domain" not in sql


def test_unbounded_sensitivity_is_refused_rather_than_under_noised(
    experiments: Database,
) -> None:
    rel = lower("SELECT MIN(v1) AS lo FROM table_b", experiments)
    with pytest.raises(RewritingException, match="infinite"):
        noise(rel, experiments)


def test_noise_is_added_once_per_query(experiments: Database) -> None:
    rel = clip("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    config = GlobalSensitivityConfig(database=experiments, epsilon=EPSILON)
    rewritten = GlobalSensitivityRewriter(config).rewrite(rel)

    # The bin-filling CTE wraps the noised projection; noise must live in that
    # projection rather than in a second one stacked above it.
    assert isinstance(rewritten, WithTable)
    assert isinstance(rewritten.body, Project)


def test_smaller_epsilon_means_more_noise(experiments: Database) -> None:
    rel = lower("SELECT COUNT(*) AS n FROM table_b", experiments)
    assert "10.0 *" in noise(rel, experiments, epsilon=0.1)
    assert "100.0 *" in noise(rel, experiments, epsilon=0.01)
