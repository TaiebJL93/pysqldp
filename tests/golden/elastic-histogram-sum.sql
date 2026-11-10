WITH _domain AS (
  SELECT *
  FROM "g1_g2_domain"
)
SELECT "_domain"."g1", "_domain"."g2", CASE WHEN "t0"."total_v1" IS NOT NULL THEN "t0"."total_v1" ELSE 0 END + 400000000 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "total_v1"
FROM (SELECT "g1", "g2", SUM(CASE WHEN "v1" < 0.0 THEN 0.0 ELSE CASE WHEN "v1" > 10000000 THEN 10000000 ELSE "v1" END END) AS "total_v1"
FROM "table_b"
GROUP BY "g1", "g2") AS "t0"
RIGHT JOIN "_domain" ON "t0"."g1" = "_domain"."g1" AND "t0"."g2" = "_domain"."g2"
ORDER BY "_domain"."g1" IS NULL, "_domain"."g1", "_domain"."g2" IS NULL, "_domain"."g2";