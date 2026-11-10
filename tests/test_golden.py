"""Parity against the Scala project's committed rewriter output.

Two kinds of oracle, both copied verbatim from the Scala project, which cannot
be built on this machine:

``tests/golden/pairs/<dir>/<name>-{orig,rw,actual}.sql``
    The Scala perf harness's queries. ``-orig`` is the analyst's query and
    ``-rw`` what the Scala rewriter produced for it, so the input is known and
    nothing has to be hand-written. ``-actual``, where present, is the exact
    non-private query used as ground truth in the accuracy experiments (e.g.
    ``MAX`` standing in for ``APPROX_PERCENTILE``); it is not a rewriter
    output. These are the preferred oracle, because both mechanism and noise
    scale must match.

``tests/golden/*.sql``
    Rewritten-only output from the Scala smoke tests. With no input query on
    disk, the one reproduced here needs a hand-written ``REFERENCE_QUERY``.

The comparison is structural, not byte for byte: the Scala output went through
Calcite's SQL writer (and the perf queries were tidied by hand into ``_orig``
CTEs and LEFT JOINs), while this port emits through sqlglot. What must agree
is which tables are read, whether the aggregate's input is clipped, whether
missing bins are coalesced, the shape of the noise term — and, for pairs,
the exact noise scales, since that is where a wrong mechanism hides.
"""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot import exp

from pysqldp import rewrite_fixed_pipeline
from pysqldp.schema import Database

from .conftest import EPSILON, GOLDEN

#: Goldens the walking skeleton cannot produce yet, and what each one needs.
#: Kept as an explicit inventory so the gap stays visible rather than implied
#: by a missing test.
PENDING = {
    "elastic-cdf-max.sql": "census percentile mechanism",
    "elastic-cdf-max-join.sql": "census percentile mechanism, joins",
    "elastic-histogram-sum-join.sql": "elastic sensitivity, joins",
    "cdf-union.sql": "percentile mechanism, UNION_ALL_JOIN bin filling",
    "cdf-union-max.sql": "percentile mechanism, UNION_ALL_MAX bin filling",
    "union.sql": "UNION_ALL_JOIN bin filling",
    "union-max.sql": "UNION_ALL_MAX bin filling",
    "mixed.sql": "mixed histogram/percentile pipeline",
    "swap-pretruncated-mixed.sql": "mixed pipeline, pretruncated tables",
    "pretruncated-elastic-cdf-max-join.sql": "percentile, pretruncated, joins",
    "pretruncated-elastic-histogram-sum-join.sql": "pretruncated tables, joins",
    "swap-pretruncated-elastic-histogram-sum-join.sql": "pretruncated tables, joins",
    "truncated-elastic-cdf-max-join.sql": "truncating rewriter, percentile, joins",
    "truncated-elastic-histogram-sum-join.sql": "truncating rewriter, joins",
}

#: The one golden whose structure the skeleton reproduces. It is the elastic
#: variant of the same histogram-SUM pipeline, so every structural feature
#: matches and only the noise scale differs.
REFERENCE = "elastic-histogram-sum.sql"

REFERENCE_QUERY = """
    SELECT g1, g2, SUM(v1) AS total_v1
    FROM table_b
    GROUP BY 1, 2
"""


def features(sql: str, dialect: str | None) -> dict[str, object]:
    """Structural facts about a rewritten query.

    Deliberately excludes noise scales and literal formatting: those are what
    the mechanisms are allowed to disagree about.
    """
    tree = sqlglot.parse_one(sql, read=dialect)

    ctes = {
        cte.alias: sorted(table.name for table in cte.this.find_all(exp.Table))
        for cte in tree.find_all(exp.CTE)
    }

    joins = [
        (
            (join.side or "INNER").upper(),
            sorted(
                f"{column.table}.{column.name}"
                for column in (join.args.get("on") or join).find_all(exp.Column)
            ),
        )
        for join in tree.find_all(exp.Join)
    ]

    aggregates = sorted(
        type(node).__name__.upper()
        for node in tree.find_all(exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)
    )

    return {
        "ctes": ctes,
        "joins": joins,
        "aggregates": aggregates,
        # Clipping: the aggregate argument is wrapped in nested CASEs.
        "clips_aggregate_input": any(
            node.find(exp.Case) is not None for node in tree.find_all(exp.Sum)
        ),
        # Bin filling: a NULL aggregate must read as zero before noise.
        "coalesces_missing_bins": any(
            node.find(exp.Is) is not None for node in tree.find_all(exp.Case)
        ),
        # The Laplace sampler, identified by shape rather than by scale.
        "laplace_terms": len(list(tree.find_all(exp.Ln))),
        "uses_random": len(list(tree.find_all(exp.Rand))),
    }


