WITH _domain AS (
  SELECT *
  FROM (SELECT *
  FROM "g0_domain") AS "t",
  (SELECT *
  FROM "g1_g2_domain") AS "t0"
  WHERE "t"."g0" = '0000000243'
)
SELECT "g0", "g1", "g2", MAX("count_b") + 40.0 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "count_b"
FROM (SELECT "g0", "g1", "g2", COUNT(*) AS "count_b"
FROM (SELECT "g0", "g1", "g2"
FROM "table_b") AS "t"
WHERE "g0" = '0000000243'
GROUP BY "g0", "g1", "g2"
UNION ALL
SELECT "g0", "g1", "g2", 0.0 AS "count_b"
FROM "_domain") AS "t3"
GROUP BY "g0", "g1", "g2"
ORDER BY "g0" IS NULL, "g0", "g1" IS NULL, "g1", "g2" IS NULL, "g2";