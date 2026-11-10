"""Lowering SQL into the relational IR, and generating SQL back out."""

from __future__ import annotations

import pytest
import sqlglot

from pysqldp.exceptions import UnsupportedQueryException
from pysqldp.relalg import (
    AggFunction,
    Aggregate,
    Filter,
    InputRef,
    Project,
    Scan,
    Sort,
    parse_to_rel_tree,
    to_sql,
)
from pysqldp.relalg.nodes import Join, SubqueryAlias, WithTable
from pysqldp.schema import Database


def lower(query: str, database: Database):
    return parse_to_rel_tree(query, database)


def render(rel, database: Database) -> str:
    return to_sql(rel, dialect=database.sqlglot_dialect)


def equivalent(left: str, right: str, dialect: str | None) -> bool:
    """Compare two queries by parsed AST, ignoring formatting."""
    return sqlglot.parse_one(left, read=dialect) == sqlglot.parse_one(right, read=dialect)


# --- Lowering ---------------------------------------------------------------


def test_scan_exposes_the_schema_columns(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    scan = rel.input
    assert isinstance(scan, Scan)
    assert scan.table == "table_b"
    assert scan.columns == experiments.table("table_b").column_names


def test_where_becomes_a_filter(experiments: Database) -> None:
    rel = lower(
        "SELECT g1, COUNT(*) AS n FROM table_b WHERE g0 = 'x' GROUP BY 1", experiments
    )
    assert isinstance(rel.input, Filter)
    assert isinstance(rel.input.input, Scan)


def test_grouped_columns_lead_the_output(experiments: Database) -> None:
    rel = lower(
        "SELECT g1, g2, SUM(v1) AS total FROM table_b GROUP BY 1, 2", experiments
    )
    assert isinstance(rel, Aggregate)
    assert rel.group_count == 2
    assert rel.row_type == ("g1", "g2", "total")
    assert rel.agg_calls[0].func is AggFunction.SUM


def test_positional_group_by_resolves_through_the_select_list(
    experiments: Database,
) -> None:
    by_position = lower(
        "SELECT g1, g2, COUNT(*) AS n FROM table_b GROUP BY 1, 2", experiments
    )
    by_name = lower(
        "SELECT g1, g2, COUNT(*) AS n FROM table_b GROUP BY g1, g2", experiments
    )
    assert by_position.group_keys == by_name.group_keys


def test_count_star_has_no_arguments(experiments: Database) -> None:
    rel = lower("SELECT COUNT(*) AS n FROM table_b", experiments)
    assert rel.agg_calls[0].func is AggFunction.COUNT
    assert rel.agg_calls[0].args == ()


def test_aggregate_argument_resolves_to_an_input_index(experiments: Database) -> None:
    rel = lower("SELECT SUM(v1) AS s FROM table_b", experiments)
    expected = experiments.table("table_b").column_names.index("v1")
    assert rel.agg_calls[0].args == (expected,)


def test_order_by_becomes_a_sort_over_output_positions(experiments: Database) -> None:
    rel = lower(
        "SELECT g1, g2, COUNT(*) AS n FROM table_b GROUP BY 1, 2 ORDER BY 2, 1 DESC",
        experiments,
    )
    assert isinstance(rel, Sort)
    assert [(k.idx, k.descending) for k in rel.keys] == [(1, False), (0, True)]


def test_projection_without_aggregation_is_a_project(experiments: Database) -> None:
    rel = lower("SELECT b_id, g1 FROM table_b", experiments)
    assert isinstance(rel, Project)
    assert rel.row_type == ("b_id", "g1")


def test_unaliased_aggregate_gets_a_generated_name(experiments: Database) -> None:
    rel = lower("SELECT COUNT(*) FROM table_b", experiments)
    assert rel.row_type == ("_f0",)


def test_qualified_column_resolves_through_the_table_alias(
    experiments: Database,
) -> None:
    rel = lower("SELECT t.g1, COUNT(*) AS n FROM table_b AS t GROUP BY 1", experiments)
    assert rel.row_type == ("g1", "n")


# --- Refusals ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("SELECT * FROM table_b", r"SELECT \*"),
        ("SELECT g1 FROM table_b JOIN table_a ON g1 = a_id", "joins"),
        ("SELECT DISTINCT g1 FROM table_b", "DISTINCT"),
        (
            "SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1 HAVING COUNT(*) > 1",
            "HAVING",
        ),
        ("SELECT g1 FROM (SELECT g1 FROM table_b) AS s", "subquer"),
        ("SELECT COUNT(*) AS n FROM table_b WHERE unknown_col = 1", "not defined"),
        ("SELECT g1, SUM(v1 + 1) AS s FROM table_b GROUP BY 1", "plain column"),
        ("SELECT g1, SUM(v1) + 1 AS s FROM table_b GROUP BY 1", "arithmetic"),
        ("SELECT g1, COUNT(*) AS n FROM table_b", "not grouped"),
    ],
)
def test_unsupported_shapes_are_refused(
    query: str, reason: str, experiments: Database
) -> None:
    with pytest.raises(UnsupportedQueryException, match=reason):
        lower(query, experiments)


def test_unparseable_query_is_refused(experiments: Database) -> None:
    with pytest.raises(UnsupportedQueryException):
        lower("SELECT FROM WHERE", experiments)


def test_non_select_statement_is_refused(experiments: Database) -> None:
    with pytest.raises(UnsupportedQueryException, match="expected a SELECT"):
        lower("DELETE FROM table_b", experiments)


# --- Generation -------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "SELECT g1, g2, SUM(v1) AS total_v1 FROM table_b WHERE g0 = 'xxx' GROUP BY 1, 2",
        "SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1 ORDER BY 1",
        "SELECT COUNT(*) AS n FROM table_b",
        "SELECT b_id, g1 FROM table_b WHERE v1 > 5",
        "SELECT g1, MIN(v1) AS lo, MAX(v1) AS hi FROM table_b GROUP BY 1",
    ],
)
def test_round_trip_preserves_query_meaning(query: str, experiments: Database) -> None:
    once = render(lower(query, experiments), experiments)
    # Re-lowering the generated SQL must reach the same place, which is what
    # the rewriters rely on when they re-analyse a tree they just produced.
    twice = render(lower(once, experiments), experiments)
    assert equivalent(once, twice, experiments.sqlglot_dialect)


def test_generated_sql_keeps_the_output_column_names(experiments: Database) -> None:
    sql = render(
        lower("SELECT g1, SUM(v1) AS total_v1 FROM table_b GROUP BY 1", experiments),
        experiments,
    )
    assert "AS total_v1" in sql
    assert "GROUP BY" in sql


def test_subquery_alias_becomes_a_derived_table(experiments: Database) -> None:
    inner = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    sql = render(SubqueryAlias(inner, "t0"), experiments)
    assert "AS t0" in sql


def test_cte_is_hoisted_to_the_head_of_the_query(experiments: Database) -> None:
    body = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    definition = Scan("g1_g2_domain", ("g1",))
    # The CTE is buried under a Sort, where SQL does not allow it.
    rel = Sort(WithTable("_domain", definition, body), ())
    sql = render(rel, experiments)
    assert sql.startswith("WITH _domain AS")


def test_right_join_renders_with_its_condition(experiments: Database) -> None:
    left = SubqueryAlias(
        lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments), "t0"
    )
    right = Scan("g1_domain", ("g1",))
    joined = Join(left, right, None, join_type="RIGHT")
    rel = Project(joined, (InputRef(2), InputRef(1)), ("g1", "n"))
    sql = render(rel, experiments)
    assert "RIGHT JOIN" in sql
