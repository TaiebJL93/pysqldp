WITH _domain AS (
  SELECT *
  FROM "g1_g2_domain"
)
SELECT "_domain"."g1", "_domain"."g2", CASE WHEN "t2"."total_v1" IS NOT NULL THEN "t2"."total_v1" ELSE 0 END + 5000000000 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "total_v1"
FROM (SELECT "t"."g1", "t"."g2", SUM(CASE WHEN "t"."v1" < 0.0 THEN 0.0 ELSE CASE WHEN "t"."v1" > 10000000 THEN 10000000 ELSE "t"."v1" END END) AS "total_v1"
FROM (SELECT "g1", "g2", "ja1", "v1"
FROM "table_b") AS "t"
INNER JOIN (SELECT "a_id"
FROM "table_a") AS "t0" ON "t"."ja1" = "t0"."a_id"
GROUP BY "t"."g1", "t"."g2") AS "t2"
RIGHT JOIN "_domain" ON "t2"."g1" = "_domain"."g1" AND "t2"."g2" = "_domain"."g2"
ORDER BY "_domain"."g1" IS NULL, "_domain"."g1", "_domain"."g2" IS NULL, "_domain"."g2";