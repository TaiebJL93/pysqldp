WITH _domain AS (
    SELECT
        g0_domain.g0,
        g1_g2_domain.g1,
        g1_g2_domain.g2
    FROM g0_domain, g1_g2_domain
), _orig AS (
    SELECT
        g0,
        g1,
        g2,
        COUNT(*) AS count_b
    FROM table_b
    GROUP BY 1, 2, 3
)
SELECT
    _domain.g0,
    _domain.g1 AS g1,
    _domain.g2 AS g2,
    CASE WHEN _orig.count_b IS NOT NULL THEN _orig.count_b ELSE 0 END AS count_b
FROM _orig
RIGHT JOIN _domain ON
    _orig.g0 = _domain.g0 AND
    _orig.g1 = _domain.g1 AND
    _orig.g2 = _domain.g2
ORDER BY 1, 2, 3;
