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
SELECT *, 0 FROM _domain
WHERE NOT EXISTS (
    SELECT 1 FROM _orig
    WHERE
        _orig.g0 = _domain.g0 AND
        _orig.g1 = _domain.g1 AND
        _orig.g2 = _domain.g2
)
ORDER BY 1, 2, 3;
