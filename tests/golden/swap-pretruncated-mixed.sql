WITH _domain AS (
  SELECT *
  FROM "g1_g2_domain"
), _bins2 AS (
  SELECT *
  FROM "_domain",
  (VALUES (0),
  (1),
  (2),
  (3),
  (4),
  (5),
  (6),
  (7),
  (8),
  (9),
  (10),
  (11),
  (12),
  (13),
  (14),
  (15),
  (16),
  (17),
  (18),
  (19),
  (20),
  (21),
  (22),
  (23),
  (24),
  (25),
  (26),
  (27),
  (28),
  (29),
  (30),
  (31),
  (32),
  (33),
  (34),
  (35),
  (36),
  (37),
  (38),
  (39),
  (40),
  (41),
  (42),
  (43),
  (44),
  (45),
  (46),
  (47),
  (48),
  (49),
  (50),
  (51),
  (52),
  (53),
  (54),
  (55),
  (56),
  (57),
  (58),
  (59),
  (60),
  (61),
  (62),
  (63),
  (64),
  (65),
  (66),
  (67),
  (68),
  (69),
  (70),
  (71),
  (72),
  (73),
  (74),
  (75),
  (76),
  (77),
  (78),
  (79),
  (80),
  (81),
  (82),
  (83),
  (84),
  (85),
  (86),
  (87),
  (88),
  (89),
  (90),
  (91),
  (92),
  (93),
  (94),
  (95),
  (96),
  (97),
  (98),
  (99)) AS "t" ("_bin")
), _input AS (
  SELECT "t"."g1", "t"."g2", "t"."v1", 0.3 AS "_f3"
  FROM (SELECT "g1", "g2", "ja1", "v1"
  FROM "table_b") AS "t"
  INNER JOIN (SELECT "a_id"
  FROM "table_a") AS "t0" ON "t"."ja1" = "t0"."a_id"
), _pdf2 AS (
  SELECT "_bins2"."g1", "_bins2"."g2", "_bins2"."_bin", CASE WHEN "t1"."_cnt_incomplete" IS NOT NULL THEN "t1"."_cnt_incomplete" ELSE 0 END + 500.0 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "_cnt"
  FROM (SELECT "g1" AS "g1_incomplete", "g2" AS "g2_incomplete", FLOOR(("v1" - 0.0) / 100000.0) AS "_bin_incomplete", COUNT(*) AS "_cnt_incomplete"
  FROM "_input"
  GROUP BY "g1", "g2", FLOOR(("v1" - 0.0) / 100000.0)) AS "t1"
  RIGHT JOIN "_bins2" ON "t1"."g1_incomplete" = "_bins2"."g1" AND "t1"."g2_incomplete" = "_bins2"."g2" AND "t1"."_bin_incomplete" = "_bins2"."_bin"
), _cdf2 AS (
  SELECT "g1", "g2", "_bin", SUM("_cnt") OVER (PARTITION BY "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "_cdist", SUM("_cnt") OVER (PARTITION BY "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS "_tot"
  FROM "_pdf2"
), _noised13212 AS (
  SELECT "_domain"."g1", "_domain"."g2", CASE WHEN "t2"."total_v1" IS NOT NULL THEN "t2"."total_v1" ELSE 0 END + 5000000000 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "total_v1", CASE WHEN "t2"."count_b" IS NOT NULL THEN "t2"."count_b" ELSE 0 END + 500.0 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "count_b"
  FROM (SELECT "t"."g1", "t"."g2", COALESCE(SUM(CASE WHEN "t"."v1" < 0.0 THEN 0.0 ELSE CASE WHEN "t"."v1" > 10000000 THEN 10000000 ELSE "t"."v1" END END), 0) AS "total_v1", COUNT(*) AS "count_b"
  FROM (SELECT "g1", "g2", "ja1", "v1"
  FROM "table_b") AS "t"
  INNER JOIN (SELECT "a_id"
  FROM "table_a") AS "t0" ON "t"."ja1" = "t0"."a_id"
  GROUP BY "t"."g1", "t"."g2") AS "t2"
  RIGHT JOIN "_domain" ON "t2"."g1" = "_domain"."g1" AND "t2"."g2" = "_domain"."g2"
), _sign_fixed13212 AS (
  SELECT "g1", "g2", CASE WHEN "total_v1" < 0.5 THEN 0.5 - 5000000000 * LN(1 - 2 * ABS(RAND() - 0.5)) ELSE "total_v1" END AS "total_v1", CASE WHEN "count_b" < 0.5 THEN 0.5 - 500.0 * LN(1 - 2 * ABS(RAND() - 0.5)) ELSE "count_b" END AS "count_b"
  FROM "_noised13212"
)
SELECT "t"."g1", "t"."g2", "t9"."max_v1", "t"."total_v1", "t"."count_b", "t"."avg_v1", "t9"."min_v1", "t9"."p30_v1"
FROM (SELECT "g1", "g2", "total_v1", "count_b", "total_v1" / "count_b" AS "avg_v1"
FROM "_sign_fixed13212") AS "t"
INNER JOIN (SELECT "t2"."g1", "t2"."g2", "t2"."max_v1", "t5"."min_v1", "t8"."p30_v1"
FROM (SELECT "g1", "g2", CAST(0.0 + MIN("_bin") * 100000.0 AS DOUBLE) AS "max_v1"
FROM "_cdf2"
WHERE "_cdist" > "_tot" * 0.9
GROUP BY "g1", "g2") AS "t2"
INNER JOIN (SELECT "g1", "g2", CAST(0.0 + MIN("_bin") * 100000.0 AS DOUBLE) AS "min_v1"
FROM "_cdf2"
WHERE "_cdist" > "_tot" * 0.1
GROUP BY "g1", "g2") AS "t5" ON "t2"."g1" = "t5"."g1" AND "t2"."g2" = "t5"."g2"
INNER JOIN (SELECT "g1", "g2", CAST(0.0 + MIN("_bin") * 100000.0 AS DOUBLE) AS "p30_v1"
FROM "_cdf2"
WHERE "_cdist" > "_tot" * 0.3
GROUP BY "g1", "g2") AS "t8" ON "t2"."g1" = "t8"."g1" AND "t2"."g2" = "t8"."g2") AS "t9" ON "t"."g1" = "t9"."g1" AND "t"."g2" = "t9"."g2"
ORDER BY "t"."g1" IS NULL, "t"."g1", "t"."g2" IS NULL, "t"."g2";