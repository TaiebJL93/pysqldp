"""Taint analysis.

Port of ``com.uber.engsec.dp.analysis.taint.TaintAnalysis``. Reports, per output
column, whether its value could have flowed from a column the schema marks
``isTainted``.

The pipeline runs this first and refuses any query whose output depends on a
tainted column, regardless of how much noise would be added — some columns are
simply not for release in any form.

Propagation needs no transfer functions beyond the table scan: the engine
already joins a column's facts from the expressions and aggregate arguments it
derives from, and taint is exactly that join under boolean or.
"""

from __future__ import annotations

from ..dataflow.column_analysis import NodeColumnFacts, RelNodeColumnAnalysis
from ..dataflow.domain import BOOLEAN_DOMAIN, UNIT_DOMAIN
from ..relalg.nodes import Scan
from ..schema import get_schema_map_for_table


class TaintAnalysis(RelNodeColumnAnalysis[None, bool]):
    """True for each output column that may carry data from a tainted column."""

    def __init__(self) -> None:
        super().__init__(UNIT_DOMAIN, BOOLEAN_DOMAIN)

    def transfer_table_scan(
        self, node: Scan, state: NodeColumnFacts[None, bool]
    ) -> NodeColumnFacts[None, bool]:
        columns = get_schema_map_for_table(self.database, node.table)
        col_facts = tuple(
            columns[name].bool_property("isTainted") for name in node.columns
        )
        return NodeColumnFacts(UNIT_DOMAIN.bottom, col_facts)
