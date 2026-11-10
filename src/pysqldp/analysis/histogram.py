"""Histogram analysis.

Port of ``com.uber.engsec.dp.analysis.histogram.HistogramAnalysis``. For each
output column it reports whether the column is an aggregation, which aggregate
function is outermost, whether it is a group-by bin, which database columns its
value derives from, and whether anything modified that value along the way.

Nearly everything downstream depends on this: the clipping rewriter uses
``references`` to find the schema column to read bounds from, the bin filler
uses it to find the ``domainSet`` table, and the pipeline uses
``is_aggregation`` / ``is_group_by`` to reject queries that would release raw
rows.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..dataflow.column_analysis import NodeColumnFacts, RelNodeColumnAnalysis
from ..dataflow.domain import (
    FLAT_LATTICE_DOMAIN,
    UNIT_DOMAIN,
    AbstractDomain,
    FlatLatticeDomain,
)
from ..relalg.nodes import AggFunction, Aggregate, Expr, InputRef, Scan


@dataclass(frozen=True)
class QualifiedColumnName:
    """A database column, as ``table.column``. ``column`` may be ``"*"``."""

    table: str
    column: str

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.table}.{self.column}"


@dataclass(frozen=True)
class AggregationInfo:
    """What is known about one output column.

    Attributes:
        is_aggregation: the column is an aggregation of some kind.
        outermost_aggregation: the outermost aggregate function applied, or
            None when there is none or no single one.
        references: every database column influencing this column's value.
        value_modified: some function or expression was applied. When this is
            false, the column's values correspond exactly to values stored in
            ``references`` — which is what makes bin filling sound.
        is_group_by: the column is a ``GROUP BY`` key.
    """

    is_aggregation: bool = False
    outermost_aggregation_elem: object = None
    references: frozenset[QualifiedColumnName] = frozenset()
    value_modified: bool = False
    is_group_by: bool = False

    @property
    def outermost_aggregation(self) -> AggFunction | None:
        value = FlatLatticeDomain.value_of(self.outermost_aggregation_elem)
        return value if isinstance(value, AggFunction) else None


class AggregationDomain(AbstractDomain[AggregationInfo]):
    """Port of ``AggregationDomain``."""

    @property
    def bottom(self) -> AggregationInfo:
        return AggregationInfo(
            is_aggregation=False,
            outermost_aggregation_elem=FLAT_LATTICE_DOMAIN.bottom,
            references=frozenset(),
            value_modified=False,
            is_group_by=False,
        )

    def least_upper_bound(
        self, left: AggregationInfo, right: AggregationInfo
    ) -> AggregationInfo:
        return AggregationInfo(
            is_aggregation=left.is_aggregation or right.is_aggregation,
            outermost_aggregation_elem=FLAT_LATTICE_DOMAIN.least_upper_bound(
                left.outermost_aggregation_elem, right.outermost_aggregation_elem
            ),
            references=left.references | right.references,
            value_modified=left.value_modified or right.value_modified,
            is_group_by=left.is_group_by or right.is_group_by,
        )


AGGREGATION_DOMAIN = AggregationDomain()


class HistogramAnalysis(RelNodeColumnAnalysis[None, AggregationInfo]):
    """Reports the aggregation status and provenance of each output column."""

    def __init__(self) -> None:
        super().__init__(UNIT_DOMAIN, AGGREGATION_DOMAIN)

    def transfer_table_scan(
        self, node: Scan, state: NodeColumnFacts[None, AggregationInfo]
    ) -> NodeColumnFacts[None, AggregationInfo]:
        col_facts = tuple(
            replace(fact, references=frozenset({QualifiedColumnName(node.table, name)}))
            for fact, name in zip(state.col_facts, node.columns)
        )
        return NodeColumnFacts(UNIT_DOMAIN.bottom, col_facts)

    def transfer_aggregate(
        self,
        node: Aggregate,
        agg_functions: tuple[AggFunction | None, ...],
        state: NodeColumnFacts[None, AggregationInfo],
    ) -> NodeColumnFacts[None, AggregationInfo]:
        col_facts = []
        for fact, agg in zip(state.col_facts, agg_functions):
            if agg is None:  # a grouped column
                col_facts.append(replace(fact, is_group_by=True))
                continue

            if agg is AggFunction.COUNT:
                # A count depends on whole rows, not on particular values, so
                # provenance collapses to one `table.*` entry per source table.
                references = frozenset(
                    QualifiedColumnName(ref.table, "*") for ref in fact.references
                )
            else:
                references = fact.references

            col_facts.append(
                AggregationInfo(
                    is_aggregation=True,
                    outermost_aggregation_elem=agg,
                    references=references,
                    value_modified=True,
                    is_group_by=False,
                )
            )

        return NodeColumnFacts(UNIT_DOMAIN.bottom, tuple(col_facts))

    def transfer_expression(self, node: Expr, state: AggregationInfo) -> AggregationInfo:
        if isinstance(node, InputRef):
            return state
        return replace(state, value_modified=True)
