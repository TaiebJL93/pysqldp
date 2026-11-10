"""Exception hierarchy, ported from com.uber.engsec.dp.exception."""


class DPException(Exception):
    """Base class for all pysqldp errors."""


class AnalysisException(DPException):
    """Raised when a dataflow analysis cannot produce a sound result."""


class TransformationException(DPException):
    """Raised when the relational IR cannot be built or emitted."""


class UnsupportedQueryException(TransformationException):
    """The query uses a construct this port does not support yet.

    Raised rather than falling back to a weaker rewrite: emitting SQL with too
    little noise would be a privacy violation, so refusing is the safe default.
    """


class UnsupportedConstructException(UnsupportedQueryException):
    """A specific SQL construct has no mapping in the relational IR."""


class RewritingException(DPException):
    """The query cannot be rewritten into a private form.

    Typically means required schema metadata is missing (``clipLower``,
    ``clipUpper``, ``domainSet``) or the query shape defeats the mechanism.
    """


class ProtectedBinException(RewritingException):
    """A histogram bin column is not marked ``canRelease`` in the schema."""

    def __init__(self, bin_name: str) -> None:
        super().__init__(
            f"Histogram bin column {bin_name!r} is not safe for release. "
            "Set 'canRelease: true' on the column in the schema if its values "
            "may appear in query output."
        )
        self.bin_name = bin_name
