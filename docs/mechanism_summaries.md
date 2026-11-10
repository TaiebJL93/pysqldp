# COUNT queries

COUNT queries have the following form:

```
SELECT COUNT(*)
FROM T
WHERE a
  AND b
  ...
```

The global sensitivity mechanism for COUNT queries is implemented in
two pieces:

1. A global sensitivity analysis on the original query
2. A rewriter that adds Laplace noise to the output

## Sensitivity Analysis

The sensitivity analysis is implemented in the
`SimpleSensitivityAnalysis` class. This analysis works for SELECT
queries over a single table. It tracks stability of the relational
transformation encoded by the query, in the style of PINQ [1], and
then reports the sensitivity of each COUNT column as equal to the
stability of the underlying relation (since the sensitivity of COUNT
is 1). 

This analysis fails for queries with joins and queries with
aggregation queries other than COUNT.

The analysis ensures that for a query q, running q on two neighboring
databases produces two outputs whose difference is bounded by s. In
other words:

    d(x, y) ≤ 1 ⇒ ‖q(x) - q(y)‖₁ ≤ s

Here, `s` is the global L1 sensitivity of the query, and `d` is a
*distance metric* that computes the distance between the databases `x`
and `y`. The sensitivity analysis calculates a conservative
approximation of the number `s`.

## Laplace Noise Rewriter

The Laplace noise rewriter calculates the global sensitivity for each
column in the query using the sensitivity analysis described above. It
rewrites the query to generate Laplace noise scaled to s/ε, where s is
the sensitivity of the column and ε is the privacy parameter.

For a query q with global L1 sensitivity s, the Laplace mechanism
releases the following:

    q(x) + (y₁, ..., yₙ)
  
where `(y₁, ..., yₙ)` is a vector of samples drawn iid from the
Laplace distribution with center 0 and scale `s/ε`. This mechanism
satisfies ε-differential privacy [2].

The implementation of this rewriter is in the
`GlobalSensitivityRewriter` class. It uses the DBMS's RAND() function
to generate noise from the uniform distribution. A uniform sample
between -0.5 and 0.5 can be converted into a sample from the Laplace
distribution according to the following equation [3]:

    yᵢ = (s/ε) sign(Uᵢ) log(1 - 2|Uᵢ|)


## Accuracy

By the definition of the Laplace mechanism [2], this solution produces
(α, β)-accuracy for:

    α = (s/ε) log(1/β)

Where (α, β)-accuracy for query `q` and mechanism `m` means that:

    Pr[|q(x) - m(x)| ≥ α] ≤ β

# SUM Queries

SUM queries are queries of the form:

```
SELECT SUM(c)
FROM T
WHERE a
  AND b
  ...
```

The global sensitivity mechanism for SUM queries is implemented in
three pieces:

1. A clipping rewriter that bounds the values of the summed column
2. A global sensitivity analysis on the result of (1)
2. A rewriter that adds Laplace noise to the output of (1)

## Clipping Rewriter

The clipping rewriter is implemented in the `ClippingRewriter`
class. This rewriter "clips" the data being aggregated by forcing each
value being aggregated to lie between upper and lower bounds using a
`CASE` expression:

```
CASE WHEN c > upper THEN upper ELSE
  (CASE WHEN c < lower THEN lower ELSE c END) END
```

## Sensitivity Analysis

The sensitivity analysis is the same as in the `COUNT` mechanism,
except that columns with `CASE` expressions are tagged in the abstract
domain with their upper and lower bounds. This tagging detects the
clipping inserted by the clipping rewriter and tracks the sensitivity
effects of it. Specifically, for an expression like the above example,
the abstract domain records an upper bound of `upper` and a lower
bound of `lower`. For a `SUM` aggregation like the following:

```
SUM(
  CASE WHEN c > upper THEN upper ELSE
    (CASE WHEN c < lower THEN lower ELSE c END) END)
```

The sensitivity of the `SUM` aggregation is equal to the difference
between the lower and upper bound. If a row is added or deleted in the
database, then either:

- It is below `lower`, in which case the sum increases/decreases by `lower`
- It is between `lower` and `upper`, in which case the
  increase/decrease in the sum is bounded by `lower` and `upper`
- It is above `upper`, in which case the sum increases/decreases by `upper`

That is, for a `SUM` aggregation, the sensitivity `s = upper - lower`.

We require that `upper - lower ≥ 1`, to prevent the use of SUM for
counting after filtering.

## Laplace Noise Rewriter

Same as the `COUNT` mechanism. By the definition of the Laplace
mechanism, provides ε-differential privacy.

## Accuracy

By the definition of the Laplace mechanism [2], this solution produces
(α, β)-accuracy for:

    α = (s/ε) log(1/β)

In the case of `SUM` aggregations, `s = upper - lower`, so error goes
up as the difference between `upper` and `lower` increases.

# AVG Queries

AVG queries have the form:

```
SELECT AVG(c)
FROM T
WHERE a
  AND b
  ...
```

To answer an AVG query, the global sensitivity mechanism rewrites the
`AVG` aggregation function to produce, conceptually, two new queries:

```
SELECT SUM(c)
FROM T
WHERE a
  AND b
  ...
```

```
SELECT COUNT(c)
FROM T
WHERE a
  AND b
  ...
```

The first query can be answered using the SUM mechanism above, and the
second by the COUNT mechanism. The average can be calculated by
dividing the first by the second.

This approach effectively runs two differentially private queries, and
splits the privacy budget across the two. By sequential composition
[1,2], if we set εᵢ = ε/2 for each of the two queries, then the total
privacy cost sums to ε.



# References

[1] McSherry, Frank D. "Privacy integrated queries: an extensible
platform for privacy-preserving data analysis." Proceedings of the
2009 ACM SIGMOD International Conference on Management of data. 2009.

[2] Dwork, Cynthia, et al. "Calibrating noise to sensitivity in
private data analysis." Theory of cryptography conference. Springer,
Berlin, Heidelberg, 2006.

[3] https://en.wikipedia.org/wiki/Laplace_distribution
