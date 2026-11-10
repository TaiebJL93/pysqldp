SELECT
    g1,
    g2,
    APPROX_PERCENTILE(v1, 0.9) AS p90_v1
FROM table_b
JOIN table_a ON table_b.ja1 = table_a.a_id
GROUP BY 1, 2
ORDER BY 1, 2;
