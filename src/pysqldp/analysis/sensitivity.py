"""Global (stability-based) sensitivity analysis.

Port of ``com.uber.engsec.dp.analysis.differential_privacy``'s
``SimpleSensitivityAnalysis``, plus the ``StabilityDomain`` and
``SensitivityDomain`` it works over.

The analysis tracks the *stability* of the relational transformation the query
encodes, in the style of PINQ, and reports each aggregated column's global L1
sensitivity from it. For a query ``q`` with sensitivity ``s``:

    d(x, y) <= 1  =>  ||q(x) - q(y)||_1 <= s

so adding Laplace noise scaled to ``s / epsilon`` gives epsilon-differential
privacy. The number computed here is a conservative upper bound.

Scope, inherited from the Scala original: single-table ``SELECT`` queries.
Joins and aggregations other than ``COUNT``/``SUM`` yield infinite sensitivity,
which the rewriter turns into a hard error rather than an under-noised query.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..dataflow.column_analysis import NodeColumnFacts, RelNodeColumnAnalysis
from ..dataflow.domain import AbstractDomain
from ..exceptions import ProtectedBinException
from ..relalg.nodes import (
    NON_ARITHMETIC_OPS,
    OP_CASE,
    OP_GT,
    OP_LT,
    AggFunction,
    Aggregate,
    Call,
    Expr,
    Literal,
    Scan,
)
from ..schema import get_schema_map_for_table


@dataclass(frozen=True)
class RelStability:
    """Node-level fact: how much the relation can change per changed input row.

    Attributes:
        stability: the relation's stability, as defined by elastic sensitivity.
        is_public: the relation holds only publicly-derived data. Joining a
            public table with a protected one makes the whole relation
            non-public.
        ancestors: source tables beneath this node, used to detect self-joins.
    """

    stability: float = 1.0
    is_public: bool = False
    ancestors: frozenset[str] = frozenset()


class StabilityDomain(AbstractDomain[RelStability]):
    """Product lattice over :class:`RelStability`, ordered pointwise."""

    @property
    def bottom(self) -> RelStability:
        return RelStability(stability=1.0, is_public=False, ancestors=frozenset())

    def least_upper_bound(self, left: RelStability, right: RelStability) -> RelStability:
        return RelStability(
            stability=max(left.stability, right.stability),
            is_public=left.is_public and right.is_public,
            ancestors=left.ancestors | right.ancestors,
        )


@dataclass(frozen=True)
class ColSensitivity:
    """Column-level fact.

    Attributes:
        sensitivity: upper bound on this column's local sensitivity. ``None``
            is bottom (undefined until an aggregation is applied) and ``inf``
            is top (unbounded); the order is by ``max``.
        max_freq: maximum number of rows sharing a value of this column.
        aggregation_applied: an aggregation has already been applied.
        post_aggregation_arithmetic_applied: an operation was applied to an
            already-aggregated value. Tracked only so the error message can say
            why sensitivity became infinite.
        can_release: the column's values may be released without noise. True
            for public tables and for columns marked ``canRelease``, and for
            values derived from them. Boolean lattice with bottom ``True``.
        upper_bound: clipping upper bound recovered from a ``CASE``.
        lower_bound: clipping lower bound recovered from a ``CASE``.
    """

    sensitivity: float | None = None
    max_freq: float = 0.0
    aggregation_applied: bool = False
    post_aggregation_arithmetic_applied: bool = False
    can_release: bool = True
    upper_bound: float | None = None
    lower_bound: float | None = None


class SensitivityDomain(AbstractDomain[ColSensitivity]):
    """Product lattice over :class:`ColSensitivity`, ordered pointwise."""

    @property
    def bottom(self) -> ColSensitivity:
        return ColSensitivity(
            sensitivity=None,
            max_freq=0.0,
            aggregation_applied=False,
            post_aggregation_arithmetic_applied=False,
            can_release=True,
            upper_bound=None,
            lower_bound=None,
        )

    def least_upper_bound(
        self, left: ColSensitivity, right: ColSensitivity
    ) -> ColSensitivity:
        return ColSensitivity(
            sensitivity=_combine(left.sensitivity, right.sensitivity, max),
            max_freq=max(left.max_freq, right.max_freq),
            aggregation_applied=left.aggregation_applied or right.aggregation_applied,
            post_aggregation_arithmetic_applied=(
                left.post_aggregation_arithmetic_applied
                or right.post_aggregation_arithmetic_applied
            ),
            can_release=left.can_release and right.can_release,
            upper_bound=_combine(left.upper_bound, right.upper_bound, max),
            lower_bound=_combine(left.lower_bound, right.lower_bound, min),
        )


def _combine(left: float | None, right: float | None, pick) -> float | None:
    """Merge two optional numbers, ignoring the undefined ones."""
    present = [v for v in (left, right) if v is not None]
    if not present:
        return None
    result = present[0]
    for value in present[1:]:
        result = pick(result, value)
    return result


STABILITY_DOMAIN = StabilityDomain()
SENSITIVITY_DOMAIN = SensitivityDomain()


class SimpleSensitivityAnalysis(RelNodeColumnAnalysis[RelStability, ColSensitivity]):
    """Global sensitivity from relational stability, PINQ style.

    Args:
        check_bins_for_release: raise :class:`ProtectedBinException` when a
            histogram bin column is not marked ``canRelease``. Leave this on:
            releasing un-noised bin labels leaks which values exist in the data.
    """

    def __init__(self, check_bins_for_release: bool = True) -> None:
        super().__init__(STABILITY_DOMAIN, SENSITIVITY_DOMAIN)
        self.check_bins_for_release = check_bins_for_release

    def transfer_table_scan(
        self, node: Scan, state: NodeColumnFacts[RelStability, ColSensitivity]
    ) -> NodeColumnFacts[RelStability, ColSensitivity]:
        table = self.database.table(node.table)
        is_public = table.is_public
        columns = get_schema_map_for_table(self.database, node.table)

        col_facts = tuple(
            replace(
                fact,
                can_release=columns[name].bool_property("canRelease") or is_public,
            )
            for fact, name in zip(state.col_facts, node.columns)
        )

        node_fact = replace(
            state.node_fact, stability=1.0, ancestors=frozenset({node.table})
        )
        return NodeColumnFacts(node_fact, col_facts)

    def transfer_aggregate(
        self,
        node: Aggregate,
        agg_functions: tuple[AggFunction | None, ...],
        state: NodeColumnFacts[RelStability, ColSensitivity],
    ) -> NodeColumnFacts[RelStability, ColSensitivity]:
        grouped = sum(1 for agg in agg_functions if agg is None)

        # Grouping doubles the relation's stability: one changed input row can
        # move a count in the bin it left and the bin it joined.
        node_fact = (
            replace(state.node_fact, stability=2 * state.node_fact.stability)
            if grouped > 0
            else state.node_fact
        )

        col_facts = []
        for idx, (fact, agg) in enumerate(zip(state.col_facts, agg_functions)):
            if agg is None:  # histogram bin
                if self.check_bins_for_release and not fact.can_release:
                    raise ProtectedBinException(node.row_type[idx])
                # Bins that are safe for release need no noise.
                col_facts.append(replace(fact, sensitivity=0.0))
                continue

            col_facts.append(
                replace(
                    fact,
                    sensitivity=self._aggregate_sensitivity(agg, fact, node_fact),
                    max_freq=math.inf,
                    aggregation_applied=True,
                    post_aggregation_arithmetic_applied=fact.aggregation_applied,
                    can_release=True,
                    upper_bound=None,
                    lower_bound=None,
                )
            )

        return NodeColumnFacts(node_fact, tuple(col_facts))

    @staticmethod
    def _aggregate_sensitivity(
        agg: AggFunction, fact: ColSensitivity, node_fact: RelStability
    ) -> float:
        if agg is AggFunction.COUNT:
            # Removing or adding one row moves a count by at most 1, so the
            # column's sensitivity is just the relation's stability.
            return node_fact.stability

        if agg is AggFunction.SUM:
            if fact.lower_bound is None or fact.upper_bound is None:
                # Unclipped SUM is unbounded: one row can carry any value.
                return math.inf
            return node_fact.stability * (fact.upper_bound - fact.lower_bound)

        # MIN, MAX, AVG, VAR, STDDEV and percentiles need their own mechanisms;
        # reporting infinity here makes the rewriter refuse rather than
        # under-noise.
        return math.inf

    def transfer_expression(self, node: Expr, state: ColSensitivity) -> ColSensitivity:
        if not isinstance(node, Call):
            # Any other node could alter values arbitrarily, invalidating the
            # frequency bound.
            return replace(state, max_freq=math.inf)

        if node.op == OP_CASE:
            bound = self._case_bound(node)
            if bound is None:
                return replace(state, sensitivity=math.inf, max_freq=math.inf)
            side, value = bound
            if side == "upper":
                return replace(
                    state, sensitivity=math.inf, max_freq=math.inf, upper_bound=value
                )
            return replace(
                state, sensitivity=math.inf, max_freq=math.inf, lower_bound=value
            )

        is_arithmetic = node.op not in NON_ARITHMETIC_OPS
        return replace(
            state,
            sensitivity=math.inf,
            max_freq=math.inf,
            post_aggregation_arithmetic_applied=(
                state.aggregation_applied and is_arithmetic
            ),
        )

    @staticmethod
    def _case_bound(node: Call) -> tuple[str, float] | None:
        """Recover a clipping bound from the CASE the clipping rewriter emitted.

        ``ClippingRewriter`` emits ``CASE WHEN c < lo THEN lo ELSE
        (CASE WHEN c > hi THEN hi ELSE c END) END``, so a comparison against a
        numeric literal in the THEN branch identifies which bound this is.
        """
        if len(node.args) != 3:
            return None
        comparison, then, _ = node.args
        if not isinstance(comparison, Call):
            return None
        if not isinstance(then, Literal) or not then.is_numeric:
            return None
        if comparison.op == OP_GT:
            return "upper", float(then.value)
        if comparison.op == OP_LT:
            return "lower", float(then.value)
        return None
