# Tests used by known issue and mechanism

| Known Issue/mechanism                                                  | Tests                     |
|------------------------------------------------------------------------|---------------------------|
| Known Issue 1 (SUM)                                                    | sst, pp, rt, exs, exr     |
| Known Issue 2 (AVG)                                                    | sst, pp, rt, exs, exr     |
| Known Issue 3 (COUNT)                                                  | sst, pp, rt, exs, exr, db |
| Known Issue 4 (MIN, MAX)                                               | sst, pp, rt, exs, exr, db |
| Known Issue 5 (multiple aggregation functions)                         | sst, pp, rt, exs, exr     |
| Known Issue 6 (ability to keep subquery unchanged)                     | sst, rt                   |
| Laplace noise mechanism (COUNT)                                        | pp, rt, exs, acc          |
| Laplace noise with clipping mechnanism (SUM)                           | pp, exs, acc              |
| Laplace noise with clipping and aggregation reduction mechnanism (AVG) | pp, exs, acc              |
| Census percentile mechanism (MIN, MAX)                                 | pp, exs, acc              |

# Rewriting smoke tests (sst)
We use a unit test to rewrite a sample query that exercises the functionality added or changed for this Known Issue.
The unit test rewrites the query with a suitable pipeline.
Running this test verifies that the rewriting pipeline does not crash.
These tests are in `SampleSmokeTest.scala`.

# Rewritten query inspection (pp)
We manually inspect the rewritten query from the unit test to verify that it correctly implements the abstract
mechanism.
We inspect two forms of the rewritten query:
(i) the relational algebra graph and
(ii) the SQL code.
The unit test prints these two forms as it runs.
In some of these tests, we additionally inspect intermediate relational algebra graphs created within the rewriting
pipeline.

# Chorus regression tests (rt)
We run the full suite of unit tests from the stock Chorus distribution to check for regressions.
In some cases, rewritten query outputs are changed.
When they are, we manually review the differences to ensure that the change does not affect the meaning of the
rewritten query, and we update the expected output.
These tests are in the `/src/test` directory.

# Rewritten queries smoke tests (exs)
We run the sample query and the rewritten query on a real DBMS (Presto with MySQL connector).
Running this test verifies that the rewritten query is syntactically correct.
These tests are in the `/scripts` directory.

# Rewritten queries basic results checks (exr)
We manually perform basic checks on the output of the rewritten query.
We verify that
(i) the result row has the correct fields and types,
(ii) the expected rows are present in the result, and
(iii) the result is in the correct order.
In some tests, such as when the results should all be nonnegative, we verify that the results have the right sign too.

# Accuracy tests (acc)
We run a representative representative query many times and inspect the distribution of outputs.
We verify that the distribution is close to the result of a reference non-private query.

These tests are done on datasets of 1k records per relation, 1M records per relation, and 10M records per relation.

The detailed description of these tests and the results are in `/docs/accuracy_report.pdf`.
The code for these tests is in `accuracy_tests.py`.

# DBMS implementation tests (db)
We run some simple diagnostic queries to determine how the DBMS (Presto with MySQL connector) implements some SQL
constructs.
We use feedback from these tests to guide the development of the changes.
