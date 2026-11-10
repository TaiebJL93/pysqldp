# Tests used by mechanism

| Known Issue/mechanism                                                  | Tests      |
|------------------------------------------------------------------------|------------|
| Laplace noise mechanism (COUNT)                                        | csdp, psdp |
| Laplace noise with clipping mechnanism (SUM)                           | nsdp       |
| Laplace noise with clipping and aggregation reduction mechnanism (AVG) | nsdp       |
| Census percentile mechanism (MIN, MAX)                                 | nsdp       |

# Statistical testing, ported (nsdp)
We run the mechanism in Ding et al.'s StatDP framework, which exercises the mechanism on a battery of adjacent database
pairs for many repetitions and detects if the results probabilistically violate differential privacy at a given privacy
budget.

In this "ported" variant, we reimplement a rewritten query from its relational algebra form to NumPy.
These tests are in `statdp_tests.py`.

# Statistical testing, Presto (psdp)
We provide a script that would run the mechanism in Ding et al.'s StatDP framework.

In this "Presto" variant, we execute the mechanism by running a rewritten query over a Python client for Presto.
This turned out to have too much overhead, particularly in repeated query planning.
We weren't able to run this for the default number of iterations.
In the future, if the Presto API add support for prepared queries, the overhead may be reduce to the point where one
could run this script for a smaller number of iterations.
These tests are in `statdp_tests_presto.py`.

# Statistical testing from literature (csdp)
This mechanism is already tested and verified to be correct as part of Ding et al.'s work on StatDP.
