"""The public pipeline: budget accounting, refusals, and the full rewrite."""

from __future__ import annotations

import pytest
import sqlglot

from pysqldp import budget_usage, rewrite_fixed_pipeline
from pysqldp.exceptions import (
    ProtectedBinException,
    RewritingException,
    UnsupportedQueryException,
)
from pysqldp.schema import Database

from .conftest import EPSILON


# --- Budget accounting ------------------------------------------------------


def test_single_aggregation_costs_one_epsilon(experiments: Database) -> None:
    query = "SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1"
    assert budget_usage(experiments, query, EPSILON) == pytest.approx(EPSILON)


def test_two_aggregations_cost_two_epsilons(experiments: Database) -> None:
    query = "SELECT g1, COUNT(*) AS n, SUM(v1) AS total FROM table_b GROUP BY 1"
    assert budget_usage(experiments, query, EPSILON) == pytest.approx(2 * EPSILON)


def test_average_costs_two_epsilons(experiments: Database) -> None:
    # An average is released as a sum and a count, so composition charges it
    # twice.
    query = "SELECT g1, AVG(v1) AS avg_v1 FROM table_b GROUP BY 1"
    assert budget_usage(experiments, query, EPSILON) == pytest.approx(2 * EPSILON)


def test_min_and_max_over_one_column_share_a_release(experiments: Database) -> None:
    # Percentile-style aggregations read one noisy distribution, so asking for
    # both ends of it is a single release.
    query = "SELECT MIN(v1) AS lo, MAX(v1) AS hi FROM table_b"
    assert budget_usage(experiments, query, EPSILON) == pytest.approx(EPSILON)


def test_grouping_columns_are_free(experiments: Database) -> None:
    one_bin = "SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1"
    two_bins = "SELECT g1, g2, COUNT(*) AS n FROM table_b GROUP BY 1, 2"
    assert budget_usage(experiments, one_bin, EPSILON) == budget_usage(
        experiments, two_bins, EPSILON
    )


def test_budget_scales_with_epsilon(experiments: Database) -> None:
    query = "SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1"
    assert budget_usage(experiments, query, 1.0) == pytest.approx(1.0)
    assert budget_usage(experiments, query, 0.5) == pytest.approx(0.5)


def test_budget_refuses_a_raw_data_query(experiments: Database) -> None:
    with pytest.raises(UnsupportedQueryException, match="non-aggregation"):
        budget_usage(experiments, "SELECT b_id FROM table_b", EPSILON)


# --- Refusals ---------------------------------------------------------------


def test_raw_data_query_is_refused(experiments: Database) -> None:
    with pytest.raises(UnsupportedQueryException, match="non-aggregation"):
        rewrite_fixed_pipeline(experiments, "SELECT b_id FROM table_b", EPSILON)


def test_tainted_column_is_refused(test_db: Database) -> None:
    # No amount of noise makes a tainted column releasable, so this is refused
    # before any mechanism is chosen.
    with pytest.raises(UnsupportedQueryException, match="tainted"):
        rewrite_fixed_pipeline(test_db, "SELECT COUNT(name) AS n FROM customers", EPSILON)


def test_protected_bin_is_refused(experiments: Database) -> None:
    with pytest.raises(ProtectedBinException, match="ja1"):
        rewrite_fixed_pipeline(
            experiments, "SELECT ja1, COUNT(*) AS n FROM table_b GROUP BY 1", EPSILON
        )


def test_sum_without_bounds_is_refused(experiments: Database) -> None:
    with pytest.raises(RewritingException, match="clipLower"):
        rewrite_fixed_pipeline(
            experiments, "SELECT g1, SUM(ja1) AS s FROM table_b GROUP BY 1", EPSILON
        )


def test_percentile_mechanism_is_not_available_yet(experiments: Database) -> None:
    # Reported as a refusal rather than silently noised with the wrong scale.
    with pytest.raises(RewritingException):
        rewrite_fixed_pipeline(experiments, "SELECT MIN(v1) AS lo FROM table_b", EPSILON)


# --- Full rewrite -----------------------------------------------------------


def test_walking_skeleton_rewrites_the_sum_histogram(experiments: Database) -> None:
    query = """
        SELECT g1, g2, SUM(v1) AS total_v1
        FROM table_b
        WHERE g0 = 'xxx'
        GROUP BY 1, 2
    """
    sql, spent = rewrite_fixed_pipeline(experiments, query, EPSILON)

    assert spent == pytest.approx(EPSILON)

    # The bin domain, so absent bins cannot be told apart from noised ones.
    assert sql.startswith("WITH _domain AS")
    assert "RIGHT JOIN _domain" in sql
    # Clipping, which is what gives SUM a bounded sensitivity at all.
    assert "SUM(CASE WHEN" in sql
    # Noise scaled to stability 2 * range 10000000 / epsilon 0.1.
    assert "200000000.0 *" in sql
    assert "LN(1 - 2 * ABS(RAND() - 0.5))" in sql
    # The predicate must survive into the aggregated subquery.
    assert "WHERE table_b.g0 = 'xxx'" in sql


def test_rewrite_preserves_output_column_names(experiments: Database) -> None:
    query = "SELECT g1, g2, COUNT(*) AS n FROM table_b GROUP BY 1, 2"
    sql, _ = rewrite_fixed_pipeline(experiments, query, EPSILON)
    assert "AS n" in sql
    assert "_domain.g1" in sql


def test_order_by_survives_the_rewrite(experiments: Database) -> None:
    query = "SELECT g1, g2, COUNT(*) AS n FROM table_b GROUP BY 1, 2 ORDER BY 1, 2"
    sql, _ = rewrite_fixed_pipeline(experiments, query, EPSILON)
    assert "ORDER BY" in sql


def test_average_is_rewritten_as_a_ratio_of_noised_halves(
    experiments: Database,
) -> None:
    query = "SELECT g1, AVG(v1) AS avg_v1 FROM table_b GROUP BY 1"
    sql, spent = rewrite_fixed_pipeline(experiments, query, EPSILON)

    assert spent == pytest.approx(2 * EPSILON)
    # Two independent noise terms, one for the sum and one for the count.
    assert sql.count("LN(1 - 2 * ABS(RAND() - 0.5))") == 2
    assert "AS avg_v1" in sql


def test_ungrouped_count_needs_no_domain_table(experiments: Database) -> None:
    sql, spent = rewrite_fixed_pipeline(
        experiments, "SELECT COUNT(*) AS n FROM table_b", EPSILON
    )
    assert spent == pytest.approx(EPSILON)
    assert "_domain" not in sql
    assert "10.0 *" in sql


def test_rewritten_sql_is_valid_in_the_schema_dialect(experiments: Database) -> None:
    query = "SELECT g1, g2, SUM(v1) AS total_v1 FROM table_b GROUP BY 1, 2"
    sql, _ = rewrite_fixed_pipeline(experiments, query, EPSILON)
    # Re-parsing in the same dialect proves the output is well formed.
    assert sqlglot.parse_one(sql, read=experiments.sqlglot_dialect) is not None
