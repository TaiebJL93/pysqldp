"""SQL -> relational IR, via sqlglot.

Stands in for Calcite's ``SqlToRelConverter``, reached on the Scala side through
``QueryParser.parseToRelTree``. The query is parsed in the schema's dialect and
lowered into :mod:`pysqldp.relalg.nodes`, resolving column names to positional
``InputRef`` indices against the schema.

Scope is deliberately narrow: a single table scan, an optional ``WHERE``, an
optional ``GROUP BY`` with aggregate calls, and an optional ``ORDER BY``.
Anything else raises :class:`UnsupportedQueryException` rather than being
approximated — under-noising a query is a privacy failure, so refusing is the
only safe default.
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from ..exceptions import UnsupportedQueryException
from ..schema import Database
from .nodes import (
    OP_ABS,
    OP_ADD,
    OP_AND,
    OP_CASE,
    OP_DIV,
    OP_EQ,
    OP_GT,
    OP_GTE,
    OP_IS_NOT_NULL,
    OP_IS_NULL,
    OP_LN,
    OP_LT,
    OP_LTE,
    OP_MUL,
    OP_NEG,
    OP_NEQ,
    OP_NOT,
    OP_OR,
    OP_RAND,
    OP_SUB,
    AggCall,
    AggFunction,
    Aggregate,
    Call,
    Expr,
    Filter,
    InputRef,
    Literal,
    Project,
    Rel,
    Scan,
    Sort,
    SortKey,
)

_BINARY_OPS: dict[type[exp.Expression], str] = {
    exp.Add: OP_ADD,
    exp.Sub: OP_SUB,
    exp.Mul: OP_MUL,
    exp.Div: OP_DIV,
    exp.EQ: OP_EQ,
    exp.NEQ: OP_NEQ,
    exp.GT: OP_GT,
    exp.GTE: OP_GTE,
    exp.LT: OP_LT,
    exp.LTE: OP_LTE,
    exp.And: OP_AND,
    exp.Or: OP_OR,
}

_UNARY_OPS: dict[type[exp.Expression], str] = {
    exp.Ln: OP_LN,
    exp.Abs: OP_ABS,
    exp.Neg: OP_NEG,
}

_AGG_FUNCS: dict[type[exp.Expression], AggFunction] = {
    exp.Count: AggFunction.COUNT,
    exp.Sum: AggFunction.SUM,
    exp.Avg: AggFunction.AVG,
    exp.Min: AggFunction.MIN,
    exp.Max: AggFunction.MAX,
    exp.Variance: AggFunction.VAR,
    exp.VariancePop: AggFunction.VAR,
    exp.Stddev: AggFunction.STDDEV,
    exp.StddevPop: AggFunction.STDDEV,
    exp.StddevSamp: AggFunction.STDDEV,
}


def parse_to_rel_tree(query: str, database: Database) -> Rel:
    """Parse ``query`` in ``database``'s dialect and lower it into the IR."""
    try:
        tree = sqlglot.parse_one(query, read=database.sqlglot_dialect)
    except sqlglot.ParseError as err:
        raise UnsupportedQueryException(f"could not parse query: {err}") from err

    if not isinstance(tree, exp.Select):
        raise UnsupportedQueryException(
            f"expected a SELECT statement, got {type(tree).__name__}"
        )
    return _lower_select(tree, database)


class _Scope:
    """Maps column names visible in a SELECT to input field indices."""

    def __init__(self) -> None:
        self._by_name: dict[str, int] = {}
        self._ambiguous: set[str] = set()

    def add(self, name: str, idx: int, qualifier: str | None = None) -> None:
        if name in self._by_name and self._by_name[name] != idx:
            self._ambiguous.add(name)
        else:
            self._by_name[name] = idx
        if qualifier:
            self._by_name[f"{qualifier}.{name}"] = idx

    def resolve(self, column: exp.Column) -> int:
        name = column.name
        qualifier = column.table
        key = f"{qualifier}.{name}" if qualifier else name
        if key in self._by_name:
            return self._by_name[key]
        if not qualifier and name in self._ambiguous:
            raise UnsupportedQueryException(
                f"column {name!r} is ambiguous; qualify it with a table name"
            )
        raise UnsupportedQueryException(
            f"column {key!r} is not defined in the schema for this query"
        )


