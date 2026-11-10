"""Rewriter base class and the bottom-up rewriting traversal.

Port of ``com.uber.engsec.dp.rewriting.Rewriter`` and the ``rewriteRecursive``
operation from ``rules.Operations``.

A rewriter walks the IR bottom-up. Children are rewritten first; the facts they
return are merged through an abstract domain and handed to the transformation
for the parent, which lets information travel upward — that is how
``SensitivityRewriter`` learns that a table scan below it means noise is still
owed, and records that it has since been added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from ..dataflow.domain import AbstractDomain
from ..exceptions import RewritingException
from ..relalg.nodes import Rel
from ..relalg.to_sql import to_sql
from ..schema import Database

E = TypeVar("E")

#: ``(rewritten_node, original_node, merged_child_fact) -> (new_node, fact)``
Transformation = Callable[[Rel, Rel, E], "tuple[Rel, E]"]


def rewrite_recursive(
    rel: Rel, domain: AbstractDomain[E], transformation: Transformation[E]
) -> tuple[Rel, E]:
    """Rewrite ``rel`` bottom-up, threading facts from ``domain`` upward.

    Raises:
        RewritingException: if a transformation reorders or drops existing
            output columns. Appending columns is allowed; changing the position
            of an existing one would silently repoint a parent's references.
    """
    old_children = list(rel.inputs)
    results = [
        rewrite_recursive(child, domain, transformation) for child in old_children
    ]
    new_children = [node for node, _ in results]

    node = rel if new_children == old_children else rel.with_inputs(new_children)
    context = domain.join(fact for _, fact in results)

    new_node, fact = transformation(node, rel, context)

    old_columns = rel.row_type
    new_columns = new_node.row_type
    if new_columns[: len(old_columns)] != old_columns:
        added = [c for c in new_columns if c not in old_columns]
        raise RewritingException(
            "rewriters must keep the original columns in the same order; "
            f"column(s) {added} would have to move to the end of the relation. "
            f"Original schema: {list(old_columns)}; new schema: {list(new_columns)}"
        )

    return new_node, fact


@dataclass(frozen=True)
class RewriterConfig:
    """Configuration shared by every rewriter."""

    database: Database


@dataclass(frozen=True)
class DPRewriterConfig(RewriterConfig):
    """Configuration for rewriters that spend privacy budget.

    Attributes:
        epsilon: the privacy parameter. Noise scales as
            ``sensitivity / epsilon``, so smaller values mean more noise and
            stronger privacy.
        fill_missing_bins: emit the join against the ``domainSet`` table so
            every bin in the domain appears in the result. Turning this off
            makes results **unsafe for release**: which bins are present leaks
            which values occur in the data.
    """

    epsilon: float = 0.1
    fill_missing_bins: bool = True


class RewriterResult:
    """A rewritten relation, plus the configuration that produced it."""

    def __init__(self, root: Rel, config: RewriterConfig) -> None:
        self.root = root
        self.config = config

    def to_sql(self, pretty: bool = False) -> str:
        """Render the rewritten relation in the schema's dialect."""
        return to_sql(
            self.root,
            dialect=self.config.database.sqlglot_dialect,
            pretty=pretty,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RewriterResult({type(self.root).__name__}, {self.root.row_type})"


class Rewriter(Generic[E]):
    """Base class for rewriters.

    Subclasses implement :meth:`rewrite`; :meth:`run` wraps the result with the
    configuration so callers can render SQL without repeating the dialect.
    """

    def __init__(self, config: RewriterConfig) -> None:
        self.config = config

    @property
    def database(self) -> Database:
        return self.config.database

    def rewrite(self, root: Rel) -> Rel:
        raise NotImplementedError

    def run(self, root: Rel) -> RewriterResult:
        return RewriterResult(self.rewrite(root), self.config)
