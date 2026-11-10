WITH _domain AS (
  SELECT *
  FROM g1_g2_domain
)
SELECT _domain.g1 g1, _domain.g2 g2, CASE WHEN t2.total_v1 IS NOT NULL THEN t2.total_v1 ELSE 0 END + 73071911668.98811 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) total_v1
FROM (SELECT t.g1, t.g2, SUM(CASE WHEN t.v1 < 0.0 THEN 0.0 ELSE CASE WHEN t.v1 > 10000000 THEN 10000000 ELSE t.v1 END END) total_v1
FROM (SELECT g1, ja1, v1, g2
FROM table_b) t
INNER JOIN (SELECT a_id
FROM table_a) t0 ON t.ja1 = t0.a_id
GROUP BY t.g1, t.g2) t2
RIGHT JOIN _domain ON t2.g1 = _domain.g1 AND t2.g2 = _domain.g2
ORDER BY _domain.g1 IS NULL, _domain.g1, _domain.g2 IS NULL, _domain.g2;