"""Sensitivity-based mechanisms: the Laplace noise rewriters.

Port of ``com.uber.engsec.dp.rewriting.differential_privacy``'s
``SensitivityRewriter`` and ``GlobalSensitivityRewriter``.

``SensitivityRewriter`` is the shared skeleton: it fills histogram bins, then
adds noise to every aggregated column scaled to that column's sensitivity.
Subclasses differ only in how they compute that sensitivity, which is what
distinguishes the mechanisms from one another.

For a query with L1 sensitivity ``s``, releasing ``q(x) + Laplace(s/epsilon)``
satisfies epsilon-differential privacy, giving ``(alpha, beta)``-accuracy for
``alpha = (s/epsilon) * ln(1/beta)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..analysis.histogram import HistogramAnalysis
from ..analysis.sensitivity import SimpleSensitivityAnalysis
from ..dataflow.domain import BOOLEAN_DOMAIN
from ..exceptions import RewritingException
from ..relalg.nodes import Aggregate, Rel, Scan, WithTable
from ..relalg.ops import ColumnDef, as_alias, map_cols
from .dputil import (
    JOIN_DOMAIN_ON_RIGHT,
    add_bins_from_domain,
    add_noise,
    laplace_sample,
    scale_noise,
)
from .rewriter import DPRewriterConfig, Rewriter, rewrite_recursive


@dataclass(frozen=True)
class SensitivityRewriterConfig(DPRewriterConfig):
    """Configuration for the sensitivity-based mechanisms.

    Attributes:
        fix_sign: rewrite results whose noise pushed them past zero or to the
            wrong sign. This introduces bias but is pure post-processing, so it
            does not affect the privacy guarantee.
        cast_count: cast noised ``COUNT`` results back to an integer type.
            Discards information; also pure post-processing.
        set_deterministic_alias: name to give the un-noised part of the query,
            putting it in its own derived table. Useful when the caller wants
            to materialise the deterministic half once.
        fill_routine: which bin-filling strategy to emit. See
            :mod:`pysqldp.rewriting.dputil`.
    """

    fix_sign: bool = False
    cast_count: bool = False
    set_deterministic_alias: str | None = None
    fill_routine: str = JOIN_DOMAIN_ON_RIGHT


@dataclass(frozen=True)
class GlobalSensitivityConfig(SensitivityRewriterConfig):
    """Configuration for :class:`GlobalSensitivityRewriter`."""


class SensitivityRewriter(Rewriter[bool]):
    """Adds Laplace noise scaled to each output column's sensitivity.

    Subclasses implement :meth:`get_laplace_noise_scale`.

    The boolean fact threaded up the tree answers "is noise still owed here?".
    A table scan sets it, since reading the database is what creates the
    obligation; an aggregation discharges it and clears the flag, so a query
    with nested aggregations is noised once, at the innermost one.
    """

    config: SensitivityRewriterConfig

    def __init__(self, config: SensitivityRewriterConfig) -> None:
        super().__init__(config)
        self.config = config

    def get_laplace_noise_scale(self, node: Rel, col_idx: int) -> float:
        """The Laplace scale for output column ``col_idx`` of ``node``."""
        raise NotImplementedError

    def rewrite(self, root: Rel) -> Rel:
        rewritten, _ = rewrite_recursive(root, BOOLEAN_DOMAIN, self._transform)
        return rewritten

    def _transform(self, node: Rel, original: Rel, needs_noise: bool) -> tuple[Rel, bool]:
        if isinstance(node, Scan):
            # Reading from the database is what creates the obligation to add
            # noise somewhere above.
            return node, True

        if not (isinstance(node, Aggregate) and needs_noise):
            return node, needs_noise

        scales = [
            self.get_laplace_noise_scale(node, idx) for idx in range(node.field_count)
        ]

        deterministic: Rel = node
        if node.group_count > 0 and self.config.fill_missing_bins:
            if self.config.fill_routine != JOIN_DOMAIN_ON_RIGHT:
                raise RewritingException(
                    f"fill routine {self.config.fill_routine!r} is not ported "
                    f"yet; use {JOIN_DOMAIN_ON_RIGHT!r}"
                )
            histogram = HistogramAnalysis().run(node, self.database).col_facts
            deterministic = add_bins_from_domain(node, histogram, self.database)

        if self.config.set_deterministic_alias is not None:
            deterministic = as_alias(deterministic, self.config.set_deterministic_alias)

        if self.config.fix_sign or self.config.cast_count:
            raise RewritingException(
                "fix_sign and cast_count post-processing are not ported yet"
            )

        noised = _map_cols_through_cte(
            deterministic, lambda column: self._noise_column(column, scales)
        )

        # Noise has been added for this data, so nothing above should add more.
        return noised, False

    def _noise_column(self, column: ColumnDef, scales: list[float]) -> ColumnDef:
        scale = scales[column.idx]

        if scale == float("inf"):
            raise RewritingException(
                f"noise scale for column {column.alias!r} is infinite, so no "
                "amount of noise would make it safe to release. This usually "
                "means the aggregation has no bounded-sensitivity mechanism "
                "(check that SUM/AVG columns declare clipLower and clipUpper)."
            )

        if scale == 0:
            # Histogram bins that the schema marks safe for release.
            return column

        noise = scale_noise(scale, laplace_sample())
        return column.aliased(add_noise(column.expr, noise))


def _map_cols_through_cte(
    rel: Rel, fn: Callable[[ColumnDef], ColumnDef]
) -> Rel:
    """Apply :func:`map_cols` to ``rel``, reaching inside a CTE wrapper.

    Bin filling returns a ``WithTable``. Projecting on top of that would stack
    a second ``SELECT``; rewriting the CTE's body instead keeps the noise in
    the same projection as the coalesced aggregate, which is both the shape the
    Scala rewriter produces and one fewer subquery for the engine.
    """
    if isinstance(rel, WithTable):
        return WithTable(rel.alias, rel.definition, _map_cols_through_cte(rel.body, fn))
    return map_cols(rel, fn)


class GlobalSensitivityRewriter(SensitivityRewriter):
    """Laplace noise scaled by the global (stability-based) sensitivity.

    Port of ``GlobalSensitivityRewriter``. Works on single-table queries;
    ``COUNT`` takes the relation's stability and ``SUM`` takes stability times
    the clipping range.
    """

    def __init__(self, config: GlobalSensitivityConfig) -> None:
        super().__init__(config)
        self._cache: dict[int, tuple[float | None, ...]] = {}

    def get_laplace_noise_scale(self, node: Rel, col_idx: int) -> float:
        sensitivity = self._sensitivities(node)[col_idx]
        if sensitivity is None:
            raise RewritingException(
                f"sensitivity of output column {col_idx} is undefined; the "
                "column is not an aggregation, so there is no mechanism to "
                "release it"
            )
        return sensitivity / self.config.epsilon

    def _sensitivities(self, node: Rel) -> tuple[float | None, ...]:
        """Per-column sensitivities for ``node``, computed once per node."""
        cached = self._cache.get(id(node))
        if cached is None:
            facts = SimpleSensitivityAnalysis().run(node, self.database).col_facts
            cached = tuple(fact.sensitivity for fact in facts)
            self._cache[id(node)] = cached
        return cached
