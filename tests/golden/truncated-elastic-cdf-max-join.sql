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
  SELECT "t1"."g1", "t1"."g2", "t1"."v1"
  FROM (SELECT "g1", "g2", "ja1", "v1"
  FROM (SELECT "b_id", "g0", "g1", "g2", "ja1", "ja2", "v1", "v2", ROW_NUMBER() OVER (PARTITION BY "ja1") AS "_row_number_ja1", ROW_NUMBER() OVER (PARTITION BY "ja2") AS "_row_number_ja2"
  FROM "table_b") AS "t"
  WHERE "_row_number_ja1" <= 25 AND "_row_number_ja2" <= 100) AS "t1"
  INNER JOIN (SELECT "a_id"
  FROM "table_a") AS "t2" ON "t1"."ja1" = "t2"."a_id"
), _pdf2 AS (
  SELECT "_bins2"."g1", "_bins2"."g2", "_bins2"."_bin", CASE WHEN "t1"."_cnt_incomplete" IS NOT NULL THEN "t1"."_cnt_incomplete" ELSE 0 END + 500.0 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) AS "_cnt"
  FROM (SELECT "g1" AS "g1_incomplete", "g2" AS "g2_incomplete", FLOOR(("v1" - 0.0) / 100000.0) AS "_bin_incomplete", COUNT(*) AS "_cnt_incomplete"
  FROM "_input"
  GROUP BY "g1", "g2", FLOOR(("v1" - 0.0) / 100000.0)) AS "t1"
  RIGHT JOIN "_bins2" ON "t1"."g1_incomplete" = "_bins2"."g1" AND "t1"."g2_incomplete" = "_bins2"."g2" AND "t1"."_bin_incomplete" = "_bins2"."_bin"
), _cdf2 AS (
  SELECT "g1", "g2", "_bin", SUM("_cnt") OVER (PARTITION BY "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "_cdist", SUM("_cnt") OVER (PARTITION BY "g1", "g2" ORDER BY "_bin" IS NULL, "_bin" RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS "_tot"
  FROM "_pdf2"
)
SELECT "g1", "g2", CAST(0.0 + MIN("_bin") * 100000.0 AS DOUBLE) AS "max_v1"
FROM "_cdf2"
WHERE "_cdist" > "_tot" * 0.9
GROUP BY "g1", "g2"
ORDER BY "g1" IS NULL, "g1", "g2" IS NULL, "g2";