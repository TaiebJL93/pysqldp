"""Clipping rewriter.

Port of ``com.uber.engsec.dp.rewriting.ClippingRewriter``. Constrains the inputs
of an aggregation to a range, which is what makes ``SUM`` and ``AVG`` have
bounded sensitivity at all.

An unclipped ``SUM`` has unbounded sensitivity: a single row can carry an
arbitrarily large value, so no finite amount of noise hides its presence. Once
values are clamped to ``[lower, upper]``, adding or removing one row can move
the sum by at most ``upper - lower``, and that difference becomes the
sensitivity the Laplace mechanism scales to.

This rewriter must run *before* the sensitivity analysis: the analysis recovers
the bounds by pattern-matching the ``CASE`` emitted here.
"""

from __future__ import annotations

from ..analysis.histogram import AggregationInfo, HistogramAnalysis
from ..dataflow.domain import UNIT_DOMAIN
from ..exceptions import RewritingException
from ..relalg.expr import case, gt, lit, lt
from ..relalg.nodes import AggFunction, Aggregate, Expr, Rel
from ..relalg.ops import ColumnDef, map_cols
from ..schema import get_schema_map_for_table
from .rewriter import Rewriter, rewrite_recursive


def clamp(expr: Expr, lower: float, upper: float) -> Expr:
    """Clamp ``expr`` into ``[lower, upper]`` with nested ``CASE`` expressions."""
    return case(
        lt(expr, lower),
        lit(lower),
        case(gt(expr, upper), lit(upper), expr),
    )


class ClippingRewriter(Rewriter[None]):
    """Clamps aggregation inputs to their schema-declared bounds."""

    def rewrite(self, root: Rel) -> Rel:
        rewritten, _ = rewrite_recursive(root, UNIT_DOMAIN, self._transform)
        return rewritten

    def _transform(self, node: Rel, original: Rel, _: None) -> tuple[Rel, None]:
        if not isinstance(node, Aggregate):
            return node, None

        aggregated_inputs = {idx for call in node.agg_calls for idx in call.args}
        # COUNT does not read values, only rows, so clipping its input would
        # change nothing and may touch a column that has no bounds declared.
        value_inputs = {
            idx
            for call in node.agg_calls
            if call.func is not AggFunction.COUNT
            for idx in call.args
        }

        source = node.input
        histogram = HistogramAnalysis().run(source, self.database).col_facts

        clipped_source = map_cols(
            source,
            lambda column: self._clip_column(
                column, histogram, aggregated_inputs, value_inputs
            ),
        )
        return node.with_inputs([clipped_source]), None

    def _clip_column(
        self,
        column: ColumnDef,
        histogram: tuple[AggregationInfo, ...],
        aggregated_inputs: set[int],
        value_inputs: set[int],
    ) -> ColumnDef:
        if column.idx not in aggregated_inputs or column.idx not in value_inputs:
            return column

        info = histogram[column.idx]
        reference_count = len(info.references)

        if reference_count == 0:
            # A constant argument, such as the 0.3 in PERCENTILE(amount, 0.3).
            return column

        if reference_count > 1:
            raise RewritingException(
                f"column {column.alias!r} must derive its values from exactly "
                "one database column to be clipped, but derives from "
                f"{reference_count}"
            )

        reference = next(iter(info.references))
        if reference.column == "*":
            return column

        columns = get_schema_map_for_table(self.database, reference.table)
        schema_column = columns[reference.column]
        lower = schema_column.float_property("clipLower")
        upper = schema_column.float_property("clipUpper")

        if lower is None or upper is None:
            raise RewritingException(
                f"column {reference.column!r} in table {reference.table!r} is "
                "missing clipping information. Define 'clipLower' and "
                "'clipUpper' to specify the bounds ClippingRewriter should use."
            )
        if upper - lower < 1:
            # Otherwise SUM over a narrow range degenerates into a row count,
            # which would then be reported with SUM's sensitivity rather than
            # COUNT's.
            raise RewritingException(
                f"column {reference.column!r} in table {reference.table!r} has "
                f"clipUpper - clipLower = {upper - lower}, which must be at "
                "least 1 to prevent using SUM to count filtered rows"
            )

        return column.aliased(clamp(column.expr, lower, upper))