def test_reference_golden_is_the_real_scala_output() -> None:
    """Guard the fixture itself, so the comparison below cannot pass vacuously."""
    golden = (GOLDEN / REFERENCE).read_text(encoding="utf-8")
    assert "RIGHT JOIN" in golden
    assert "RAND()" in golden
    assert "_domain" in golden


def test_skeleton_reproduces_the_reference_golden_structure(
    experiments: Database,
) -> None:
    golden = (GOLDEN / REFERENCE).read_text(encoding="utf-8").rstrip().rstrip(";")
    produced, _ = rewrite_fixed_pipeline(experiments, REFERENCE_QUERY, EPSILON)

    dialect = experiments.sqlglot_dialect
    expected = features(golden, dialect)
    actual = features(produced, dialect)

    # The CTE reads the same domain table, though the Scala output selects *
    # where this port lists the columns it needs.
    assert actual["ctes"].keys() == expected["ctes"].keys()
    assert actual["ctes"]["_domain"] == expected["ctes"]["_domain"]

    assert actual["joins"] == expected["joins"]
    assert actual["aggregates"] == expected["aggregates"]
    assert actual["clips_aggregate_input"] is True
    assert expected["clips_aggregate_input"] is True
    assert actual["coalesces_missing_bins"] is True
    assert expected["coalesces_missing_bins"] is True
    assert actual["laplace_terms"] == expected["laplace_terms"] == 1
    assert actual["uses_random"] == expected["uses_random"] == 2


def test_reference_golden_differs_only_in_noise_scale(experiments: Database) -> None:
    """The scales must differ: elastic and global sensitivity are not the same.

    The golden uses elastic sensitivity; the skeleton uses global sensitivity,
    which scales to the grouping stability times the clipping range. If these
    ever matched, one of the two mechanisms would be mis-scaled.
    """
    golden = (GOLDEN / REFERENCE).read_text(encoding="utf-8")
    produced, _ = rewrite_fixed_pipeline(experiments, REFERENCE_QUERY, EPSILON)

    assert "400000000" in golden
    assert "200000000.0" in produced


@pytest.mark.parametrize("name", sorted(PENDING))
def test_pending_goldens_are_accounted_for(name: str) -> None:
    """Every golden is either reproduced or listed with the mechanism it needs."""
    assert (GOLDEN / name).exists(), f"golden fixture {name} is missing"
    pytest.skip(f"{name} needs: {PENDING[name]}")


def test_golden_inventory_is_complete() -> None:
    """No golden file is silently ignored."""
    on_disk = {path.name for path in GOLDEN.glob("*.sql")}
    accounted = set(PENDING) | {REFERENCE}
    assert on_disk == accounted


# --- orig/rw pairs ----------------------------------------------------------

PAIRS = GOLDEN / "pairs"

#: Pairs whose ``-orig`` the pipeline rewrites into the matching ``-rw``.
REPRODUCED_PAIRS = [
    "perf-queries-1/histogram-sum",
    "perf-queries-1/histogram-avg",
]

#: Pairs the pipeline cannot reproduce yet, and what each one needs.
PENDING_PAIRS = {
    # The Scala smoke test that wrote this used ElasticSensitivityRewriter,
    # whose scale is 40.0; the global-sensitivity pipeline correctly gives 20.0.
    "perf-queries-1/histogram-count": "elastic sensitivity",
    "perf-queries-1/cdf-max": "census percentile mechanism",
    "perf-queries/elastic-histogram-sum-join": "elastic sensitivity, joins",
    "perf-queries/elastic-cdf-max-join": "census percentile, elastic sensitivity, joins",
}

#: The non-private ground-truth queries, named per pair. Not rewriter output:
#: the accuracy experiments compared the private answer against these.
ACTUAL = {
    "perf-queries-1/cdf-max": "MAX stands in for APPROX_PERCENTILE(v1, 0.9)",
    "perf-queries/elastic-cdf-max-join": "MAX stands in for APPROX_PERCENTILE(v1, 0.9)",
}

