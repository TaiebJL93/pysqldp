WITH _orig AS (
  SELECT "g0", "g1", "g2", COUNT(*) AS "count_b"
  FROM "table_b"
  GROUP BY "g0", "g1", "g2"
), _domain AS (
  SELECT *
  FROM (SELECT *
  FROM "g0_domain") AS "t",
  (SELECT *
  FROM "g1_g2_domain") AS "t0"
)
SELECT "g0", "g1", "g2", "count_b" + 40.0 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "count_b"
FROM (SELECT *
FROM "_orig"
UNION ALL
SELECT "_domain"."g0", "_domain"."g1", "_domain"."g2", 0.0 AS "count_b"
FROM "_domain"
LEFT JOIN (SELECT "g0", "g1", "g2", "count_b", TRUE AS "_seen"
FROM "_orig") AS "t" ON "_domain"."g0" = "t"."g0" AND "_domain"."g1" = "t"."g1" AND "_domain"."g2" = "t"."g2"
WHERE "t"."_seen" IS NULL) AS "t2"
ORDER BY "g0" IS NULL, "g0", "g1" IS NULL, "g1", "g2" IS NULL, "g2";