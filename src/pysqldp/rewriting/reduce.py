"""Aggregate reduction: rewriting AVG into SUM and COUNT.

Stands in for Calcite's ``AggregateReduceFunctionsRule``, which the Scala
pipeline applies via ``RelUtils.functionsToReduce`` before handing a query to
``GlobalSensitivityRewriter``.

There is no mechanism for ``AVG`` directly, because an average is a ratio and
noise does not pass cleanly through division. Decomposing it means the two
halves each get noised under a mechanism that does exist, and the quotient of
two differentially private releases is still differentially private by
post-processing. The cost is that the query now makes two releases, so
sequential composition charges it twice the budget.
"""

from __future__ import annotations

from ..dataflow.domain import UNIT_DOMAIN
from ..relalg.expr import div
from ..relalg.nodes import (
    AggCall,
    AggFunction,
    Aggregate,
    Expr,
    InputRef,
    Project,
    Rel,
)
from .rewriter import rewrite_recursive

#: Aggregate functions that are decomposed rather than noised directly.
FUNCTIONS_TO_REDUCE = frozenset({AggFunction.AVG})


def reduce_aggregate_functions(root: Rel) -> Rel:
    """Replace every ``AVG(x)`` with ``SUM(x) / COUNT(x)``.

    The ``SUM`` and ``COUNT`` become real columns of the aggregation, so the
    noise rewriter treats them as ordinary aggregations; a projection above
    restores the original output shape by dividing them.
    """
    rewritten, _ = rewrite_recursive(root, UNIT_DOMAIN, _transform)
    return rewritten


def _transform(node: Rel, original: Rel, _: None) -> tuple[Rel, None]:
    if not isinstance(node, Aggregate):
        return node, None
    if not any(call.func in FUNCTIONS_TO_REDUCE for call in node.agg_calls):
        return node, None
    return _reduce_aggregate(node), None


def _reduce_aggregate(node: Aggregate) -> Project:
    new_calls: list[AggCall] = []
    new_names: list[str] = []
    projections: list[Expr] = [InputRef(i) for i in range(node.group_count)]

    for call, name in zip(node.agg_calls, node.agg_names):
        if call.func not in FUNCTIONS_TO_REDUCE:
            new_calls.append(call)
            new_names.append(name)
            projections.append(InputRef(node.group_count + len(new_calls) - 1))
            continue

        new_calls.append(AggCall(AggFunction.SUM, call.args, call.distinct))
        new_names.append(f"_sum_{name}")
        sum_field = node.group_count + len(new_calls) - 1

        new_calls.append(AggCall(AggFunction.COUNT, call.args, call.distinct))
        new_names.append(f"_count_{name}")
        count_field = node.group_count + len(new_calls) - 1

        projections.append(div(InputRef(sum_field), InputRef(count_field)))

    reduced = Aggregate(node.input, node.group_keys, tuple(new_calls), tuple(new_names))
    return Project(reduced, tuple(projections), node.row_type)


def count_releases(func: AggFunction) -> int:
    """How many private releases an aggregation of ``func`` costs.

    ``AVG`` is two (a sum and a count) and ``VAR``/``STDDEV`` are three;
    everything else is one. Sequential composition adds the budget of each
    release, so this is the multiplier on epsilon.
    """
    if func is AggFunction.AVG:
        return 2
    if func in (AggFunction.VAR, AggFunction.STDDEV):
        return 3
    return 1
