"""Static analyses over the relational IR."""

from .histogram import (
    AGGREGATION_DOMAIN,
    AggregationDomain,
    AggregationInfo,
    HistogramAnalysis,
    QualifiedColumnName,
)
from .sensitivity import (
    SENSITIVITY_DOMAIN,
    STABILITY_DOMAIN,
    ColSensitivity,
    RelStability,
    SensitivityDomain,
    SimpleSensitivityAnalysis,
    StabilityDomain,
)
from .taint import TaintAnalysis

__all__ = [
    "AGGREGATION_DOMAIN",
    "AggregationDomain",
    "AggregationInfo",
    "ColSensitivity",
    "HistogramAnalysis",
    "QualifiedColumnName",
    "RelStability",
    "SENSITIVITY_DOMAIN",
    "STABILITY_DOMAIN",
    "SensitivityDomain",
    "SimpleSensitivityAnalysis",
    "StabilityDomain",
    "TaintAnalysis",
]
