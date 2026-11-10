"""Differential privacy for SQL queries, by query rewriting.

A Python port of the Chorus-derived Scala library. The usual entry point is
:func:`rewrite_fixed_pipeline`, which turns an analytics query into one that
enforces differential privacy on its own results.
"""

from .exceptions import (
    AnalysisException,
    DPException,
    ProtectedBinException,
    RewritingException,
    TransformationException,
    UnsupportedConstructException,
    UnsupportedQueryException,
)
from .pipeline import budget_usage, rewrite_fixed_pipeline
from .schema import Column, Database, Schema, Table

__version__ = "0.1.0"

__all__ = [
    "AnalysisException",
    "Column",
    "DPException",
    "Database",
    "ProtectedBinException",
    "RewritingException",
    "Schema",
    "Table",
    "TransformationException",
    "UnsupportedConstructException",
    "UnsupportedQueryException",
    "__version__",
    "budget_usage",
    "rewrite_fixed_pipeline",
]
