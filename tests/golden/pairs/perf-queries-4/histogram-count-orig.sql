SELECT
    g0,
    g1,
    g2,
    COUNT(*) AS count_b
FROM table_b
WHERE g0 = '0000000676'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