#: Files in the pairs tree that are not rewriter output, so there is nothing
#: to reproduce. perf-queries-3/4 hold hand-written left/right/union bin-filling
#: variants used to compare engine performance; their ``-orig`` queries group
#: on columns whose domains live in two tables, which the port rejects
#: (cross-table domain construction is not ported).
HAND_WRITTEN = {
    "perf-queries/round-trip-only.sql": "SELECT 1 latency baseline",
    "perf-queries-1/round-trip-only.sql": "SELECT 1 latency baseline",
    "perf-queries-4/round-trip-only.sql": "SELECT 1 latency baseline",
    **{
        f"perf-queries-3/histogram-count-{v}.sql": "hand-written bin-fill variant"
        for v in ("orig", "left", "right", "union")
    },
    **{
        f"perf-queries-4/histogram-count-{v}.sql": "hand-written bin-fill variant"
        for v in ("orig", "left", "right", "union", "union1", "union2", "union3")
    },
}


def _factors(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.Mul):
        return _factors(node.left) + _factors(node.right)
    if isinstance(node, exp.Paren):
        return _factors(node.this)
    return [node]


def noise_scales(sql: str, dialect: str | None) -> list[float]:
    """The Laplace scale of every noise term, sorted.

    The term is ``scale * sign * LN(...)``, but the associativity differs:
    Calcite writes ``scale * (sign * LN(...))``, sqlglot ``(scale * sign) *
    LN(...)``. Flattening the multiplication chain around each LN finds the
    numeric factor either way.
    """
    scales: list[float] = []
    for ln in sqlglot.parse_one(sql, read=dialect).find_all(exp.Ln):
        top: exp.Expression = ln
        while isinstance(top.parent, (exp.Mul, exp.Paren)):
            top = top.parent
        scales += [
            float(f.this)
            for f in _factors(top)
            if isinstance(f, exp.Literal) and f.is_number
        ]
    return sorted(scales)


def pair_features(sql: str, dialect: str | None) -> dict[str, object]:
    """``features`` minus the parts the hand-tidied perf queries reshaped.

    The perf ``-rw`` files lift the aggregate into an ``_orig`` CTE and join it
    with ``_domain LEFT JOIN _orig``; the port emits a subquery and
    ``_orig RIGHT JOIN _domain``. Both keep every domain row, so CTE names and
    join direction are dropped, and replaced by the base tables read and the
    number of outer joins.
    """
    tree = sqlglot.parse_one(sql, read=dialect)
    cte_names = {cte.alias for cte in tree.find_all(exp.CTE)}
    facts = features(sql, dialect)
    del facts["ctes"], facts["joins"]
    facts["tables"] = sorted(
        {t.name for t in tree.find_all(exp.Table)} - cte_names
    )
    facts["outer_joins"] = sum(
        1 for j in tree.find_all(exp.Join) if (j.side or "").upper() in {"LEFT", "RIGHT"}
    )
    facts["noise_scales"] = noise_scales(sql, dialect)
    return facts


def _read(path) -> str:
    return path.read_text(encoding="utf-8").rstrip().rstrip(";")


@pytest.mark.parametrize("name", REPRODUCED_PAIRS)
def test_pipeline_reproduces_pair(name: str, experiments: Database) -> None:
    rewritten = _read(PAIRS / f"{name}-rw.sql")
    produced, _ = rewrite_fixed_pipeline(
        experiments, _read(PAIRS / f"{name}-orig.sql"), EPSILON
    )

    dialect = experiments.sqlglot_dialect
    expected = pair_features(rewritten, dialect)
    # Guard the fixture: a pair with no noise would make the comparison vacuous.
    assert expected["noise_scales"]
    assert pair_features(produced, dialect) == expected


@pytest.mark.parametrize("name", sorted(PENDING_PAIRS))
def test_pending_pairs_are_accounted_for(name: str) -> None:
    assert (PAIRS / f"{name}-orig.sql").exists()
    assert (PAIRS / f"{name}-rw.sql").exists()
    pytest.skip(f"{name} needs: {PENDING_PAIRS[name]}")


def test_pair_inventory_is_complete() -> None:
    """Every file under pairs/ is reproduced, pending, or not rewriter output."""
    on_disk = {p.relative_to(PAIRS).as_posix() for p in PAIRS.rglob("*.sql")}
    accounted = set(HAND_WRITTEN) | {f"{name}-actual.sql" for name in ACTUAL}
    for name in [*REPRODUCED_PAIRS, *PENDING_PAIRS]:
        accounted |= {f"{name}-orig.sql", f"{name}-rw.sql"}
    assert on_disk == accounted
