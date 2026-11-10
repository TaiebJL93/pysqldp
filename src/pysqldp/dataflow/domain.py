"""Abstract domains.

Port of ``com.uber.engsec.dp.dataflow.domain``. A domain supplies a least
element and a join, which is all the analysis engine needs to merge facts
arriving from several inputs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, Iterable, TypeVar

T = TypeVar("T")


class AbstractDomain(ABC, Generic[T]):
    """A join semilattice over analysis facts."""

    @property
    @abstractmethod
    def bottom(self) -> T:
        """The least element: what is known before anything is analysed."""

    @abstractmethod
    def least_upper_bound(self, left: T, right: T) -> T:
        """Merge two facts conservatively."""

    def join(self, facts: Iterable[T]) -> T:
        """Merge any number of facts, starting from :attr:`bottom`."""
        result = self.bottom
        for fact in facts:
            result = self.least_upper_bound(result, fact)
        return result


class UnitDomain(AbstractDomain[None]):
    """Carries no information. Used by rewriters that need no analysis state."""

    @property
    def bottom(self) -> None:
        return None

    def least_upper_bound(self, left: None, right: None) -> None:
        return None


class BooleanDomain(AbstractDomain[bool]):
    """``False`` is bottom; the join is logical or."""

    @property
    def bottom(self) -> bool:
        return False

    def least_upper_bound(self, left: bool, right: bool) -> bool:
        return left or right


class MaxDomain(AbstractDomain[float]):
    """Numeric facts merged by taking the maximum. Bottom is ``0.0``."""

    @property
    def bottom(self) -> float:
        return 0.0

    def least_upper_bound(self, left: float, right: float) -> float:
        return max(left, right)


class _Sentinel:
    """A singleton marker with a readable repr."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return self._name


#: Nothing is known yet.
BOTTOM = _Sentinel("BOTTOM")
#: Conflicting values were merged, so nothing definite is known.
TOP = _Sentinel("TOP")


class FlatLatticeDomain(AbstractDomain[object]):
    """Port of ``FlatLatticeDomain``: bottom, one definite value, or top.

    Merging two different values yields :data:`TOP`, which is how the histogram
    analysis records that a column has no single outermost aggregation.
    """

    @property
    def bottom(self) -> object:
        return BOTTOM

    def least_upper_bound(self, left: object, right: object) -> object:
        if left is BOTTOM:
            return right
        if right is BOTTOM:
            return left
        if left is TOP or right is TOP:
            return TOP
        return left if left == right else TOP

    @staticmethod
    def value_of(element: object) -> object | None:
        """The definite value, or None for bottom/top."""
        return None if element is BOTTOM or element is TOP else element


#: Shared instances; the domains are stateless.
UNIT_DOMAIN = UnitDomain()
BOOLEAN_DOMAIN = BooleanDomain()
MAX_DOMAIN = MaxDomain()
FLAT_LATTICE_DOMAIN = FlatLatticeDomain()
