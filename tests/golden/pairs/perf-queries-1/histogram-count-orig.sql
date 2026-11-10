SELECT
    g1,
    g2,
    COUNT(*) AS count_b
FROM table_b
GROUP BY
    1, 2
ORDER BY
    1, 2;