def _arg(select: exp.Select, name: str) -> Any:
    """Read a Select argument, tolerating sqlglot's arg renames.

    sqlglot 30 renamed ``from`` to ``from_``; reading both keeps this working
    across versions without pinning.
    """
    return select.args.get(name) or select.args.get(f"{name}_")


def _lower_select(select: exp.Select, database: Database) -> Rel:
    _reject_unsupported(select)

    source, scope = _lower_from(select, database)

    where = _arg(select, "where")
    if where is not None:
        source = Filter(source, _lower_expr(where.this, scope))

    projections = select.expressions
    if not projections:
        raise UnsupportedQueryException("query has no projection list")
    if any(isinstance(p, exp.Star) for p in projections):
        raise UnsupportedQueryException(
            "SELECT * is not supported; list the output columns explicitly"
        )

    group = _arg(select, "group")
    group_exprs = list(group.expressions) if group is not None else []
    has_aggregate = any(_find_agg(p) is not None for p in projections)

    if has_aggregate or group_exprs:
        rel: Rel = _lower_aggregate(source, scope, projections, group_exprs)
    else:
        rel = Project(
            source,
            tuple(_lower_expr(_unalias(p), scope) for p in projections),
            tuple(_output_name(p, i) for i, p in enumerate(projections)),
        )

    order = _arg(select, "order")
    if order is not None:
        rel = Sort(rel, _lower_order(order, rel))

    limit = _arg(select, "limit")
    offset = _arg(select, "offset")
    if limit is not None or offset is not None:
        keys = rel.keys if isinstance(rel, Sort) else ()
        base = rel.input if isinstance(rel, Sort) else rel
        rel = Sort(
            base,
            keys,
            limit=_literal_int(limit.expression) if limit is not None else None,
            offset=_literal_int(offset.expression) if offset is not None else None,
        )

    return rel


def _reject_unsupported(select: exp.Select) -> None:
    if _arg(select, "joins"):
        raise UnsupportedQueryException(
            "joins are not supported yet; the elastic-sensitivity mechanisms "
            "that handle them land in a later phase"
        )
    if _arg(select, "with"):
        raise UnsupportedQueryException("CTEs in the input query are not supported yet")
    if _arg(select, "distinct"):
        raise UnsupportedQueryException("SELECT DISTINCT is not supported")
    if _arg(select, "having"):
        raise UnsupportedQueryException("HAVING is not supported yet")
    if _arg(select, "qualify") or _arg(select, "windows"):
        raise UnsupportedQueryException("window functions are not supported")


def _lower_from(select: exp.Select, database: Database) -> tuple[Rel, _Scope]:
    from_ = _arg(select, "from")
    if from_ is None:
        raise UnsupportedQueryException("query has no FROM clause")

    table = from_.this
    if isinstance(table, exp.Subquery):
        raise UnsupportedQueryException("subqueries in FROM are not supported yet")
    if not isinstance(table, exp.Table):
        raise UnsupportedQueryException(
            f"unsupported FROM source {type(table).__name__}"
        )

    name = ".".join(part.name for part in table.parts)
    schema_table = database.table(name)
    columns = schema_table.column_names

    scope = _Scope()
    qualifier = table.alias or schema_table.table
    for idx, column in enumerate(columns):
        scope.add(column, idx, qualifier)

    return Scan(database.qualified(schema_table.table), columns), scope


