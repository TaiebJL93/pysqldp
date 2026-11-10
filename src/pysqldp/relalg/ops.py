"""Relation-building helpers.

Port of the parts of ``com.uber.engsec.dp.rewriting.rules.Operations`` and
``ColumnDefinition`` that the mechanisms use: per-column rewriting, input
replacement, and naming a relation so it becomes a derived table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .nodes import Expr, InputRef, Project, Rel, SubqueryAlias


@dataclass(frozen=True)
class ColumnDef:
    """One output column of a relation, as seen by :func:`map_cols`.

    ``expr`` is written against the *input* of the Project that will hold it,
    so returning it unchanged is an identity rewrite.
    """

    idx: int
    alias: str
    expr: Expr

    def aliased(self, expr: Expr) -> ColumnDef:
        """This column with a new expression, same position and name."""
        return ColumnDef(self.idx, self.alias, expr)

    def renamed(self, alias: str) -> ColumnDef:
        return ColumnDef(self.idx, alias, self.expr)


def column_defs(rel: Rel) -> tuple[Rel, list[ColumnDef]]:
    """Split ``rel`` into a base relation and the column definitions over it.

    A ``Project`` is decomposed into its input plus its expressions, so
    rewriting columns does not stack a second projection. Anything else gets
    identity definitions over itself.
    """
    if isinstance(rel, Project):
        defs = [
            ColumnDef(i, name, expr)
            for i, (expr, name) in enumerate(zip(rel.exprs, rel.names))
        ]
        return rel.input, defs

    defs = [ColumnDef(i, name, InputRef(i)) for i, name in enumerate(rel.row_type)]
    return rel, defs


def map_cols(rel: Rel, fn: Callable[[ColumnDef], ColumnDef]) -> Project:
    """Rewrite every output column of ``rel`` through ``fn``.

    Port of ``Operations.mapCols``. The result is always a ``Project``, which is
    how the Scala rewriters attach noise, clipping and sign fixes to an
    arbitrary relation.
    """
    base, defs = column_defs(rel)
    rewritten = [fn(d) for d in defs]
    return Project(
        base,
        tuple(d.expr for d in rewritten),
        tuple(d.alias for d in rewritten),
    )


def identity_project(rel: Rel) -> Project:
    """Wrap ``rel`` in a projection that selects all its columns unchanged."""
    return Project(
        rel,
        tuple(InputRef(i) for i in range(rel.field_count)),
        rel.row_type,
    )


def replace_inputs(rel: Rel, fn: Callable[[list[Rel]], list[Rel]]) -> Rel:
    """Port of ``Operations.replaceInputs``."""
    return rel.with_inputs(fn(list(rel.inputs)))


def as_alias(rel: Rel, alias: str) -> SubqueryAlias:
    """Port of ``Operations.asAlias``: force ``rel`` to be a named subquery."""
    return SubqueryAlias(rel, alias)
