"""The public pipeline: SQL in, private SQL plus budget cost out.

Port of ``com.uber.engsec.dp.rewriting.BasicPipeline``. This is the entry point
callers use, and it mirrors the Scala signatures the existing consumers depend
on:

===========================================  ==================================
Scala                                        Python
===========================================  ==================================
``BasicPipeline.rewriteFixedPipeline``       :func:`rewrite_fixed_pipeline`
``BasicPipeline.BudgetUsage``                :func:`budget_usage`
===========================================  ==================================

The pipeline refuses a query before rewriting it when the query is not
releasable in principle — if it exposes a tainted column, or if it would return
raw rows rather than aggregates. Those are not noise problems, so no mechanism
fixes them.
"""

from __future__ import annotations

from .analysis.histogram import HistogramAnalysis
from .analysis.taint import TaintAnalysis
from .exceptions import UnsupportedQueryException
from .relalg.from_sql import parse_to_rel_tree
from .relalg.nodes import AggFunction, Rel
from .rewriting.clipping import ClippingRewriter
from .rewriting.reduce import count_releases, reduce_aggregate_functions
from .rewriting.rewriter import RewriterConfig
from .rewriting.sensitivity import GlobalSensitivityConfig, GlobalSensitivityRewriter
from .schema import Database

#: Aggregations answered by a binned PDF/CDF rather than by added noise. A
#: single noisy distribution serves all of them at once, so several such
#: columns over the same input cost one release between them.
_PERCENTILE_FUNCTIONS = frozenset(
    {AggFunction.MIN, AggFunction.MAX, AggFunction.PERCENTILE}
)


def budget_usage(database: Database, query: str, epsilon: float) -> float:
    """Privacy budget ``query`` would spend at ``epsilon``.

    Each private release costs ``epsilon``, and sequential composition adds
    them up. An ``AVG`` is two releases (a sum and a count) and a ``VAR`` is
    three; percentile-style aggregations over the same column share one noisy
    distribution, so they are counted once per distinct input.

    Raises:
        UnsupportedQueryException: if the query is not an aggregation query.
    """
    root = parse_to_rel_tree(query, database)
    return _budget_usage(root, database, epsilon)


def rewrite_fixed_pipeline(
    database: Database, query: str, epsilon: float
) -> tuple[str, float]:
    """Rewrite ``query`` into a differentially private query.

    Returns the rewritten SQL and the privacy budget it spends. Deducting that
    budget from the analyst's remaining allowance is the caller's job: this
    function is stateless, and running the returned query more than once spends
    the budget again.

    Raises:
        UnsupportedQueryException: the query shape has no sound mechanism.
        RewritingException: the schema lacks metadata the mechanism needs, such
            as ``clipLower``/``clipUpper`` bounds or a ``domainSet``.
        ProtectedBinException: a group-by column is not marked ``canRelease``.
    """
    root = parse_to_rel_tree(query, database)
    _reject_unreleasable(root, database)
    spent = _budget_usage(root, database, epsilon)

    reduced = reduce_aggregate_functions(root)
    clipped = ClippingRewriter(RewriterConfig(database)).rewrite(reduced)

    config = GlobalSensitivityConfig(database=database, epsilon=epsilon)
    result = GlobalSensitivityRewriter(config).run(clipped)

    return result.to_sql(), spent


def _raw_columns(root: Rel, histogram) -> list[str]:
    """Output columns that are neither aggregated nor grouped."""
    return [
        name
        for name, fact in zip(root.row_type, histogram)
        if not fact.is_aggregation and not fact.is_group_by and fact.references
    ]


def _reject_unreleasable(root: Rel, database: Database) -> None:
    """Refuse queries no amount of noise could make safe."""
    taint = TaintAnalysis().run(root, database).col_facts
    if any(taint):
        tainted = [name for name, is_tainted in zip(root.row_type, taint) if is_tainted]
        raise UnsupportedQueryException(
            f"query exposes tainted column(s): {', '.join(tainted)}"
        )

    histogram = HistogramAnalysis().run(root, database).col_facts
    raw = _raw_columns(root, histogram)
    if raw:
        raise UnsupportedQueryException(
            f"query contains non-aggregation column(s): {', '.join(raw)}. Only "
            "aggregations and the columns they are grouped by can be released."
        )


def _budget_usage(root: Rel, database: Database, epsilon: float) -> float:
    histogram = HistogramAnalysis().run(root, database).col_facts

    raw = _raw_columns(root, histogram)
    if raw:
        raise UnsupportedQueryException(
            f"query contains non-aggregation column(s): {', '.join(raw)}"
        )

    aggregations = [fact for fact in histogram if fact.is_aggregation]

    # Percentile columns sharing the same input share one noisy distribution,
    # so MIN(v) and MAX(v) together cost a single release.
    percentile_inputs = {
        fact.references
        for fact in aggregations
        if fact.outermost_aggregation in _PERCENTILE_FUNCTIONS
    }

    histogram_releases = sum(
        count_releases(fact.outermost_aggregation)
        for fact in aggregations
        if fact.outermost_aggregation is not None
        and fact.outermost_aggregation not in _PERCENTILE_FUNCTIONS
    )

    return epsilon * len(percentile_inputs) + epsilon * histogram_releases