def _lower_aggregate(
    source: Rel,
    scope: _Scope,
    projections: list[exp.Expression],
    group_exprs: list[exp.Expression],
) -> Rel:
    """Build an Aggregate plus the Project that restores the SELECT's order."""
    group_keys: list[int] = [
        _resolve_group_key(g, scope, projections) for g in group_exprs
    ]

    agg_calls: list[AggCall] = []
    agg_names: list[str] = []
    # Output position in the SELECT list -> field index in the Aggregate output.
    position_to_field: dict[int, int] = {}

    for position, projection in enumerate(projections):
        bare = _unalias(projection)
        agg = _find_agg(bare)
        if agg is None:
            if not isinstance(bare, exp.Column):
                raise UnsupportedQueryException(
                    "every non-aggregated output column must be a plain column "
                    f"reference; got {bare.sql()!r}"
                )
            idx = scope.resolve(bare)
            if idx not in group_keys:
                raise UnsupportedQueryException(
                    f"column {bare.name!r} is selected but not grouped"
                )
            position_to_field[position] = group_keys.index(idx)
            continue

        if agg is not bare:
            raise UnsupportedQueryException(
                "arithmetic around an aggregate is not supported; select the "
                "aggregate directly and compute afterwards"
            )

        agg_calls.append(_lower_agg_call(agg, scope))
        agg_names.append(_output_name(projection, position))
        position_to_field[position] = len(group_keys) + len(agg_calls) - 1

    aggregate = Aggregate(source, tuple(group_keys), tuple(agg_calls), tuple(agg_names))

    exprs = tuple(InputRef(position_to_field[i]) for i in range(len(projections)))
    names = tuple(_output_name(p, i) for i, p in enumerate(projections))
    identity = tuple(InputRef(i) for i in range(len(exprs)))
    if exprs == identity and names == aggregate.row_type:
        return aggregate
    return Project(aggregate, exprs, names)


def _resolve_group_key(
    group: exp.Expression, scope: _Scope, projections: list[exp.Expression]
) -> int:
    """Resolve one GROUP BY term to an input field index.

    Hive and Presto both accept positional group keys (``GROUP BY 1, 2``), and
    the Scala test queries use them, so they are resolved through the SELECT
    list the same way Calcite does.
    """
    if isinstance(group, exp.Literal) and group.is_int:
        position = int(group.name) - 1
        if not 0 <= position < len(projections):
            raise UnsupportedQueryException(
                f"GROUP BY {group.name} is out of range for "
                f"{len(projections)} output column(s)"
            )
        target = _unalias(projections[position])
        if not isinstance(target, exp.Column):
            raise UnsupportedQueryException(
                f"GROUP BY {group.name} points at {target.sql()!r}, which is not "
                "a plain column reference"
            )
        return scope.resolve(target)

    if isinstance(group, exp.Column):
        return scope.resolve(group)

    raise UnsupportedQueryException(
        f"unsupported GROUP BY term {group.sql()!r}; only column references and "
        "positions are supported"
    )


def _lower_agg_call(agg: exp.Expression, scope: _Scope) -> AggCall:
    func = _AGG_FUNCS[type(agg)]
    inner = agg.this

    distinct = False
    if isinstance(inner, exp.Distinct):
        distinct = True
        if len(inner.expressions) != 1:
            raise UnsupportedQueryException(
                "DISTINCT aggregates over multiple columns are not supported"
            )
        inner = inner.expressions[0]

    if inner is None or isinstance(inner, exp.Star):
        if func is not AggFunction.COUNT:
            raise UnsupportedQueryException(f"{func.value}(*) is not a valid aggregation")
        return AggCall(func, (), distinct)

    if not isinstance(inner, exp.Column):
        raise UnsupportedQueryException(
            f"aggregate argument must be a plain column reference; got {inner.sql()!r}"
        )

    return AggCall(func, (scope.resolve(inner),), distinct)


def _lower_order(order: exp.Order, rel: Rel) -> tuple[SortKey, ...]:
    keys: list[SortKey] = []
    names = rel.row_type
    for term in order.expressions:
        target = term.this
        if isinstance(target, exp.Literal) and target.is_int:
            idx = int(target.name) - 1
        elif isinstance(target, exp.Column) and target.name in names:
            idx = names.index(target.name)
        else:
            raise UnsupportedQueryException(
                f"ORDER BY term {target.sql()!r} must refer to an output column "
                "by name or position"
            )
        if not 0 <= idx < len(names):
            raise UnsupportedQueryException(
                f"ORDER BY position {idx + 1} is out of range for "
                f"{len(names)} output column(s)"
            )
        keys.append(
            SortKey(
                idx,
                descending=bool(term.args.get("desc")),
                nulls_first=term.args.get("nulls_first"),
            )
        )
    return tuple(keys)


