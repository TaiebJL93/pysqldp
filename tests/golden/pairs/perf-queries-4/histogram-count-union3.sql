WITH _domain AS (
    SELECT
        g0_domain.g0,
        g1_g2_domain.g1,
        g1_g2_domain.g2
    FROM g0_domain, g1_g2_domain
    WHERE g0_domain.g0 = '0000000676'
), _orig AS (
    SELECT
        g0,
        g1,
        g2,
        COUNT(*) AS count_b
    FROM table_b
    WHERE g0 = '0000000676'
    GROUP BY 1, 2, 3
)
SELECT * FROM _orig
UNION ALL
SELECT
    _domain.g0,
    _domain.g1 AS g1,
    _domain.g2 AS g2,
    0
FROM _domain
LEFT JOIN (
    SELECT
        g0,
        g1,
        g2,
        TRUE AS _seen
    FROM _orig
) t ON
    _domain.g0 = t.g0 AND
    _domain.g1 = t.g1 AND
    _domain.g2 = t.g2
WHERE t._seen IS NULL
ORDER BY 1, 2, 3;
