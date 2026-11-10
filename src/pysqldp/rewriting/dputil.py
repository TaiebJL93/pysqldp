"""Shared machinery for the differential-privacy rewriters.

Port of ``com.uber.engsec.dp.rewriting.DPUtil``: the in-database Laplace
sampler, and the histogram bin filling that makes grouped results safe to
release.
"""

from __future__ import annotations

from ..analysis.histogram import AggregationInfo
from ..exceptions import RewritingException
from ..relalg.expr import (
    abs_,
    add,
    and_,
    case,
    eq,
    is_not_null,
    lit,
    ln,
    lt,
    mul,
    rand,
    sub,
)
from ..relalg.nodes import (
    Aggregate,
    Expr,
    InputRef,
    Join,
    Project,
    Rel,
    Scan,
    SubqueryAlias,
    WithTable,
)
from ..relalg.ops import as_alias
from ..schema import Database, get_schema_map_for_table

#: Alias of the CTE holding the bin domain.
DOMAIN_ALIAS = "_domain"
#: Alias given to the un-filled aggregation when it is joined to the domain.
AGGREGATE_ALIAS = "t0"

# Bin-filling strategies, mirroring ``SensitivityRewriterConfig``.
#: Right-join the domain set onto the aggregated data. The default.
JOIN_DOMAIN_ON_RIGHT = "JOIN_DOMAIN_ON_RIGHT"
#: Find the missing bins with a join, then ``UNION ALL`` them in. Preserves
#: result ordering, so it avoids leaking information through row order.
UNION_ALL_JOIN = "UNION_ALL_JOIN"
#: ``UNION ALL`` the data with the domain, then group and take ``MAX`` per bin.
#: Only valid for non-negative data: negatives would be lost against the 0
#: default.
UNION_ALL_MAX = "UNION_ALL_MAX"


def laplace_sample() -> Expr:
    """An expression drawing one sample from Laplace(0, 1).

    Built from the engine's uniform generator. For ``U`` uniform on
    ``[-0.5, 0.5]``:

        y = sign(U) * ln(1 - 2 |U|)

    is Laplace-distributed with scale 1, so multiplying by ``s / epsilon``
    gives the noise the Laplace mechanism requires.

    Matches ``DPUtil.laplaceSample`` expression for expression, so the
    rewritten SQL stays comparable against the Scala output. Note that the two
    ``RAND()`` calls are independent draws, as in the original: the sign and
    the magnitude come from different samples.
    """
    sign = case(lt(sub(rand(), 0.5), 0), lit(-1.0), lit(1.0))
    magnitude = ln(sub(1, mul(2, abs_(sub(rand(), 0.5)))))
    return mul(sign, magnitude)


def one_sided_laplace_sample() -> Expr:
    """A non-positive Laplace draw, used when fixing the sign of a result.

    Port of ``DPUtil.oneSidedLaplaceSample``.
    """
    return ln(sub(1, mul(2, abs_(sub(rand(), 0.5)))))


def construct_domain_set(
    node: Aggregate, histogram_facts: tuple[AggregationInfo, ...], database: Database
) -> tuple[Rel, tuple[str, ...]]:
    """Build the relation enumerating every bin of the grouped columns.

    Each grouped column must name a ``domainSet`` in the schema — a
    ``table.column`` holding that column's full domain. Without it there is no
    way to distinguish a bin that is genuinely absent from one suppressed by
    noise, and that absence is itself a leak.

    Returns the domain relation and the column names to join on, in group order.
    """
    specs: list[tuple[str, str]] = []
    for idx in range(node.group_count):
        fact = histogram_facts[idx]
        bin_name = node.row_type[idx]

        if fact.value_modified:
            raise RewritingException(
                f"histogram column {bin_name!r} has a modified value, so its "
                "bins cannot be matched against a domain set"
            )
        if len(fact.references) != 1:
            raise RewritingException(
                f"histogram column {bin_name!r} must derive its values from "
                "exactly one database column, but derives from "
                f"{len(fact.references)}"
            )

        reference = next(iter(fact.references))
        columns = get_schema_map_for_table(database, reference.table)
        domain_set = columns[reference.column].properties.get("domainSet")
        if domain_set is None:
            raise RewritingException(
                f"column {reference.column!r} in table {reference.table!r} is "
                "used as a histogram bin. Define a 'domainSet' property naming "
                "a table.column that enumerates this column's domain. Disabling "
                "fill_missing_bins skips this check, but then query results are "
                "NOT safe for release."
            )

        table, _, column = domain_set.rpartition(".")
        if not table:
            raise RewritingException(
                f"domainSet {domain_set!r} must be of the form 'table.column'"
            )
        specs.append((table, column))

    if not specs:
        raise RewritingException("bin filling requires at least one grouped column")

    tables = {table for table, _ in specs}
    if len(tables) > 1:
        raise RewritingException(
            "grouped columns draw their domains from multiple tables "
            f"({sorted(tables)}); cross-table domain construction is not "
            "ported yet"
        )

    table = specs[0][0]
    columns = tuple(column for _, column in specs)
    return Scan(database.qualified(table), columns), columns


def add_bins_from_domain(
    node: Aggregate,
    histogram_facts: tuple[AggregationInfo, ...],
    database: Database,
) -> Rel:
    """Fill in missing histogram bins by right-joining the bin domain.

    Port of ``DPUtil.addBinsFromDomain`` with the ``JOIN_DOMAIN_ON_RIGHT``
    strategy. The aggregation becomes a derived table, the domain becomes a
    CTE, and a right join produces one row per bin in the domain. Aggregates
    for bins with no data come back NULL and are coalesced to 0, which the
    caller then adds noise to — so an empty bin is indistinguishable from a bin
    whose count noise pushed to zero.
    """
    domain_relation, join_columns = construct_domain_set(node, histogram_facts, database)

    aggregated = as_alias(node, AGGREGATE_ALIAS)
    domain_scan = Scan(DOMAIN_ALIAS, join_columns)

    agg_field_count = node.field_count
    condition: Expr | None = None
    for position in range(node.group_count):
        equality = eq(InputRef(position), InputRef(agg_field_count + position))
        condition = equality if condition is None else and_(condition, equality)

    joined = Join(aggregated, domain_scan, condition, join_type="RIGHT")

    # Bin labels come from the domain side: the aggregated side is NULL for
    # bins that had no rows at all.
    exprs: list[Expr] = [
        InputRef(agg_field_count + position) for position in range(node.group_count)
    ]
    for offset in range(len(node.agg_calls)):
        aggregate_ref = InputRef(node.group_count + offset)
        exprs.append(case(is_not_null(aggregate_ref), aggregate_ref, lit(0)))

    filled = Project(joined, tuple(exprs), node.row_type)
    return WithTable(DOMAIN_ALIAS, domain_relation, filled)


def has_bins_filled(rel: Rel) -> bool:
    """True when ``rel`` already carries the bin-filling CTE."""
    if isinstance(rel, WithTable) and rel.alias == DOMAIN_ALIAS:
        return True
    return any(has_bins_filled(child) for child in rel.inputs)


def unwrap_alias(rel: Rel) -> Rel:
    """Strip a :class:`SubqueryAlias`, if present."""
    return rel.input if isinstance(rel, SubqueryAlias) else rel


def scale_noise(scale: float, sample: Expr) -> Expr:
    """``scale * sample``, the Laplace term added to a column."""
    return mul(lit(scale), sample)


def add_noise(expr: Expr, noise: Expr) -> Expr:
    """``expr + noise``."""
    return add(expr, noise)
