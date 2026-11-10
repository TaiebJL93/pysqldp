"""Parity against the Scala project's committed rewriter output.

``tests/golden/*.sql`` are the rewritten queries the Scala smoke tests wrote
out, copied verbatim. They are the only oracle available here — the Scala
project cannot be built on this machine — so they are what the port is checked
against.

The mechanisms differ in the noise *scale* they choose, which is the whole
point of having more than one, so comparing generated SQL byte for byte would
only prove the two mechanisms are the same. These tests compare structural
features instead: which tables are read, how the bin domain is joined on,
whether the aggregate's input is clipped, and whether the noise term has the
right shape. Those are the parts every sensitivity mechanism must share, and
they are where a port goes wrong.
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
