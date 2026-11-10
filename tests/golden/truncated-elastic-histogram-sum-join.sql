WITH _domain AS (
  SELECT *
  FROM "g1_g2_domain"
)
SELECT "_domain"."g1", "_domain"."g2", CASE WHEN "t4"."total_v1" IS NOT NULL THEN "t4"."total_v1" ELSE 0 END + 5000000000 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "total_v1"
FROM (SELECT "t1"."g1", "t1"."g2", SUM(CASE WHEN "t1"."v1" < 0.0 THEN 0.0 ELSE CASE WHEN "t1"."v1" > 10000000 THEN 10000000 ELSE "t1"."v1" END END) AS "total_v1"
FROM (SELECT "g1", "g2", "ja1", "v1"
FROM (SELECT "b_id", "g0", "g1", "g2", "ja1", "ja2", "v1", "v2", ROW_NUMBER() OVER (PARTITION BY "ja1") AS "_row_number_ja1", ROW_NUMBER() OVER (PARTITION BY "ja2") AS "_row_number_ja2"
FROM "table_b") AS "t"
WHERE "_row_number_ja1" <= 25 AND "_row_number_ja2" <= 100) AS "t1"
INNER JOIN (SELECT "a_id"
FROM "table_a") AS "t2" ON "t1"."ja1" = "t2"."a_id"
GROUP BY "t1"."g1", "t1"."g2") AS "t4"
RIGHT JOIN "_domain" ON "t4"."g1" = "_domain"."g1" AND "t4"."g2" = "_domain"."g2"
ORDER BY "_domain"."g1" IS NULL, "_domain"."g1", "_domain"."g2" IS NULL, "_domain"."g2";