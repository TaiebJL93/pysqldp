SELECT
    g1,
    g2,
    AVG(v1) AS avg_v1
FROM table_b
GROUP BY
    1, 2
ORDER BY
    1, 2;
