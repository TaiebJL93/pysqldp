"""The dataflow analysis engine.

Port of ``com.uber.engsec.dp.dataflow.column.RelNodeColumnAnalysis``. An
analysis tracks two kinds of fact in tandem:

* a **node fact** about the relation as a whole (e.g. its stability), and
* a **column fact** per output field (e.g. that field's sensitivity),

because each informs the other: the sensitivity of a ``COUNT`` column is the
stability of the relation underneath it.

Facts flow bottom-up. For each relation, :meth:`_join_node` assembles the
incoming state from the already-computed children, then the subclass's
``transfer_*`` hook updates it. Expressions inside a ``Project`` are walked the
same way, so analyses can observe per-expression structure — which is how
``SimpleSensitivityAnalysis`` recovers clipping bounds from the ``CASE`` that
``ClippingRewriter`` inserted.

Subclasses override only the hooks they care about; every hook defaults to
passing the state through unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar

from ..exceptions import AnalysisException
from ..relalg.nodes import (
    AggFunction,
    Aggregate,
    Call,
    Expr,
    Filter,
    InputRef,
    Join,
    Literal,
    Project,
    Rel,
    Scan,
    Sort,
    SubqueryAlias,
    WithTable,
)
from ..schema import Database
from .domain import AbstractDomain

N = TypeVar("N")
C = TypeVar("C")


@dataclass(frozen=True)
class NodeColumnFacts(Generic[N, C]):
    """A node fact paired with one column fact per output field."""

    node_fact: N
    col_facts: tuple[C, ...]

    def with_node_fact(self, node_fact: N) -> NodeColumnFacts[N, C]:
        return NodeColumnFacts(node_fact, self.col_facts)

    def with_col_facts(self, col_facts: Sequence[C]) -> NodeColumnFacts[N, C]:
        return NodeColumnFacts(self.node_fact, tuple(col_facts))


class RelNodeColumnAnalysis(Generic[N, C]):
    """Base class for analyses over the relational IR."""

    def __init__(
        self,
        node_domain: AbstractDomain[N],
        col_domain: AbstractDomain[C],
    ) -> None:
        self.node_domain = node_domain
        self.col_domain = col_domain
        self._database: Database | None = None
        self._results: dict[int, NodeColumnFacts[N, C]] = {}
        # Facts for each CTE, keyed by alias, so a scan of a CTE picks up the
        # definition's facts instead of looking the name up in the schema.
        self._cte_facts: dict[str, NodeColumnFacts[N, C]] = {}

    # --- Entry point --------------------------------------------------------

    def run(self, root: Rel, database: Database) -> NodeColumnFacts[N, C]:
        """Analyse ``root`` and return the facts for its output."""
        self._database = database
        self._results = {}
        self._cte_facts = {}
        return self._visit(root)

    @property
    def database(self) -> Database:
        if self._database is None:
            raise AnalysisException("analysis has not been run yet")
        return self._database

    def facts_for(self, rel: Rel) -> NodeColumnFacts[N, C]:
        """Facts computed for ``rel`` during the last :meth:`run`."""
        try:
            return self._results[id(rel)]
        except KeyError as err:
            raise AnalysisException(
                f"no facts recorded for {type(rel).__name__}; it was not part "
                "of the analysed tree"
            ) from err

    # --- Traversal ----------------------------------------------------------

    def _visit(self, rel: Rel) -> NodeColumnFacts[N, C]:
        cached = self._results.get(id(rel))
        if cached is not None:
            return cached

        if isinstance(rel, WithTable):
            # Analyse the CTE first so scans of it resolve, then take the
            # body's facts as this node's, since the body shapes the output.
            self._cte_facts[rel.alias] = self._visit(rel.definition)
            facts = self._visit(rel.body)
        else:
            child_facts = [self._visit(child) for child in rel.inputs]
            facts = self._transfer(rel, self._join_node(rel, child_facts))

        if len(facts.col_facts) != rel.field_count:
            raise AnalysisException(
                f"{type(rel).__name__} produced {len(facts.col_facts)} column "
                f"fact(s) for {rel.field_count} output field(s)"
            )
        self._results[id(rel)] = facts
        return facts

    def _cte_lookup(self, table: str) -> NodeColumnFacts[N, C] | None:
        return self._cte_facts.get(table) or self._cte_facts.get(
            table.rsplit(".", 1)[-1]
        )

    def _join_node(
        self, rel: Rel, child_facts: list[NodeColumnFacts[N, C]]
    ) -> NodeColumnFacts[N, C]:
        """Assemble the state arriving at ``rel`` from its children."""
        if isinstance(rel, Scan):
            cte = self._cte_lookup(rel.table)
            if cte is not None:
                return cte
            return NodeColumnFacts(
                self.node_domain.bottom,
                tuple(self.col_domain.bottom for _ in rel.columns),
            )

        if isinstance(rel, (Filter, Sort, SubqueryAlias)):
            return child_facts[0]

        if isinstance(rel, Project):
            (incoming,) = child_facts
            col_facts = tuple(
                self._expr_fact(expr, incoming.col_facts) for expr in rel.exprs
            )
            return NodeColumnFacts(incoming.node_fact, col_facts)

        if isinstance(rel, Aggregate):
            (incoming,) = child_facts
            input_facts = incoming.col_facts

            group_facts = [input_facts[i] for i in rel.group_keys]
            agg_facts = []
            for call in rel.agg_calls:
                # COUNT(*) reads no column in particular, so it depends on all
                # of them, exactly as Calcite's empty arg list implies.
                sources = (
                    [input_facts[i] for i in call.args]
                    if call.args
                    else list(input_facts)
                )
                agg_facts.append(self.col_domain.join(sources))

            return NodeColumnFacts(incoming.node_fact, tuple(group_facts + agg_facts))

        if isinstance(rel, Join):
            left, right = child_facts
            return NodeColumnFacts(
                self.node_domain.least_upper_bound(left.node_fact, right.node_fact),
                left.col_facts + right.col_facts,
            )

        raise AnalysisException(f"unhandled relation node type {type(rel).__name__}")

    def _expr_fact(self, expr: Expr, input_facts: tuple[C, ...]) -> C:
        """The column fact produced by a scalar expression."""
        if isinstance(expr, InputRef):
            # State was already propagated to the referenced field; no transfer
            # function runs, matching the Scala RexInputRef case.
            try:
                return input_facts[expr.idx]
            except IndexError as err:
                raise AnalysisException(
                    f"InputRef({expr.idx}) is out of range for "
                    f"{len(input_facts)} input field(s)"
                ) from err

        if isinstance(expr, Literal):
            return self.transfer_expression(expr, self.col_domain.bottom)

        if isinstance(expr, Call):
            children = [self._expr_fact(arg, input_facts) for arg in expr.args]
            return self.transfer_expression(expr, self.col_domain.join(children))

        raise AnalysisException(f"unhandled expression type {type(expr).__name__}")

    def _transfer(
        self, rel: Rel, state: NodeColumnFacts[N, C]
    ) -> NodeColumnFacts[N, C]:
        if isinstance(rel, Scan):
            if self._cte_lookup(rel.table) is not None:
                # Facts came from the CTE definition; re-running the table-scan
                # hook would try to look a nonexistent table up in the schema.
                return state
            return self.transfer_table_scan(rel, state)
        if isinstance(rel, Filter):
            return self.transfer_filter(rel, state)
        if isinstance(rel, Project):
            return self.transfer_project(rel, state)
        if isinstance(rel, Aggregate):
            agg_functions = tuple(rel.agg_function_at(i) for i in range(rel.field_count))
            return self.transfer_aggregate(rel, agg_functions, state)
        if isinstance(rel, Join):
            return self.transfer_join(rel, state)
        if isinstance(rel, Sort):
            return self.transfer_sort(rel, state)
        if isinstance(rel, SubqueryAlias):
            return self.transfer_subquery_alias(rel, state)
        raise AnalysisException(f"unhandled relation node type {type(rel).__name__}")

    # --- Hooks for subclasses ----------------------------------------------

    def transfer_table_scan(
        self, node: Scan, state: NodeColumnFacts[N, C]
    ) -> NodeColumnFacts[N, C]:
        return state

    def transfer_filter(
        self, node: Filter, state: NodeColumnFacts[N, C]
    ) -> NodeColumnFacts[N, C]:
        return state

    def transfer_project(
        self, node: Project, state: NodeColumnFacts[N, C]
    ) -> NodeColumnFacts[N, C]:
        return state

    def transfer_aggregate(
        self,
        node: Aggregate,
        agg_functions: tuple[AggFunction | None, ...],
        state: NodeColumnFacts[N, C],
    ) -> NodeColumnFacts[N, C]:
        """``agg_functions[i]`` is None when output field ``i`` is a group key."""
        return state

    def transfer_join(
        self, node: Join, state: NodeColumnFacts[N, C]
    ) -> NodeColumnFacts[N, C]:
        return state

    def transfer_sort(
        self, node: Sort, state: NodeColumnFacts[N, C]
    ) -> NodeColumnFacts[N, C]:
        return state

    def transfer_subquery_alias(
        self, node: SubqueryAlias, state: NodeColumnFacts[N, C]
    ) -> NodeColumnFacts[N, C]:
        return state

    def transfer_expression(self, node: Expr, state: C) -> C:
        return state
