"""Relational IR -> SQL, via sqlglot.

Stands in for Calcite's ``RelToSqlConverter`` (used by ``Relation.toSql`` on the
Scala side). The IR is lowered into a sqlglot expression tree, which sqlglot
then renders in whichever dialect the schema names.

Subquery boundaries are explicit in the IR (:class:`SubqueryAlias`) rather than
inferred, so generation is a straightforward walk: each ``SELECT`` scope is
built by peeling the ``Sort``/``Project``/``Aggregate``/``Filter`` chain above a
source relation.

The central piece of bookkeeping is ``refs``: a list holding, for each output
field of the relation being processed, the sqlglot expression that refers to
that field from inside the current ``SELECT``. ``InputRef(i)`` resolves to
``refs[i]``, which is how Calcite's positional field references survive the
trip to name-based SQL.
"""

from __future__ import annotations

from sqlglot import exp

from ..exceptions import UnsupportedConstructException
from .nodes import (
    OP_ABS,
    OP_ADD,
    OP_AND,
    OP_CASE,
    OP_CAST,
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
    Join,
    Literal,
    Project,
    Rel,
    Scan,
    Sort,
    SubqueryAlias,
    WithTable,
)

_BINARY = {
    OP_ADD: exp.Add,
    OP_SUB: exp.Sub,
    OP_MUL: exp.Mul,
    OP_DIV: exp.Div,
    OP_EQ: exp.EQ,
    OP_NEQ: exp.NEQ,
    OP_GT: exp.GT,
    OP_GTE: exp.GTE,
    OP_LT: exp.LT,
    OP_LTE: exp.LTE,
    OP_AND: exp.And,
    OP_OR: exp.Or,
}

_UNARY = {
    OP_LN: exp.Ln,
    OP_ABS: exp.Abs,
    OP_NEG: exp.Neg,
    OP_NOT: exp.Not,
}

_AGGREGATES = {
    AggFunction.SUM: exp.Sum,
    AggFunction.AVG: exp.Avg,
    AggFunction.MIN: exp.Min,
    AggFunction.MAX: exp.Max,
    AggFunction.VAR: exp.Variance,
    AggFunction.STDDEV: exp.Stddev,
}

# Relational operators that contribute clauses to the SELECT they sit in,
# rather than becoming a FROM-able source of their own.
_CLAUSE_NODES = (Sort, Project, Aggregate, Filter)


def to_sql(rel: Rel, dialect: str | None = None, pretty: bool = False) -> str:
    """Render ``rel`` as SQL in ``dialect``."""
    return build(rel).sql(dialect=dialect, pretty=pretty)


def build(rel: Rel) -> exp.Expression:
    """Lower ``rel`` into a sqlglot expression tree."""
    return _as_select(rel)


def _table_qualifier(table: str) -> str:
    """The name columns of ``table`` should be qualified with."""
    return table.rsplit(".", 1)[-1]


def _as_source(rel: Rel) -> tuple[exp.Expression, list[exp.Expression]]:
    """Render ``rel`` as something usable in ``FROM``, with its field refs."""
    if isinstance(rel, Scan):
        qualifier = _table_qualifier(rel.table)
        refs = [exp.column(name, table=qualifier) for name in rel.columns]
        return exp.to_table(rel.table), refs

    if isinstance(rel, SubqueryAlias):
        inner = _as_select(rel.input)
        refs = [exp.column(name, table=rel.alias) for name in rel.row_type]
        alias = exp.TableAlias(this=exp.to_identifier(rel.alias))
        return exp.Subquery(this=inner, alias=alias), refs

    raise UnsupportedConstructException(
        f"{type(rel).__name__} cannot be used directly as a FROM source; "
        "wrap it in a SubqueryAlias to give it a name"
    )


def _build_from(select: exp.Select, rel: Rel) -> tuple[exp.Select, list[exp.Expression]]:
    """Attach ``rel`` to ``select`` as its FROM/JOIN chain."""
    if isinstance(rel, Join):
        select, left_refs = _build_from(select, rel.left)
        right_source, right_refs = _as_source(rel.right)
        refs = left_refs + right_refs
        join_type = rel.join_type.upper()
        if join_type == "CROSS":
            select = select.join(right_source, join_type="CROSS", copy=False)
        else:
            on = _expr(rel.condition, refs) if rel.condition is not None else None
            select = select.join(right_source, on=on, join_type=join_type, copy=False)
        return select, refs

    source, refs = _as_source(rel)
    return select.from_(source, copy=False), refs


