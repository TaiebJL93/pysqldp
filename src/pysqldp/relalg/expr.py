"""Expression constructors.

Port of ``com.uber.engsec.dp.rewriting.rules.Expr``, which gives the Scala
rewriters a small DSL for building ``RexNode`` trees. Here they are plain
functions returning :mod:`pysqldp.relalg.nodes` expressions.
"""

from __future__ import annotations

from typing import Any

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
    Call,
    Expr,
    InputRef,
    Literal,
)


def col(idx: int) -> InputRef:
    """Reference input field ``idx``."""
    return InputRef(idx)


def lit(value: Any) -> Literal:
    """A constant. Pass ``None`` for SQL NULL."""
    return Literal(value)


def _coerce(value: Expr | Any) -> Expr:
    return value if isinstance(value, Expr) else Literal(value)


def case(condition: Expr | Any, then: Expr | Any, otherwise: Expr | Any) -> Call:
    """``CASE WHEN condition THEN then ELSE otherwise END``."""
    return Call(OP_CASE, (_coerce(condition), _coerce(then), _coerce(otherwise)))


def rand() -> Call:
    """A uniform sample in [0, 1).

    The Scala side picks ``RANDOM()`` for PostgreSQL and ``RAND()`` elsewhere
    (``DPUtil.randZeroOne``). Here the choice is deferred to SQL generation,
    where sqlglot already renders the right function per dialect.
    """
    return Call(OP_RAND, ())


def ln(value: Expr | Any) -> Call:
    return Call(OP_LN, (_coerce(value),))


def abs_(value: Expr | Any) -> Call:
    return Call(OP_ABS, (_coerce(value),))


def add(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_ADD, (_coerce(left), _coerce(right)))


def sub(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_SUB, (_coerce(left), _coerce(right)))


def mul(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_MUL, (_coerce(left), _coerce(right)))


def div(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_DIV, (_coerce(left), _coerce(right)))


def neg(value: Expr | Any) -> Call:
    return Call(OP_NEG, (_coerce(value),))


def eq(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_EQ, (_coerce(left), _coerce(right)))


def neq(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_NEQ, (_coerce(left), _coerce(right)))


def gt(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_GT, (_coerce(left), _coerce(right)))


def gte(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_GTE, (_coerce(left), _coerce(right)))


def lt(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_LT, (_coerce(left), _coerce(right)))


def lte(left: Expr | Any, right: Expr | Any) -> Call:
    return Call(OP_LTE, (_coerce(left), _coerce(right)))


def and_(*parts: Expr) -> Expr:
    if not parts:
        return Literal(True)
    result = parts[0]
    for part in parts[1:]:
        result = Call(OP_AND, (result, part))
    return result


def or_(*parts: Expr) -> Expr:
    if not parts:
        return Literal(False)
    result = parts[0]
    for part in parts[1:]:
        result = Call(OP_OR, (result, part))
    return result


def not_(value: Expr) -> Call:
    return Call(OP_NOT, (value,))


def is_null(value: Expr) -> Call:
    return Call(OP_IS_NULL, (value,))


def is_not_null(value: Expr) -> Call:
    return Call(OP_IS_NOT_NULL, (value,))


def shift_refs(expr: Expr, offset: int) -> Expr:
    """Re-index every ``InputRef`` in ``expr`` by ``offset``.

    Needed when an expression written against one input is moved onto a join,
    where the right side's fields start at ``len(left.row_type)``.
    """
    if isinstance(expr, InputRef):
        return InputRef(expr.idx + offset)
    if isinstance(expr, Call):
        return Call(expr.op, tuple(shift_refs(a, offset) for a in expr.args))
    return expr


def map_refs(expr: Expr, mapping: dict[int, int]) -> Expr:
    """Rewrite ``InputRef`` indices through ``mapping``.

    Indices absent from ``mapping`` are left alone.
    """
    if isinstance(expr, InputRef):
        return InputRef(mapping.get(expr.idx, expr.idx))
    if isinstance(expr, Call):
        return Call(expr.op, tuple(map_refs(a, mapping) for a in expr.args))
    return expr


def referenced_indices(expr: Expr) -> set[int]:
    """Every input field index ``expr`` reads."""
    if isinstance(expr, InputRef):
        return {expr.idx}
    if isinstance(expr, Call):
        found: set[int] = set()
        for arg in expr.args:
            found |= referenced_indices(arg)
        return found
    return set()
