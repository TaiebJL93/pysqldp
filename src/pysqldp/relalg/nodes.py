"""The relational IR: a Python stand-in for the Calcite ``RelNode``/``RexNode``
subset that the Scala analyses and rewriters are written against.

Python has no Calcite, and sqlglot's AST is a *syntax* tree rather than a
relational algebra, so the port needs its own small algebra to hang the
operator-level transfer functions off. Only the operators the mechanisms
actually touch are modelled.

Two invariants are inherited from Calcite and relied on throughout:

1. An ``Aggregate``'s grouped columns are the *leading* output fields, followed
   by one field per aggregate call. ``SimpleSensitivityAnalysis`` and
   ``SensitivityRewriter`` both index on this.
2. A ``Join``'s output fields are the left input's fields followed by the
   right input's, so a column index at or above ``len(left.row_type)`` belongs
   to the right side.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AggFunction(str, Enum):
    """Port of ``com.uber.engsec.dp.dataflow.AggFunctions``."""

    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"
    VAR = "VAR"
    STDDEV = "STDDEV"
    PERCENTILE = "PERCENTILE"
    SINGLE_VALUE = "SINGLE_VALUE"


# Operator tokens used in `Call.op`. Kept as plain strings so the IR stays
# printable and comparable without a second enum to maintain.
OP_CASE = "CASE"
OP_AND = "AND"
OP_OR = "OR"
OP_NOT = "NOT"
OP_EQ = "="
OP_NEQ = "<>"
OP_GT = ">"
OP_GTE = ">="
OP_LT = "<"
OP_LTE = "<="
OP_ADD = "+"
OP_SUB = "-"
OP_MUL = "*"
OP_DIV = "/"
OP_NEG = "NEGATE"
OP_LN = "LN"
OP_ABS = "ABS"
OP_RAND = "RAND"
OP_IS_NULL = "IS NULL"
OP_IS_NOT_NULL = "IS NOT NULL"
OP_CAST = "CAST"

#: Operators that ``SimpleSensitivityAnalysis.transferExpression`` treats as
#: non-arithmetic, i.e. value-preserving for sensitivity purposes.
NON_ARITHMETIC_OPS = frozenset({OP_EQ, OP_CAST})


# --- Expressions ------------------------------------------------------------


class Expr:
    """Base class for scalar expressions (Calcite ``RexNode``)."""

    __slots__ = ()

    @property
    def operands(self) -> tuple[Expr, ...]:
        return ()


@dataclass(frozen=True)
class InputRef(Expr):
    """Reference to field ``idx`` of the enclosing relation's input."""

    idx: int


@dataclass(frozen=True)
class Literal(Expr):
    """A constant. ``value`` is a Python scalar; ``None`` means SQL NULL."""

    value: Any

    @property
    def is_numeric(self) -> bool:
        return isinstance(self.value, (int, float)) and not isinstance(self.value, bool)


@dataclass(frozen=True)
class Call(Expr):
    """An operator applied to operands, e.g. ``Call(OP_ADD, (a, b))``."""

    op: str
    args: tuple[Expr, ...] = ()

    @property
    def operands(self) -> tuple[Expr, ...]:
        return self.args


@dataclass(frozen=True)
class AggCall:
    """One aggregate call inside an ``Aggregate``.

    ``args`` are indices into the *input* relation's fields. An empty tuple
    means ``COUNT(*)``.
    """

    func: AggFunction
    args: tuple[int, ...] = ()
    distinct: bool = False
    #: Extra literal arguments, e.g. the 0.3 in ``PERCENTILE(amount, 0.3)``.
    literals: tuple[Any, ...] = ()


@dataclass(frozen=True)
class SortKey:
    """One ``ORDER BY`` term, by output field index."""

    idx: int
    descending: bool = False
    nulls_first: bool | None = None


# --- Relations --------------------------------------------------------------


class Rel:
    """Base class for relational operators (Calcite ``RelNode``)."""

    __slots__ = ()

    @property
    def row_type(self) -> tuple[str, ...]:
        """Output field names, in order."""
        raise NotImplementedError

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return ()

    @property
    def field_count(self) -> int:
        return len(self.row_type)

    def with_inputs(self, inputs: list[Rel]) -> Rel:
        """Return a copy of this node with its inputs replaced."""
        if inputs:
            raise ValueError(f"{type(self).__name__} takes no inputs")
        return self