def _hoist_ctes(rel: Rel) -> tuple[Rel, list[tuple[str, Rel]]]:
    """Lift every ``WithTable`` out of ``rel``, returning the CTEs separately.

    Rewriters insert CTEs wherever they need one — the bin filler wraps the
    relation it is rewriting, which can sit deep in the tree. SQL only allows
    them at the head of a query, and a CTE declared there is visible to every
    nested scope, so collecting them all and emitting them once is both simpler
    and still correct.
    """
    ctes: list[tuple[str, Rel]] = []

    def walk(node: Rel) -> Rel:
        if isinstance(node, WithTable):
            definition = walk(node.definition)
            body = walk(node.body)
            ctes.append((node.alias, definition))
            return body
        new_inputs = [walk(child) for child in node.inputs]
        if new_inputs != list(node.inputs):
            return node.with_inputs(new_inputs)
        return node

    return walk(rel), ctes


def _as_select(rel: Rel) -> exp.Select:
    """Build a SELECT for ``rel``, attaching any CTEs it contains."""
    body, ctes = _hoist_ctes(rel)
    select = _select_scope(body)
    for alias, definition in ctes:
        select = select.with_(alias, as_=_select_scope(definition), copy=False)
    return select


def _select_scope(rel: Rel) -> exp.Select:
    """Build one SELECT scope for ``rel``, which must contain no CTEs."""
    node: Rel = rel

    # Output-side clauses, in the order SQL evaluates them last-first.
    sort: Sort | None = None
    if isinstance(node, Sort):
        sort = node
        node = node.input

    project: Project | None = None
    if isinstance(node, Project):
        project = node
        node = node.input

    having: Filter | None = None
    if isinstance(node, Filter) and isinstance(node.input, Aggregate):
        having = node
        node = node.input

    aggregate: Aggregate | None = None
    if isinstance(node, Aggregate):
        aggregate = node
        node = node.input

    # Input-side clauses. A Project *below* an Aggregate supplies the
    # aggregate's arguments rather than the SELECT list, so its expressions get
    # inlined into the aggregate calls and GROUP BY — which is how the clipping
    # CASE ends up inside SUM(...) instead of in a separate subquery.
    input_project: Project | None = None
    if aggregate is not None and isinstance(node, Project):
        input_project = node
        node = node.input

    where: Filter | None = None
    if isinstance(node, Filter):
        where = node
        node = node.input

    if isinstance(node, _CLAUSE_NODES):
        # Clauses this scope cannot absorb, e.g. a second stacked Project.
        # Emit the lower part as a named derived table so each SELECT stays
        # well formed.
        node = SubqueryAlias(node, _auto_alias(node))

    select = exp.Select()
    select, refs = _build_from(select, node)

    if where is not None:
        select = select.where(_expr(where.condition, refs), copy=False)

    if input_project is not None:
        refs = [_expr(e, refs) for e in input_project.exprs]

    if aggregate is not None:
        group_refs = [refs[i] for i in aggregate.group_keys]
        agg_refs = [_agg_call(call, refs) for call in aggregate.agg_calls]
        if group_refs:
            select = select.group_by(*(r.copy() for r in group_refs), copy=False)
        refs = group_refs + agg_refs

    if having is not None:
        select = select.having(_expr(having.condition, refs), copy=False)

    if project is not None:
        projections = [
            _aliased(_expr(e, refs), name)
            for e, name in zip(project.exprs, project.names)
        ]
        select = select.select(*projections, copy=False)
        # A parent referring to output field i should see the expression, not
        # the alias: Calcite repeats the expression, and repeating it keeps the
        # SQL valid on engines that disallow aliases in WHERE/ORDER BY.
        refs = [_expr(e, refs) for e in project.exprs]
    else:
        names = aggregate.row_type if aggregate is not None else node.row_type
        projections = [_aliased(r.copy(), name) for r, name in zip(refs, names)]
        select = select.select(*projections, copy=False)

    if sort is not None:
        ordered = []
        for key in sort.keys:
            # Only set `desc` when descending: sqlglot renders an explicit ASC
            # otherwise, which Calcite leaves implicit.
            term = exp.Ordered(this=refs[key.idx].copy())
            if key.descending:
                term.set("desc", True)
            if key.nulls_first is not None:
                term.set("nulls_first", key.nulls_first)
            ordered.append(term)
        if ordered:
            select = select.order_by(*ordered, copy=False)
        if sort.limit is not None:
            select = select.limit(sort.limit, copy=False)
        if sort.offset is not None:
            select = select.offset(sort.offset, copy=False)

    return select


