# Performance tests used by known issue

| Known Issue                                        | Tests        |
|----------------------------------------------------|--------------|
| Known Issue 1 (SUM)                                | perf         |
| Known Issue 2 (AVG)                                | perf         |
| Known Issue 3 (COUNT)                              | pt, qp, perf |
| Known Issue 4 (MIN, MAX)                           | pt, qp, perf |
| Known Issue 5 (multiple aggregation functions)     |              |
| Known Issue 6 (ability to keep subquery unchanged) |              |

# Preliminary experiment time (pt)
For earlier versions of the implementations, we recorded the time taken in the preliminary smoke tests.
These tests were run once and do not control for caching effects.

These tests are done on a laptop, on presto-server 0.234.1 configured with a memory connector, on a dataset of 1k
records per relation.

| Query summary                                | Original query time | Rewritten query time |
|----------------------------------------------|--------------------:|---------------------:|
| COUNT with multiple GROUP BY                 |               0m00s |                0m01s |
| MIN and MAX each on two columns, no GROUP BY |               0m00s |                0m01s |

# Query plan inspection (qp)
We run an "EXPLAIN" on the rewritten query in Presto.
We manually inspect the query plan to verify that there are no unjustified inefficiencies.

These tests are done on presto-server 0.234.1 configured with a MySQL connector.

# Performance tests (perf)
We run a representative rewritten query and record the time taken.
We report these times in comparison with a reference non-private query.

These tests are done on a laptop, on presto-server 0.234.1 configured with a memory connector, on datasets of 1k
records per relation, 1M records per relation, and 10M records per relation.

The detailed description of these tests and the results are in `/docs/perf_report.pdf`.
The code for these tests is in `run-perf.sh`.
