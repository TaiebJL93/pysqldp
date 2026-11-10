# Third-party notices and provenance

`pysqldp` is a Python port of a Scala library with a layered history. The
layers carry different licences, and that affects what may be redistributed.
**Read this before making this repository public or shipping it to anyone.**

## Lineage

```
Uber "Chorus" / sql-differential-privacy   MIT, archived 2019
  └─> Oasis Labs fork                      extended; licence not uniformly stated
        └─> internal fork                  further extensions; private repository
              └─> pysqldp (this project)   Python port
```

Upstream: <https://github.com/uber-archive/sql-differential-privacy>

## What is clearly MIT

The upstream Uber project is MIT-licensed; its `LICENSE` is reproduced in this
repository as [`LICENSE`](LICENSE). 57 of the Scala source files carry that
header, covering:

- the dataflow analysis framework (abstract domains, node/column fact tracking,
  the per-operator transfer function dispatch)
- the schema layer
- the histogram, taint, columns-used, join-keys and name-resolution analyses
- the elastic sensitivity and restricted sensitivity analyses
- the elastic sensitivity, restricted sensitivity, sample-and-aggregate and
  weighted-PINQ rewriters
- the shared rewriting machinery and the coverage rewriter

One further file, `ArithmeticAnalysis.scala`, carries an explicit MIT grant
from Oasis Labs, Inc. (2022).

The Python modules in this repository that follow those files are ports of
MIT-licensed work.

## What is not clearly licensed

Roughly eighteen Scala source files exist only in the forks, carry **no
copyright or licence header**, and are the work of Oasis Labs and the internal
fork's maintainers. They implement:

- `GlobalSensitivityRewriter` — PINQ-style stability sensitivity with Laplace
  noise
- `ClippingRewriter` — bounds `SUM`/`AVG` inputs
- `CensusPercentileRewriter`, `CensusPercentileUnionRewriter`,
  `CensusPercentileUnionMaxRewriter` — `MIN`/`MAX`/percentile via noisy bins
- `MixedRewriter` — combined histogram and percentile dispatch
- `TruncatingRewriter`, `Truncation`,
  `PretruncatedElasticSensitivityRewriter`,
  `TruncatedElasticSensitivityRewriter` — join truncation to `maxFreq`
- `StddevRewriter` — `VAR`/`STDDEV` decomposition
- `SimpleSensitivityAnalysis`, `SignAnalysis`
- `BasicPipeline`, `BasicPipelineBMW` — the public entry points
- `PreviewGenerator`

The following modules in this repository are ports of that unlicensed work, and
inherit its unresolved status:

| This repository | Ported from |
|---|---|
| `src/pysqldp/analysis/sensitivity.py` | `SimpleSensitivityAnalysis.scala` |
| `src/pysqldp/rewriting/clipping.py` | `ClippingRewriter.scala` |
| `src/pysqldp/rewriting/sensitivity.py` | `SensitivityRewriter.scala`, `GlobalSensitivityRewriter.scala` |
| `src/pysqldp/rewriting/dputil.py` | `DPUtil.scala` |
| `src/pysqldp/pipeline.py` | `BasicPipeline.scala` |

`SensitivityRewriter.scala` and `DPUtil.scala` exist upstream under MIT but were
substantially extended in the forks, so the ports follow the extended versions.

**Consequence:** this repository is private for that reason. Making it public,
or distributing it outside the organisation that owns the internal fork,
requires clearance from the owners of that fork. Nothing here constitutes legal
advice or a licence grant.

## Test fixtures

Copied verbatim from the Scala project, with the same provenance caveats:

- `tests/fixtures/schema.yaml`, `tests/fixtures/schema_2.yaml` — from
  `src/test/resources/`
- `tests/golden/*.sql` (15 files) — rewritten-query outputs written by
  `SampleSmokeTest`, used here as the parity oracle

## Runtime dependencies

| Dependency | Licence | Role |
|---|---|---|
| [sqlglot](https://github.com/tobymao/sqlglot) | MIT | SQL parsing, AST, dialect generation — replaces Apache Calcite |
| [PyYAML](https://pyyaml.org/) | MIT | reads the schema file |

Development only:

| Dependency | Licence | Role |
|---|---|---|
| [pytest](https://pytest.org/) | MIT | test runner |
| [DuckDB](https://duckdb.org/) | MIT | executes rewritten SQL in tests, replacing the Docker/Presto/MySQL harness |

Apache Calcite (Apache-2.0) and the Presto parser are **not** dependencies of
this port; they were dependencies of the Scala original.

## Papers the mechanisms come from

The mechanisms are published research. These are the sources, and they are also
the basis on which a clean-room reimplementation could be built if the
provenance above proves blocking:

- Johnson, Near, Song. *Towards Practical Differential Privacy for SQL
  Queries.* <https://arxiv.org/abs/1706.09479> (elastic sensitivity)
- Johnson, Near, Hellerstein, Song. *Chorus: a Programming Framework for
  Building Scalable Differential Privacy Mechanisms.*
  <https://arxiv.org/abs/1809.07750>
- Dwork, McSherry, Nissim, Smith. *Calibrating Noise to Sensitivity in Private
  Data Analysis.* TCC 2006 (the Laplace mechanism)
- McSherry. *Privacy Integrated Queries.* SIGMOD 2009 (stability / PINQ)
- Nissim, Raskhodnikova, Smith. *Smooth Sensitivity and Sampling in Private
  Data Analysis.* STOC 2007 (smooth sensitivity, sample and aggregate)
- Ding, Wang, Wang, Zhang, Kifer. *Detecting Violations of Differential
  Privacy.* CCS 2018 (StatDP, the planned statistical validation)
