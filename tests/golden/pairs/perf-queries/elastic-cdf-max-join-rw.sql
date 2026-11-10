WITH _domain AS (
  SELECT *
  FROM g1_g2_domain
), _bins2 AS (
  SELECT *
  FROM _domain,
  (VALUES  (0),
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
   (99)) t (_bin)
), _input AS (
  SELECT t.g1, t.g2, t.v1
  FROM (SELECT g1, ja1, v1, g2
  FROM table_b) t
  INNER JOIN (SELECT a_id
  FROM table_a) t0 ON t.ja1 = t0.a_id
), _pdf2 AS (
  SELECT _bins2.g1, _bins2.g2, _bins2._bin, CASE WHEN t0._cnt IS NOT NULL THEN t0._cnt ELSE 0 END + 6005.441140121012 * (CASE WHEN RAND() - 0.5 < 0 THEN -1.0 ELSE 1.0 END * LN(1 - 2 * ABS(RAND() - 0.5))) _cnt
  FROM (SELECT g1, g2, FLOOR((v1 - 0.0) / 100000.0) _bin, COUNT(*) _cnt
  FROM _input
  GROUP BY g1, g2, FLOOR((v1 - 0.0) / 100000.0)) t0
  RIGHT JOIN _bins2 ON t0.g1 = _bins2.g1 AND t0.g2 = _bins2.g2 AND t0._bin = _bins2._bin
), _cdf2 AS (
  SELECT g1, g2, _bin, SUM(_cnt) OVER (PARTITION BY g1, g2 ORDER BY _bin NULLS LAST RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) _cdist, SUM(_cnt) OVER (PARTITION BY g1, g2 ORDER BY _bin NULLS LAST RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) _tot
  FROM _pdf2
)
SELECT g1, g2, CAST(0.0 + MIN(_bin) * 100000.0 AS DOUBLE) max_v1
FROM _cdf2
WHERE _cdist > _tot * 0.9
GROUP BY g1, g2
ORDER BY g1 IS NULL, g1, g2 IS NULL, g2;