def _auto_alias(rel: Rel) -> str:
    """A stable alias for an implicitly materialised derived table."""
    return f"_t{abs(hash((type(rel).__name__, rel.row_type))) % 10000}"


def _aliased(expression: exp.Expression, name: str) -> exp.Expression:
    """Alias ``expression`` as ``name``, skipping no-op self-aliases."""
    if isinstance(expression, exp.Column) and expression.name == name:
        return expression
    return exp.alias_(expression, name)


def _agg_call(call: AggCall, refs: list[exp.Expression]) -> exp.Expression:
    """Render one aggregate call against the input's field refs."""
    args = [refs[i].copy() for i in call.args]

    if call.func is AggFunction.COUNT:
        if not args:
            return exp.Count(this=exp.Star())
        inner = exp.Distinct(expressions=args) if call.distinct else args[0]
        return exp.Count(this=inner)

    if call.func is AggFunction.PERCENTILE:
        params = args + [exp.convert(v) for v in call.literals]
        return exp.Anonymous(this="PERCENTILE", expressions=params)

    if call.func is AggFunction.SINGLE_VALUE:
        return exp.Anonymous(this="SINGLE_VALUE", expressions=args)

    cls = _AGGREGATES.get(call.func)
    if cls is None:
        raise UnsupportedConstructException(
            f"aggregate function {call.func.value} has no SQL mapping"
        )
    if not args:
        raise UnsupportedConstructException(f"{call.func.value} requires an argument")
    inner = exp.Distinct(expressions=args) if call.distinct else args[0]
    return cls(this=inner)


def _expr(expr: Expr, refs: list[exp.Expression]) -> exp.Expression:
    """Translate an IR expression to sqlglot, resolving InputRefs via ``refs``."""
    if isinstance(expr, InputRef):
        try:
            return refs[expr.idx].copy()
        except IndexError as err:
            raise UnsupportedConstructException(
                f"InputRef({expr.idx}) is out of range; the relation has "
                f"{len(refs)} field(s)"
            ) from err

    if isinstance(expr, Literal):
        return exp.Null() if expr.value is None else exp.convert(expr.value)

    if isinstance(expr, Call):
        return _call(expr, refs)

    raise UnsupportedConstructException(
        f"expression node {type(expr).__name__} has no SQL mapping"
    )


def _call(call: Call, refs: list[exp.Expression]) -> exp.Expression:
    args = [_expr(a, refs) for a in call.args]

    if call.op == OP_CASE:
        condition, then, otherwise = args
        return exp.Case(ifs=[exp.If(this=condition, true=then)], default=otherwise)

    if call.op == OP_RAND:
        return exp.Rand()

    if call.op == OP_IS_NULL:
        return exp.Is(this=args[0], expression=exp.Null())

    if call.op == OP_IS_NOT_NULL:
        return exp.Not(this=exp.Is(this=args[0], expression=exp.Null()))

    if call.op == OP_CAST:
        if len(args) != 1:
            raise UnsupportedConstructException("CAST takes exactly one operand")
        return exp.Cast(this=args[0], to=exp.DataType.build("DOUBLE"))

    unary = _UNARY.get(call.op)
    if unary is not None:
        return unary(this=args[0])

    binary = _BINARY.get(call.op)
    if binary is not None:
        result = args[0]
        for operand in args[1:]:
            result = binary(this=result, expression=operand)
        return result

    raise UnsupportedConstructException(f"operator {call.op!r} has no SQL mapping")
