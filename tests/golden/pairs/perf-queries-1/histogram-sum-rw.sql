WITH _orig AS (
  SELECT g1, g2, SUM(CASE WHEN v1 < 0.0 THEN 0.0 ELSE CASE WHEN v1 > 10000000 THEN 10000000 ELSE v1 END END) _agg2
  FROM table_b
  GROUP BY g1, g2
), _domain AS (
  SELECT *
  FROM g1_g2_domain
)
SELECT _domain.g1 g1, _domain.g2 g2, CASE WHEN _orig._agg2 IS NOT NULL THEN _orig._agg2 ELSE 0 END + 200000000 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) total_v1
FROM _domain
LEFT JOIN _orig ON _domain.g1 = _orig.g1 AND _domain.g2 = _orig.g2
ORDER BY _domain.g1 IS NULL, _domain.g1, _domain.g2 IS NULL, _domain.g2;