def _find_agg(expression: exp.Expression) -> exp.Expression | None:
    """The aggregate call inside ``expression``, if there is exactly one."""
    found = [node for node in expression.walk() if type(node) in _AGG_FUNCS]
    if not found:
        return None
    if len(found) > 1:
        raise UnsupportedQueryException(
            "nested or multiple aggregates in one output column are not supported"
        )
    return found[0]


def _unalias(expression: exp.Expression) -> exp.Expression:
    return expression.this if isinstance(expression, exp.Alias) else expression


def _output_name(projection: exp.Expression, position: int) -> str:
    if isinstance(projection, exp.Alias):
        return projection.alias
    if isinstance(projection, exp.Column):
        return projection.name
    # Calcite names unaliased aggregates $f<n>; the Scala test harness renames
    # them to _f<n> because the leading $ is awkward in most clients.
    return f"_f{position}"


def _literal_int(expression: exp.Expression | None) -> int | None:
    if expression is None:
        return None
    if isinstance(expression, exp.Literal) and expression.is_int:
        return int(expression.name)
    raise UnsupportedQueryException("LIMIT/OFFSET must be integer literals")


def _lower_expr(expression: exp.Expression, scope: _Scope) -> Expr:
    """Lower a scalar sqlglot expression into the IR."""
    if isinstance(expression, exp.Paren):
        return _lower_expr(expression.this, scope)

    if isinstance(expression, exp.Column):
        return InputRef(scope.resolve(expression))

    if isinstance(expression, exp.Boolean):
        return Literal(expression.this)

    if isinstance(expression, exp.Null):
        return Literal(None)

    if isinstance(expression, exp.Literal):
        return Literal(_literal_value(expression))

    if isinstance(expression, exp.Case):
        return _lower_case(expression, scope)

    if isinstance(expression, exp.Is):
        inner = _lower_expr(expression.this, scope)
        if isinstance(expression.expression, exp.Null):
            return Call(OP_IS_NULL, (inner,))
        raise UnsupportedQueryException("IS is only supported against NULL")

    if isinstance(expression, exp.Not):
        inner = expression.this
        if isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null):
            return Call(OP_IS_NOT_NULL, (_lower_expr(inner.this, scope),))
        return Call(OP_NOT, (_lower_expr(inner, scope),))

    if isinstance(expression, exp.Rand):
        return Call(OP_RAND, ())

    unary = _UNARY_OPS.get(type(expression))
    if unary is not None:
        return Call(unary, (_lower_expr(expression.this, scope),))

    binary = _BINARY_OPS.get(type(expression))
    if binary is not None:
        return Call(
            binary,
            (
                _lower_expr(expression.this, scope),
                _lower_expr(expression.expression, scope),
            ),
        )

    raise UnsupportedQueryException(
        f"unsupported expression {expression.sql()!r} ({type(expression).__name__})"
    )


def _lower_case(expression: exp.Case, scope: _Scope) -> Expr:
    ifs = expression.args.get("ifs") or []
    if len(ifs) != 1:
        raise UnsupportedQueryException(
            "only single-branch CASE WHEN ... THEN ... ELSE ... END is supported"
        )
    branch = ifs[0]
    default = expression.args.get("default")
    if default is None:
        raise UnsupportedQueryException("CASE without ELSE is not supported")
    return Call(
        OP_CASE,
        (
            _lower_expr(branch.this, scope),
            _lower_expr(branch.args["true"], scope),
            _lower_expr(default, scope),
        ),
    )


def _literal_value(literal: exp.Literal) -> Any:
    if literal.is_string:
        return literal.this
    text = literal.name
    try:
        return int(text)
    except ValueError:
        return float(text)
