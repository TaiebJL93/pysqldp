WITH _domain AS (
  SELECT *
  FROM (SELECT *
  FROM "g0_domain") AS "t",
  (SELECT *
  FROM "g1_g2_domain") AS "t0"
  WHERE "t"."g0" = '0000000243'
), _bins4 AS (
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
  SELECT *
  FROM (SELECT "g0", "g1", "g2", "v1", "v2"
  FROM "table_b") AS "t"
  WHERE "g0" = '0000000243'
), _pdf4_clear AS (
  SELECT "g0", "g1", "g2", FLOOR(("v2" - 0.0) / 150000.0) AS "_bin", COUNT(*) AS "_cnt"
  FROM "_input"
  GROUP BY "g0", "g1", "g2", FLOOR(("v2" - 0.0) / 150000.0)
), _pdf4 AS (
  SELECT "g0", "g1", "g2", "_bin", MAX("_cnt") + 20.0 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "_cnt"
  FROM (SELECT *
  FROM "_pdf4_clear"
  UNION ALL
  SELECT "g0", "g1", "g2", "_bin", 0.0 AS "_cnt"
  FROM "_bins4") AS "t0"
  GROUP BY "g0", "g1", "g2", "_bin"
), _cdf4 AS (
  SELECT "g0", "g1", "g2", "_bin", SUM("_cnt") OVER (PARTITION BY "g0", "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "_cdist", SUM("_cnt") OVER (PARTITION BY "g0", "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS "_tot"
  FROM "_pdf4"
), _bins3 AS (
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
), _pdf3_clear AS (
  SELECT "g0", "g1", "g2", FLOOR(("v1" - 0.0) / 100000.0) AS "_bin", COUNT(*) AS "_cnt"
  FROM "_input"
  GROUP BY "g0", "g1", "g2", FLOOR(("v1" - 0.0) / 100000.0)
), _pdf3 AS (
  SELECT "g0", "g1", "g2", "_bin", MAX("_cnt") + 20.0 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "_cnt"
  FROM (SELECT *
  FROM "_pdf3_clear"
  UNION ALL
  SELECT "g0", "g1", "g2", "_bin", 0.0 AS "_cnt"
  FROM "_bins3") AS "t0"
  GROUP BY "g0", "g1", "g2", "_bin"
), _cdf3 AS (
  SELECT "g0", "g1", "g2", "_bin", SUM("_cnt") OVER (PARTITION BY "g0", "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "_cdist", SUM("_cnt") OVER (PARTITION BY "g0", "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS "_tot"
  FROM "_pdf3"
)
SELECT "t1"."g0", "t1"."g1", "t1"."g2", "t1"."min_v1", "t4"."max_v1", "t7"."min_v2", "t10"."max_v2"
FROM (SELECT "g0", "g1", "g2", CAST(0.0 + MIN("_bin") * 100000.0 AS DOUBLE) AS "min_v1"
FROM "_cdf3"
WHERE "_cdist" > "_tot" * 0.1
GROUP BY "g0", "g1", "g2") AS "t1"
INNER JOIN (SELECT "g0", "g1", "g2", CAST(0.0 + MIN("_bin") * 100000.0 AS DOUBLE) AS "max_v1"
FROM "_cdf3"
WHERE "_cdist" > "_tot" * 0.9
GROUP BY "g0", "g1", "g2") AS "t4" ON "t1"."g0" = "t4"."g0" AND "t1"."g1" = "t4"."g1" AND "t1"."g2" = "t4"."g2"
INNER JOIN (SELECT "g0", "g1", "g2", CAST(0.0 + MIN("_bin") * 150000.0 AS DOUBLE) AS "min_v2"
FROM "_cdf4"
WHERE "_cdist" > "_tot" * 0.1
GROUP BY "g0", "g1", "g2") AS "t7" ON "t1"."g0" = "t7"."g0" AND "t1"."g1" = "t7"."g1" AND "t1"."g2" = "t7"."g2"
INNER JOIN (SELECT "g0", "g1", "g2", CAST(0.0 + MIN("_bin") * 150000.0 AS DOUBLE) AS "max_v2"
FROM "_cdf4"
WHERE "_cdist" > "_tot" * 0.9
GROUP BY "g0", "g1", "g2") AS "t10" ON "t1"."g0" = "t10"."g0" AND "t1"."g1" = "t10"."g1" AND "t1"."g2" = "t10"."g2"
ORDER BY "t1"."g0" IS NULL, "t1"."g0", "t1"."g1" IS NULL, "t1"."g1", "t1"."g2" IS NULL, "t1"."g2";