"""The static analyses: histogram shape, taint, and sensitivity."""

from __future__ import annotations

import math

import pytest

from pysqldp.analysis import HistogramAnalysis, SimpleSensitivityAnalysis, TaintAnalysis
from pysqldp.exceptions import ProtectedBinException
from pysqldp.relalg import AggFunction, parse_to_rel_tree
from pysqldp.rewriting.clipping import ClippingRewriter
from pysqldp.rewriting.rewriter import RewriterConfig
from pysqldp.schema import Database


def lower(query: str, database: Database):
    return parse_to_rel_tree(query, database)


# --- Histogram analysis -----------------------------------------------------


def test_classifies_bins_and_aggregations(experiments: Database) -> None:
    rel = lower(
        "SELECT g1, g2, SUM(v1) AS total FROM table_b GROUP BY 1, 2", experiments
    )
    facts = HistogramAnalysis().run(rel, experiments).col_facts

    assert [f.is_group_by for f in facts] == [True, True, False]
    assert [f.is_aggregation for f in facts] == [False, False, True]
    assert facts[2].outermost_aggregation is AggFunction.SUM


def test_tracks_provenance_back_to_the_database_column(experiments: Database) -> None:
    rel = lower("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    facts = HistogramAnalysis().run(rel, experiments).col_facts

    bin_reference = next(iter(facts[0].references))
    assert (bin_reference.table, bin_reference.column) == ("table_b", "g1")

    sum_reference = next(iter(facts[1].references))
    assert (sum_reference.table, sum_reference.column) == ("table_b", "v1")


def test_count_provenance_collapses_to_the_whole_row(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    facts = HistogramAnalysis().run(rel, experiments).col_facts

    reference = next(iter(facts[1].references))
    assert (reference.table, reference.column) == ("table_b", "*")


def test_unmodified_bin_values_are_flagged_as_such(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    facts = HistogramAnalysis().run(rel, experiments).col_facts

    # Bin filling is only sound when the bin value is untouched, so this flag
    # gates it.
    assert facts[0].value_modified is False
    assert facts[1].value_modified is True


def test_clipping_marks_the_aggregated_value_as_modified(experiments: Database) -> None:
    rel = lower("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    clipped = ClippingRewriter(RewriterConfig(experiments)).rewrite(rel)
    facts = HistogramAnalysis().run(clipped, experiments).col_facts

    assert facts[0].value_modified is False
    assert facts[1].value_modified is True


# --- Taint analysis ---------------------------------------------------------


def test_untainted_query_reports_no_taint(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    assert not any(TaintAnalysis().run(rel, experiments).col_facts)


def test_taint_flows_from_the_tainted_column(test_db: Database) -> None:
    rel = lower("SELECT name, address FROM customers", test_db)
    assert list(TaintAnalysis().run(rel, test_db).col_facts) == [True, True]


def test_taint_survives_aggregation(test_db: Database) -> None:
    rel = lower("SELECT COUNT(name) AS n FROM customers", test_db)
    assert list(TaintAnalysis().run(rel, test_db).col_facts) == [True]


def test_untainted_columns_of_a_tainted_table_stay_clean(test_db: Database) -> None:
    rel = lower("SELECT customer_id FROM customers", test_db)
    assert list(TaintAnalysis().run(rel, test_db).col_facts) == [False]


# --- Sensitivity analysis ---------------------------------------------------


def test_ungrouped_count_has_sensitivity_one(experiments: Database) -> None:
    rel = lower("SELECT COUNT(*) AS n FROM table_b", experiments)
    facts = SimpleSensitivityAnalysis().run(rel, experiments).col_facts
    assert facts[0].sensitivity == 1.0


def test_grouping_doubles_the_stability(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    result = SimpleSensitivityAnalysis().run(rel, experiments)

    # One changed row can move the count in the bin it left and the bin it
    # joined, so a grouped count has sensitivity 2.
    assert result.node_fact.stability == 2.0
    assert result.col_facts[1].sensitivity == 2.0


def test_releasable_bins_need_no_noise(experiments: Database) -> None:
    rel = lower("SELECT g1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    facts = SimpleSensitivityAnalysis().run(rel, experiments).col_facts
    assert facts[0].sensitivity == 0.0


def test_protected_bin_is_rejected(experiments: Database) -> None:
    # ja1 is not marked canRelease, so its values must not appear in output.
    rel = lower("SELECT ja1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    with pytest.raises(ProtectedBinException, match="ja1"):
        SimpleSensitivityAnalysis().run(rel, experiments)


def test_bin_check_can_be_disabled_for_analysis_only_use(experiments: Database) -> None:
    rel = lower("SELECT ja1, COUNT(*) AS n FROM table_b GROUP BY 1", experiments)
    facts = (
        SimpleSensitivityAnalysis(check_bins_for_release=False)
        .run(rel, experiments)
        .col_facts
    )
    assert facts[1].sensitivity == 2.0


def test_unclipped_sum_has_unbounded_sensitivity(experiments: Database) -> None:
    rel = lower("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    facts = SimpleSensitivityAnalysis().run(rel, experiments).col_facts
    assert facts[1].sensitivity == math.inf


def test_clipped_sum_sensitivity_is_stability_times_the_range(
    experiments: Database,
) -> None:
    rel = lower("SELECT g1, SUM(v1) AS total FROM table_b GROUP BY 1", experiments)
    clipped = ClippingRewriter(RewriterConfig(experiments)).rewrite(rel)
    facts = SimpleSensitivityAnalysis().run(clipped, experiments).col_facts

    # v1 is declared clipLower 0, clipUpper 10000000; grouping doubles
    # stability to 2.
    assert facts[1].sensitivity == 2.0 * (10_000_000 - 0)


def test_clipping_bounds_are_recovered_from_the_case_expression(
    experiments: Database,
) -> None:
    rel = lower("SELECT SUM(v1) AS total FROM table_b", experiments)
    clipped = ClippingRewriter(RewriterConfig(experiments)).rewrite(rel)

    analysis = SimpleSensitivityAnalysis()
    analysis.run(clipped, experiments)
    # The aggregate's input is the clipped projection; its facts carry the
    # bounds the CASE encodes.
    input_facts = analysis.facts_for(clipped.input).col_facts
    v1 = experiments.table("table_b").column_names.index("v1")
    assert input_facts[v1].lower_bound == 0.0
    assert input_facts[v1].upper_bound == 10_000_000.0


def test_min_and_max_have_no_global_sensitivity_mechanism(
    experiments: Database,
) -> None:
    rel = lower("SELECT MIN(v1) AS lo, MAX(v1) AS hi FROM table_b", experiments)
    facts = SimpleSensitivityAnalysis().run(rel, experiments).col_facts
    assert [f.sensitivity for f in facts] == [math.inf, math.inf]