@dataclass(frozen=True)
class Scan(Rel):
    """A base table read. ``table`` may be namespace-qualified."""

    table: str
    columns: tuple[str, ...]

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.columns


@dataclass(frozen=True)
class Filter(Rel):
    """``WHERE`` / ``HAVING``: row selection, output shape unchanged."""

    input: Rel
    condition: Expr

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.input.row_type

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return (self.input,)

    def with_inputs(self, inputs: list[Rel]) -> Filter:
        (child,) = inputs
        return Filter(child, self.condition)


@dataclass(frozen=True)
class Project(Rel):
    """Per-column expressions with output aliases."""

    input: Rel
    exprs: tuple[Expr, ...]
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.exprs) != len(self.names):
            raise ValueError(
                f"Project has {len(self.exprs)} expressions but "
                f"{len(self.names)} names"
            )

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.names

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return (self.input,)

    def with_inputs(self, inputs: list[Rel]) -> Project:
        (child,) = inputs
        return Project(child, self.exprs, self.names)


@dataclass(frozen=True)
class Aggregate(Rel):
    """``GROUP BY`` with aggregate calls.

    Grouped columns come first in the output, as in Calcite. ``group_keys`` are
    indices into the input relation.
    """

    input: Rel
    group_keys: tuple[int, ...]
    agg_calls: tuple[AggCall, ...]
    agg_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.agg_calls) != len(self.agg_names):
            raise ValueError(
                f"Aggregate has {len(self.agg_calls)} calls but "
                f"{len(self.agg_names)} names"
            )

    @property
    def group_count(self) -> int:
        return len(self.group_keys)

    @property
    def group_names(self) -> tuple[str, ...]:
        return tuple(self.input.row_type[i] for i in self.group_keys)

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.group_names + self.agg_names

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return (self.input,)

    def with_inputs(self, inputs: list[Rel]) -> Aggregate:
        (child,) = inputs
        return Aggregate(child, self.group_keys, self.agg_calls, self.agg_names)

    def agg_function_at(self, idx: int) -> AggFunction | None:
        """The aggregate function for output field ``idx``, or None for a bin."""
        if idx < self.group_count:
            return None
        return self.agg_calls[idx - self.group_count].func


@dataclass(frozen=True)
class Join(Rel):
    """A two-input join. Output fields are left's followed by right's."""

    left: Rel
    right: Rel
    condition: Expr | None = None
    join_type: str = "INNER"

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.left.row_type + self.right.row_type

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return (self.left, self.right)

    def with_inputs(self, inputs: list[Rel]) -> Join:
        left, right = inputs
        return Join(left, right, self.condition, self.join_type)


@dataclass(frozen=True)
class Sort(Rel):
    """``ORDER BY``, optionally with ``LIMIT``/``OFFSET``."""

    input: Rel
    keys: tuple[SortKey, ...] = ()
    limit: int | None = None
    offset: int | None = None

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.input.row_type

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return (self.input,)

    def with_inputs(self, inputs: list[Rel]) -> Sort:
        (child,) = inputs
        return Sort(child, self.keys, self.limit, self.offset)


@dataclass(frozen=True)
class SubqueryAlias(Rel):
    """Forces its input to be emitted as a named derived table.

    Calcite decides subquery boundaries during ``RelToSql`` conversion; this
    port makes them explicit in the IR instead, which keeps SQL generation
    simple and predictable.
    """

    input: Rel
    alias: str

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.input.row_type

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return (self.input,)

    def with_inputs(self, inputs: list[Rel]) -> SubqueryAlias:
        (child,) = inputs
        return SubqueryAlias(child, self.alias)


@dataclass(frozen=True)
class WithTable(Rel):
    """A CTE: ``WITH <alias> AS (<definition>) <body>``.

    Port of ``com.uber.engsec.dp.rewriting.WithTable``. Analyses skip straight
    to the definition's facts, matching the Scala behaviour.
    """

    alias: str
    definition: Rel
    body: Rel

    @property
    def row_type(self) -> tuple[str, ...]:
        return self.body.row_type

    @property
    def inputs(self) -> tuple[Rel, ...]:
        return (self.definition, self.body)

    def with_inputs(self, inputs: list[Rel]) -> WithTable:
        definition, body = inputs
        return WithTable(self.alias, definition, body)
