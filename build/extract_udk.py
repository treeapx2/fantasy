"""
UDK (Ultimate Draft Kit) extraction — Fantasy Footballers PPR (4pt QB) Redraft Rankings, 8/30/2026.

This is a MECHANICAL extraction of the tabular data only: rank, tier, bio/ADP columns,
projected points, games, and prior-year finish. It does NOT include synthesized risk/upside
notes (that's a separate downstream step — see build/synthesize_notes.py, not yet built) and
does NOT include tag icons (My Guy / Value / Sleeper / Rookie / Breakout / Bust / Injury
Concerns) beyond what's objectively derivable (Rookie = 0 years experience). The icon
glyphs render visually in the PDF but don't survive OCR/text extraction reliably enough to
transcribe 300+ rows by icon without a dedicated visual re-pass — flagged in the README
rather than guessed.

Column order per tuple:
(rank, name, team, tier, age, exp, bye, adp, risk, upside, proj_pts, games, finish_2025)

- `adp` is UDK's own positional ADP string (e.g. "2.10" = round 2, pick 10), not overall ADP.
- Missing values ("-" in source) are None.
- TE games/finish columns were cropped out of the source page layout for every TE row
  (not just a few) — this is a source artifact, not a transcription gap. Stored as None
  for all TEs and flagged in the field mapping / README.
"""

import json
import os

QB = [
    (1, "Josh Allen", "BUF", 1, 30.3, 9, 7, "2.10", 2.6, 9.7, 367.2, 17, 1),
    (2, "Lamar Jackson", "BAL", 2, 29.7, 9, 13, "3.07", 5.5, 9.0, 334.0, 13, 20),
    (3, "Jalen Hurts", "PHI", 3, 28.1, 7, 10, "5.12", 3.8, 5.8, 325.1, 16, 10),
    (4, "Jayden Daniels", "WAS", 3, 25.7, 3, 7, "6.05", 4.7, 6.2, 324.0, 7, 34),
    (5, "Joe Burrow", "CIN", 3, 29.7, 7, 6, "5.04", 5.5, 8.9, 323.3, 8, 28),
    (6, "Drake Maye", "NE", 4, 24.0, 3, 11, "4.12", 4.1, 8.2, 321.0, 17, 3),
    (7, "Jaxson Dart", "NYG", 4, 23.3, 2, 8, "8.08", 5.7, 8.2, 318.1, 14, 16),
    (8, "Caleb Williams", "CHI", 4, 24.8, 3, 10, "6.11", 5.8, 7.8, 315.9, 17, 7),
    (9, "Trevor Lawrence", "JAX", 4, 26.9, 6, 7, "9.06", 4.9, 7.7, 315.1, 17, 4),
    (10, "Dak Prescott", "DAL", 5, 33.1, 11, 14, "7.06", 4.1, 7.7, 310.5, 17, 5),
    (11, "Bo Nix", "DEN", 5, 26.5, 3, 10, "10.12", 4.6, 6.8, 308.1, 17, 6),
    (12, "Justin Herbert", "LAC", 5, 28.5, 7, 7, "7.10", 4.8, 7.8, 307.8, 16, 9),
    (13, "Brock Purdy", "SF", 6, 26.7, 5, 8, "11.03", 4.2, 7.5, 303.4, 9, 24),
    (14, "Jared Goff", "DET", 6, 31.9, 11, 6, "12.03", 2.8, 7.2, 302.2, 17, 8),
    (15, "Matthew Stafford", "LAR", 6, 38.6, 18, 11, "8.12", 4.4, 5.1, 299.5, 17, 2),
    (16, "Tyler Shough", "NO", 6, 26.9, 2, 8, "16.09", 4.3, 7.3, 299.1, 11, 26),
    (17, "Kyler Murray", "MIN", 6, 29.1, 8, 6, "14.02", 7.5, 7.5, 298.9, 5, 39),
    (18, "Baker Mayfield", "TB", 7, 31.4, 9, 10, "12.12", 4.1, 6.8, 296.5, 17, 12),
    (19, "Patrick Mahomes", "KC", 7, 31.0, 10, 5, "10.01", 5.3, 8.2, 295.5, 14, 11),
    (20, "Malik Willis", "MIA", 7, 27.3, 5, 6, "17.03", 5.3, 8.0, 282.0, 4, 45),
    (21, "Jordan Love", "GB", 7, 27.8, 7, 11, "13.06", 3.3, 5.2, 274.6, 15, 15),
    (22, "Cam Ward", "TEN", 8, 24.3, 2, 9, "20.01", 4.6, 6.0, 260.2, 17, 23),
    (23, "C.J. Stroud", "HOU", 8, 24.9, 4, 8, "18.02", 4.2, 6.1, 259.3, 14, 21),
    (24, "Sam Darnold", "SEA", 8, 29.3, 9, 11, "14.04", 4.0, 6.2, 253.8, 17, 13),
    (25, "Daniel Jones", "IND", 8, 29.3, 8, 13, "17.11", 7.5, 6.3, 248.8, 13, 17),
    (26, "Bryce Young", "CAR", 8, 25.1, 4, 5, "19.12", 4.0, 5.4, 235.2, 16, 18),
    (27, "Aaron Rodgers", "PIT", 8, 42.8, 22, 9, "20.01", 7.0, 3.8, 234.1, 16, 19),
    (28, "Geno Smith", "NYJ", 8, 35.9, 14, 13, None, 4.9, 3.9, 225.0, 15, 22),
    (29, "Jacoby Brissett", "ARI", 9, 33.7, 11, 14, "21.03", 4.7, 6.0, 199.7, 14, 14),
    (30, "Tua Tagovailoa", "ATL", 9, 28.5, 7, 11, "20.09", 5.5, 4.3, 165.4, 14, 25),
    (31, "Shedeur Sanders", "CLE", 9, 24.6, 2, 11, "20.08", 8.1, 5.8, 139.0, 8, 37),
    (32, "Fernando Mendoza", "LV", 9, 22.9, 0, 13, "16.03", 8.8, 6.7, 118.5, None, None),
    (33, "Michael Penix Jr.", "ATL", 9, 26.3, 3, 11, "19.12", 5.3, 4.7, 108.0, 9, 33),
    (34, "Kirk Cousins", "LV", 9, 38.1, 15, 13, None, 8.1, 4.8, 100.0, 11, 35),
    (35, "Deshaun Watson", "CLE", 9, 31.0, 10, 11, None, 9.3, 4.3, 90.9, None, None),
    (36, "Carson Beck", "ARI", 9, 24.8, 0, 14, None, 8.5, 5.8, 73.8, None, None),
]

RB = [
    (1, "Jahmyr Gibbs", "DET", 1, 24.5, 4, 6, "1.02", 2.0, 9.8, 378.1, 17, 4),
    (2, "Bijan Robinson", "ATL", 1, 24.6, 4, 11, "1.02", 1.3, 10.0, 365.7, 17, 3),
    (3, "Christian McCaffrey", "SF", 2, 30.3, 10, 8, "1.05", 5.6, 9.3, 344.4, 17, 1),
    (4, "Jonathan Taylor", "IND", 3, 27.6, 7, 13, "1.07", 3.9, 9.0, 293.5, 17, 2),
    (5, "James Cook III", "BUF", 3, 26.9, 5, 7, "1.10", 2.5, 8.4, 292.1, 17, 5),
    (6, "De'Von Achane", "MIA", 4, 24.9, 4, 6, "2.01", 3.8, 9.1, 282.2, 16, 6),
    (7, "Kenneth Walker", "KC", 4, 25.9, 5, 5, "2.07", 5.0, 8.2, 265.1, 17, 22),
    (8, "Chase Brown", "CIN", 4, 26.5, 4, 6, "2.03", 4.8, 8.4, 264.9, 17, 8),
    (9, "Omarion Hampton", "LAC", 5, 23.5, 2, 7, "2.04", 4.7, 8.7, 252.0, 9, 36),
    (10, "Ashton Jeanty", "LV", 5, 22.8, 2, 13, "2.03", 10.0, 8.7, 249.9, 17, 12),
    (11, "Saquon Barkley", "PHI", 5, 29.6, 9, 10, "2.02", 4.9, 8.3, 244.1, 16, 13),
    (12, "Derrick Henry", "BAL", 6, 32.7, 11, 13, "2.08", 5.3, 8.6, 239.7, 17, 7),
    (13, "Jeremiyah Love", "ARI", 6, 21.3, 0, 14, "3.02", 5.3, 8.5, 233.3, None, None),
    (14, "Kyren Williams", "LAR", 6, 26.0, 5, 11, "3.06", 5.5, 8.0, 232.5, 17, 9),
    (15, "Breece Hall", "NYJ", 6, 25.3, 5, 13, "3.10", 5.3, 8.1, 228.8, 16, 18),
    (16, "D'Andre Swift", "CHI", 6, 27.6, 7, 10, "5.04", 5.3, 6.8, 228.4, 16, 14),
    (17, "Javonte Williams", "DAL", 6, 26.4, 6, 14, "3.12", 4.3, 7.7, 222.8, 16, 11),
    (18, "Cam Skattebo", "NYG", 6, 24.6, 2, 8, "4.07", 6.5, 7.2, 218.2, 8, 41),
    (19, "Bucky Irving", "TB", 6, 24.0, 3, 10, "4.06", 5.8, 7.7, 217.7, 10, 33),
    (20, "Travis Etienne Jr.", "NO", 7, 27.6, 6, 8, "4.09", 4.6, 7.6, 214.8, 17, 10),
    (21, "Bhayshul Tuten", "JAX", 7, 24.6, 2, 7, "6.03", 6.4, 7.7, 210.9, 15, 51),
    (22, "Quinshon Judkins", "CLE", 7, 22.9, 2, 11, "5.05", 5.0, 7.6, 200.9, 14, 26),
    (23, "TreVeyon Henderson", "NE", 7, 23.9, 2, 11, "5.08", 5.1, 8.2, 195.7, 17, 19),
    (24, "David Montgomery", "HOU", 7, 29.3, 8, 8, "5.01", 4.1, 6.8, 194.3, 17, 27),
    (25, "Jadarian Price", "SEA", 7, 22.9, 0, 11, "6.08", 5.5, 7.2, 193.2, None, None),
    (26, "Rhamondre Stevenson", "NE", 8, 28.5, 6, 11, "7.10", 4.8, 5.6, 189.0, 14, 25),
    (27, "Rico Dowdle", "PIT", 8, 28.2, 7, 9, "8.01", 4.5, 4.0, 183.2, 17, 16),
    (28, "Josh Jacobs", "GB", 8, 28.6, 8, 11, "3.07", 9.3, 5.8, 180.6, 15, 15),
    (29, "Jacory Croskey-Merritt", "WAS", 8, 25.4, 2, 7, "10.08", 6.3, 5.9, 174.6, 17, 30),
    (30, "Kenny Gainwell", "TB", 8, 27.5, 6, 10, "10.03", 4.4, 5.6, 173.5, 17, 20),
    (31, "Jaylen Warren", "PIT", 8, 27.8, 5, 9, "6.12", 4.4, 6.2, 173.3, 16, 17),
    (32, "Chuba Hubbard", "CAR", 8, 27.2, 6, 5, "7.07", 6.7, 5.2, 164.1, 15, 42),
    (33, "Tony Pollard", "TEN", 8, 29.4, 8, 9, "8.01", 5.6, 5.9, 163.8, 17, 23),
    (34, "J.K. Dobbins", "DEN", 8, 27.7, 7, 10, "8.11", 7.5, 6.2, 163.4, 10, 39),
    (35, "Jonathon Brooks", "CAR", 8, 23.1, 3, 5, "9.10", 7.2, 6.0, 162.8, None, None),
    (36, "Kyle Monangai", "CHI", 8, 24.5, 2, 10, "9.05", 5.8, 5.7, 156.6, 17, 29),
    (37, "Jordan Mason", "MIN", 8, 27.3, 5, 6, "10.06", 4.0, 6.4, 153.2, 16, 34),
    (38, "Rachaad White", "WAS", 8, 27.7, 5, 7, "11.12", 4.6, 5.6, 150.5, 17, 35),
    (39, "Blake Corum", "LAR", 8, 25.8, 3, 11, "9.07", 4.6, 6.8, 146.8, 17, 37),
    (40, "RJ Harvey", "DEN", 9, 25.6, 2, 10, "7.07", 6.2, 5.5, 145.8, 17, 21),
    (41, "MarShawn Lloyd", "GB", 9, 25.7, 3, 11, "15.06", 7.7, 6.0, 138.3, None, None),
    (42, "Aaron Jones Sr.", "MIN", 9, 31.8, 10, 6, "11.05", 4.3, 5.3, 138.1, 12, 43),
    (43, "Tyjae Spears", "TEN", 9, 25.2, 4, 9, "14.06", 4.6, 4.7, 133.9, 13, 48),
    (44, "Woody Marks", "HOU", 9, 25.7, 2, 8, "14.03", 4.3, 5.4, 118.9, 16, 32),
    (45, "Chris Rodriguez Jr.", "JAX", 9, 25.9, 4, 7, "12.10", 5.1, 5.2, 114.9, 13, 45),
    (46, "Isiah Pacheco", "DET", 9, 27.5, 5, 6, "16.07", 5.0, 5.2, 112.2, 13, 55),
    (47, "Keaton Mitchell", "LAC", 10, 24.6, 4, 7, "16.05", 4.7, 4.9, 109.0, 13, 66),
    (48, "Zach Charbonnet", "SEA", 10, 25.7, 4, 11, "13.05", 7.0, 5.2, 107.3, 16, 24),
    (49, "Tyler Allgeier", "ARI", 10, 26.4, 5, 14, "13.01", 4.0, 3.5, 106.4, 17, 40),
    (50, "Dylan Sampson", "CLE", 10, 22.0, 2, 11, "16.11", 3.7, 4.9, 106.3, 15, 56),
    (51, "Jonah Coleman", "DEN", 10, 23.0, 0, 10, "15.03", 5.3, 5.8, 104.1, None, None),
    (52, "Mike Washington Jr.", "LV", 10, 23.3, 0, 13, "13.12", 5.8, 6.2, 103.5, None, None),
    (53, "Tyrone Tracy Jr.", "NYG", 10, 26.8, 3, 8, "14.12", 5.9, 5.0, 102.5, 15, 28),
    (54, "Tank Bigsby", "PHI", 10, 25.0, 4, 10, "15.11", 4.6, 6.0, 99.0, 17, 62),
    (55, "Alvin Kamara", "NO", 10, 31.1, 10, 8, "14.05", 6.5, 4.2, 98.2, 11, 50),
    (56, "Brian Robinson", "ATL", 10, 27.5, 5, 11, "14.10", 3.7, 4.3, 91.4, 17, 61),
    (57, "Jordan James", "SF", 10, 22.4, 2, 8, None, 4.8, 4.2, 84.8, None, None),
    (58, "Kimani Vidal", "LAC", 10, 25.0, 3, 7, "20.10", 4.4, 3.9, 84.3, 13, 38),
    (59, "Justice Hill", "BAL", 10, 28.8, 8, 13, None, 3.7, 4.0, 83.6, 10, 63),
    (60, "Samaje Perine", "CIN", 10, 31.0, 10, 6, None, 4.1, 3.1, 80.0, 15, 57),
    (61, "Emmett Johnson", "KC", 10, 22.9, 0, 5, "18.05", 4.8, 4.5, 79.1, None, None),
    (62, "Nicholas Singleton", "TEN", 10, 22.7, 0, 9, "18.07", 5.4, 5.7, 76.3, None, None),
    (63, "Ty Johnson", "BUF", 10, 29.0, 8, 7, None, 3.5, 3.8, 74.5, 17, 49),
    (64, "LeQuint Allen Jr.", "JAX", 10, 22.1, 2, 7, None, 4.9, 3.2, 73.2, 17, 91),
    (65, "Chris Brooks", "GB", 10, 26.7, 4, 11, None, 4.6, 2.7, 68.5, 17, 82),
    (66, "James Conner", "ARI", 10, 31.3, 10, 14, "20.07", 4.3, 3.3, 67.0, 3, 78),
    (67, "Braelon Allen", "NYJ", 10, 22.6, 3, 13, "18.01", 5.0, 5.1, 63.8, 4, 97),
    (68, "George Holani", "SEA", 10, 26.7, 3, 11, None, 4.5, 2.0, 63.6, 11, 90),
    (69, "Isaiah Davis", "NYJ", 10, 24.5, 3, 13, None, 5.2, 3.3, 62.6, 16, 59),
    (70, "DJ Giddens", "IND", 10, 23.0, 2, 13, None, 5.1, 3.8, 61.9, 10, 108),
    (71, "Kaelon Black", "SF", 10, 24.9, 0, 8, "18.10", 5.7, 4.9, 60.0, None, None),
    (72, "Devin Neal", "NO", 10, 23.1, 2, 8, "18.08", 4.8, 2.7, 59.0, 11, 65),
    (73, "Jerome Ford", "FA", 10, 27.0, 5, None, None, 4.8, 2.3, 58.2, 13, 75),
    (74, "Brashard Smith", "KC", 10, 23.4, 2, 5, "19.10", 4.8, 3.0, 57.3, 17, 67),
    (75, "Ray Davis", "BUF", 10, 26.8, 3, 7, "19.08", 3.8, 4.7, 54.6, 17, 58),
    (76, "Jaydon Blue", "DAL", 10, 22.7, 2, 14, "20.01", 5.0, 4.1, 49.4, 5, 89),
    (77, "Emanuel Wilson", "SEA", 10, 27.3, 4, 11, "21.10", 4.9, 3.2, 48.1, 17, 47),
    (78, "Jaylen Wright", "MIA", 10, 23.4, 3, 6, "21.08", 5.0, 4.8, 46.3, 10, 69),
    (79, "Kaytron Allen", "WAS", 10, 23.7, 0, 7, "20.11", 5.3, 3.5, 45.4, None, None),
    (80, "Emari Demercado", "KC", 10, 27.6, 4, 5, None, 5.3, 2.0, 45.3, 13, 64),
    (81, "Devin Singletary", "NYG", 10, 29.0, 8, 8, None, 4.9, 2.9, 44.9, 17, 44),
    (82, "Sean Tucker", "TB", 10, 24.9, 4, 10, "21.04", 4.8, 3.2, 42.6, 17, 46),
    (83, "Demond Claiborne", "MIN", 10, 22.9, 0, 6, "21.02", 5.3, 4.8, 42.3, None, None),
    (84, "Trevor Etienne", "CAR", 10, 22.2, 2, 5, None, 4.3, 3.8, 40.3, 17, 101),
    (85, "Ollie Gordon II", "MIA", 10, 22.6, 2, 6, None, 5.1, 2.9, 38.8, 17, 68),
    (86, "Will Shipley", "PHI", 10, 24.0, 3, 10, None, 4.6, 2.0, 33.3, 15, 99),
    (87, "AJ Dillon", "CAR", 10, 28.3, 7, 5, None, 3.3, 2.0, 32.9, 7, 114),
    (88, "Adam Randall", "BAL", 10, 22.1, 0, 13, None, 4.7, 3.8, 31.6, None, None),
    (89, "Kaleb Johnson", "PIT", 10, 23.1, 2, 9, "19.02", 5.2, 3.1, 30.6, 10, 111),
    (90, "Tahj Brooks", "CIN", 10, 24.3, 2, 6, None, 4.2, 3.6, 27.1, 16, 120),
    (91, "Audric Estime", "NO", 10, 23.0, 3, 8, "20.09", 1.0, 1.0, 4.7, 7, 72),
]

WR = [
    (1, "Ja'Marr Chase", "CIN", 1, 26.5, 6, 6, "1.04", 3.2, 9.7, 338.8, 16, 4),
    (2, "Puka Nacua", "LAR", 1, 25.3, 4, 11, "1.05", 6.3, 9.6, 328.2, 16, 1),
    (3, "Jaxon Smith-Njigba", "SEA", 2, 24.6, 4, 11, "1.07", 2.0, 9.7, 320.8, 17, 2),
    (4, "Amon-Ra St. Brown", "DET", 2, 26.9, 6, 6, "1.08", 1.0, 9.7, 309.9, 17, 3),
    (5, "CeeDee Lamb", "DAL", 2, 27.4, 7, 14, "1.10", 2.6, 9.3, 288.4, 14, 18),
    (6, "Justin Jefferson", "MIN", 3, 27.2, 7, 6, "1.11", 4.7, 9.5, 259.8, 17, 22),
    (7, "A.J. Brown", "NE", 3, 29.2, 8, 11, "2.06", 5.3, 8.0, 257.8, 15, 10),
    (8, "Chris Olave", "NO", 3, 26.2, 5, 8, "3.06", 6.2, 8.8, 255.8, 16, 6),
    (9, "Nico Collins", "HOU", 3, 27.5, 6, 8, "3.01", 4.6, 8.9, 254.0, 15, 8),
    (10, "Garrett Wilson", "NYJ", 3, 26.1, 5, 13, "4.10", 4.9, 8.1, 253.5, 7, 63),
    (11, "Drake London", "ATL", 3, 25.1, 5, 11, "2.06", 4.0, 9.1, 253.2, 12, 15),
    (12, "George Pickens", "DAL", 3, 25.5, 5, 14, "2.12", 5.0, 8.9, 251.9, 17, 5),
    (13, "Rashee Rice", "KC", 3, 26.4, 4, 5, "3.04", 9.5, 8.3, 251.1, 8, 41),
    (14, "Malik Nabers", "NYG", 4, 23.1, 3, 8, "3.03", 7.8, 9.0, 248.8, 4, 98),
    (15, "Zay Flowers", "BAL", 4, 26.0, 4, 13, "4.05", 4.3, 7.5, 244.0, 17, 7),
    (16, "DeVonta Smith", "PHI", 4, 27.8, 6, 10, "3.12", 3.4, 7.6, 242.7, 17, 21),
    (17, "Jaylen Waddle", "DEN", 5, 27.8, 6, 10, "4.10", 5.0, 7.7, 242.0, 16, 25),
    (18, "Ladd McConkey", "LAC", 5, 24.8, 3, 7, "4.02", 4.7, 6.8, 240.2, 16, 28),
    (19, "Emeka Egbuka", "TB", 5, 23.9, 2, 10, "4.03", 5.5, 8.1, 236.4, 17, 20),
    (20, "Tetairoa McMillan", "CAR", 5, 23.4, 2, 5, "4.02", 4.0, 8.2, 235.4, 17, 17),
    (21, "Tee Higgins", "CIN", 5, 27.6, 7, 6, "3.10", 6.1, 8.3, 234.0, 15, 14),
    (22, "Carnell Tate", "TEN", 5, 21.6, 0, 9, "6.06", 5.9, 6.8, 231.6, None, None),
    (23, "Luther Burden III", "CHI", 6, 22.7, 2, 10, "5.07", 5.5, 7.8, 228.5, 15, 47),
    (24, "Parker Washington", "JAX", 6, 24.5, 4, 7, "7.04", 4.3, 6.2, 224.0, 16, 27),
    (25, "Christian Watson", "GB", 6, 27.3, 5, 11, "6.10", 6.6, 8.1, 223.6, 10, 43),
    (26, "Terry McLaurin", "WAS", 6, 31.0, 8, 7, "5.07", 4.4, 6.8, 221.3, 10, 55),
    (27, "Jameson Williams", "DET", 6, 25.4, 5, 6, "5.10", 5.3, 7.7, 220.6, 17, 9),
    (28, "DJ Moore", "BUF", 6, 29.4, 9, 7, "5.10", 4.2, 7.1, 220.4, 17, 33),
    (29, "Davante Adams", "LAR", 6, 33.7, 13, 11, "5.03", 5.2, 7.8, 217.7, 14, 11),
    (30, "Mike Evans", "SF", 7, 33.0, 13, 8, "6.01", 7.8, 7.5, 216.7, 8, 73),
    (31, "Rome Odunze", "CHI", 7, 24.3, 3, 10, "6.04", 3.5, 7.3, 215.2, 12, 40),
    (32, "Marvin Harrison Jr.", "ARI", 7, 24.1, 3, 14, "7.05", 6.2, 7.3, 211.8, 12, 50),
    (33, "DK Metcalf", "PIT", 7, 28.7, 8, 9, "7.03", 4.4, 7.1, 211.2, 15, 26),
    (34, "Alec Pierce", "IND", 8, 26.3, 5, 13, "9.03", 5.8, 6.9, 209.3, 15, 23),
    (35, "Brian Thomas Jr.", "JAX", 8, 23.9, 3, 7, "7.02", 6.5, 7.5, 208.1, 14, 44),
    (36, "Chris Godwin Jr.", "TB", 8, 30.5, 10, 10, "8.12", 4.5, 6.4, 199.8, 9, 78),
    (37, "Quentin Johnston", "LAC", 8, 25.0, 4, 7, "10.06", 6.3, 6.4, 194.1, 14, 30),
    (38, "Michael Pittman Jr.", "PIT", 8, 28.9, 7, 9, "9.08", 3.5, 4.9, 193.1, 17, 24),
    (39, "Wan'Dale Robinson", "TEN", 8, 25.7, 5, 9, "10.09", 4.6, 4.7, 188.4, 16, 19),
    (40, "Michael Wilson", "ARI", 9, 26.5, 4, 14, "7.12", 3.8, 6.6, 183.5, 17, 12),
    (41, "Stefon Diggs", "WAS", 9, 32.8, 12, 7, "10.02", 5.3, 5.0, 182.1, 17, 16),
    (42, "Courtland Sutton", "DEN", 9, 30.9, 9, 10, "7.07", 5.0, 6.0, 180.6, 17, 13),
    (43, "Jordan Addison", "MIN", 9, 24.6, 4, 6, "9.08", 3.7, 7.2, 179.1, 14, 42),
    (44, "De'Zhaun Stribling", "SF", 9, 23.7, 0, 8, "12.07", 5.3, 5.5, 176.7, None, None),
    (45, "Jayden Reed", "GB", 9, 26.4, 4, 11, "10.03", 4.2, 4.7, 173.4, 7, 117),
    (46, "Josh Downs", "IND", 9, 25.1, 4, 13, "10.03", 4.2, 7.3, 168.6, 16, 49),
    (47, "Jakobi Meyers", "JAX", 9, 29.8, 8, 7, "10.12", 2.7, 5.2, 165.4, 16, 35),
    (48, "Romeo Doubs", "NE", 9, 26.4, 5, 11, "12.01", 3.9, 6.0, 163.7, 16, 36),
    (49, "Khalil Shakir", "BUF", 9, 26.6, 5, 7, "12.12", 2.8, 5.1, 162.4, 16, 38),
    (50, "Makai Lemon", "PHI", 10, 22.3, 0, 10, "8.05", 6.6, 6.9, 161.1, None, None),
    (51, "Xavier Worthy", "KC", 10, 23.4, 3, 5, "12.09", 6.2, 6.0, 160.3, 14, 60),
    (52, "Malik Washington", "MIA", 10, 25.9, 3, 6, "15.07", 4.6, 5.1, 159.3, 17, 57),
    (53, "Jalen Coker", "CAR", 10, 24.9, 3, 5, "13.03", 3.7, 5.8, 157.4, 11, 71),
    (54, "Rashid Shaheed", "SEA", 10, 28.0, 5, 11, "13.03", 4.4, 5.3, 156.6, 18, 39),
    (55, "Kayshon Boutte", "HOU", 10, 24.3, 4, 8, "19.05", 4.4, 5.8, 156.6, 14, 46),
    (56, "KC Concepcion", "CLE", 10, 21.9, 0, 11, "11.01", 5.9, 6.7, 156.5, None, None),
    (57, "Keenan Allen", "IND", 10, 34.4, 14, 13, "17.05", 5.7, 3.5, 153.0, 17, 32),
    (58, "Matthew Golden", "GB", 10, 23.1, 2, 11, "11.08", 5.2, 6.8, 152.4, 14, 90),
    (59, "Jordyn Tyson", "NO", 10, 22.1, 0, 8, "8.09", 7.2, 7.2, 146.0, None, None),
    (60, "Tre Tucker", "LV", 10, 25.5, 4, 13, "17.11", 4.5, 4.6, 145.3, 17, 37),
    (61, "Omar Cooper Jr.", "NYJ", 10, 22.7, 0, 13, "17.03", 6.7, 5.9, 133.8, None, None),
    (62, "Jauan Jennings", "MIN", 10, 29.2, 6, 6, "18.09", 6.4, 5.3, 133.6, 15, 31),
    (63, "Deebo Samuel Sr.", "SF", 10, 30.6, 8, 8, "11.09", 6.3, 3.7, 133.2, 16, 29),
    (64, "Denzel Boston", "CLE", 10, 22.7, 0, 11, "15.01", 4.7, 4.9, 132.8, None, None),
    (65, "Dontayvion Wicks", "PHI", 10, 25.2, 4, 10, None, 5.3, 4.3, 127.9, 14, 83),
    (66, "Jalen Nailor", "LV", 10, 27.5, 5, 13, "16.04", 4.9, 3.9, 123.8, 17, 59),
    (67, "Travis Hunter", "JAX", 11, 23.3, 2, 7, "14.10", 8.3, 6.3, 119.4, 7, 96),
    (68, "Cooper Kupp", "SEA", 11, 33.2, 10, 11, "17.08", 5.3, 3.5, 116.5, 16, 56),
    (69, "Jerry Jeudy", "CLE", 11, 27.4, 7, 11, "16.09", 5.5, 5.5, 116.3, 17, 54),
    (70, "Pat Bryant", "DEN", 11, 23.7, 2, 10, "19.11", 4.0, 4.7, 116.3, 15, 85),
    (71, "DeMario Douglas", "NE", 11, 25.7, 4, 11, None, 4.8, 4.1, 115.4, 17, 62),
    (72, "Ja'Kobi Lane", "BAL", 11, 22.1, 0, 13, "13.12", 5.3, 4.8, 112.2, None, None),
    (73, "Tank Dell", "HOU", 11, 26.9, 4, 8, "16.01", 8.5, 6.3, 112.0, None, None),
    (74, "Adonai Mitchell", "NYJ", 11, 23.9, 3, 13, "20.03", 4.6, 4.5, 112.0, 16, 69),
    (75, "Germie Bernard", "PIT", 11, 22.8, 0, 9, "20.02", 5.4, 4.1, 110.9, None, None),
    (76, "Cyrus Allen", "KC", 11, 23.6, 0, 5, "15.06", 5.3, 4.7, 110.5, None, None),
    (77, "Kyle Williams", "NE", 11, 23.8, 2, 11, "19.06", 5.0, 5.7, 108.9, 17, 107),
    (78, "Calvin Ridley", "TEN", 11, 31.7, 8, 9, "22.01", 5.2, 4.7, 108.5, 7, 110),
    (79, "Tre' Harris", "LAC", 11, 24.5, 2, 7, "20.03", 4.3, 5.1, 106.9, 17, 94),
    (80, "Keon Coleman", "BUF", 11, 23.3, 3, 7, "20.07", 5.4, 5.3, 105.9, 13, 61),
    (81, "Ryan Flournoy", "DAL", 11, 26.9, 3, 14, "20.03", 4.3, 4.8, 103.7, 16, 52),
    (82, "Zachariah Branch", "ATL", 11, 22.4, 0, 11, "18.04", 4.3, 5.2, 103.1, None, None),
    (83, "Caleb Douglas", "MIA", 11, 23.0, 0, 6, "17.06", 5.3, 4.4, 100.0, None, None),
    (84, "Darius Slayton", "NYG", 11, 29.7, 8, 8, None, 4.9, 3.9, 96.1, 14, 65),
    (85, "Devaughn Vele", "NO", 11, 28.7, 3, 8, "20.12", 4.8, 4.3, 91.7, 13, 95),
    (86, "Jaylin Noel", "HOU", 11, 24.0, 2, 8, "18.10", 4.2, 3.5, 91.3, 17, 92),
    (87, "Xavier Hutchinson", "HOU", 11, 26.3, 4, 8, None, 3.5, 2.0, 91.0, 17, 64),
    (88, "Darnell Mooney", "NYG", 11, 28.9, 7, 8, "21.09", 4.8, 3.8, 90.1, 15, 80),
    (89, "Jalen Tolbert", "MIA", 11, 27.5, 5, 6, None, 4.4, 3.1, 89.8, 13, 119),
    (90, "Tory Horton", "SEA", 11, 23.8, 2, 11, "20.01", 5.1, 4.0, 89.7, 8, 86),
    (91, "Rashod Bateman", "BAL", 11, 26.8, 6, 13, "20.05", 5.2, 3.8, 89.5, 13, 102),
    (92, "Isaac TeSlaa", "DET", 11, 24.5, 2, 6, "19.11", 7.8, 6.3, 89.2, 17, 79),
    (93, "Jalen McMillan", "TB", 11, 24.7, 3, 10, "18.08", 3.5, 4.0, 89.2, 4, 132),
    (94, "Antonio Williams", "WAS", 11, 22.1, 0, 7, "20.08", 5.3, 5.2, 88.1, None, None),
    (95, "Jack Bech", "LV", 11, 23.7, 2, 13, "20.10", 4.6, 5.2, 87.1, 16, 123),
    (96, "Troy Franklin", "DEN", 11, 23.6, 3, 10, "21.02", 4.0, 3.7, 86.2, 17, 34),
    (97, "Chris Bell", "MIA", 11, 22.2, 0, 6, "21.01", 6.3, 5.6, 83.8, None, None),
    (98, "Elic Ayomanor", "TEN", 11, 23.3, 2, 9, "21.02", 4.7, 4.1, 81.6, 16, 53),
    (99, "Andrei Iosivas", "CIN", 11, 26.9, 4, 6, None, 3.7, 3.9, 80.6, 17, 72),
    (100, "Tyquan Thornton", "KC", 11, 26.1, 5, 5, None, 5.8, 3.7, 79.5, 14, 76),
    (101, "Tez Johnson", "TB", 11, 24.3, 2, 10, None, 4.6, 3.6, 79.0, 16, 67),
    (102, "Chimere Dike", "TEN", 11, 24.7, 2, 9, "20.01", 5.1, 3.7, 76.2, 17, 51),
    (103, "Malachi Fields", "NYG", 11, 23.0, 0, 8, "19.03", 5.4, 3.7, 76.1, None, None),
    (104, "Ted Hurst III", "TB", 11, 22.2, 0, 10, "20.12", 4.3, 3.3, 71.9, None, None),
    (105, "Jahan Dotson", "ATL", 11, 26.5, 5, 11, None, 3.5, 2.5, 70.6, 17, 112),
    (106, "Christian Kirk", "SF", 11, 29.8, 9, 8, "21.02", 5.8, 3.9, 66.8, 13, 108),
    (107, "Kendrick Bourne", "ARI", 11, 31.1, 10, 14, None, 3.7, 2.7, 64.8, 16, 66),
    (108, "Malik Benson", "LV", 11, 23.9, 0, 13, None, 5.5, 3.5, 62.9, None, None),
    (109, "Bryce Lance", "NO", 11, 24.0, 0, 8, None, 8.0, 6.0, 62.8, None, None),
    (110, "Kalif Raymond", "CHI", 11, 32.1, 10, 10, None, 4.7, 3.3, 60.8, 15, 93),
    (111, "Roman Wilson", "PIT", 11, 25.2, 3, 9, None, 5.1, 2.7, 60.7, 13, 122),
    (112, "Olamide Zaccheaus", "ATL", 11, 29.1, 8, 11, None, 2.5, 2.5, 59.6, 16, 81),
    (113, "Marvin Mims Jr.", "DEN", 11, 24.5, 4, 10, "19.04", 4.7, 2.3, 58.9, 15, 70),
    (114, "Jordan Whittington", "LAR", 11, 25.9, 3, 11, None, 4.7, 3.3, 57.9, 17, 131),
    (115, "Mack Hollins", "NE", 11, 33.0, 10, 11, None, 5.3, 3.4, 57.2, 15, 58),
    (116, "Treylon Burks", "WAS", 11, 26.5, 5, 7, None, 5.7, 3.6, 57.2, 8, 139),
    (117, "Dont'e Thornton Jr.", "LV", 11, 23.8, 2, 13, None, 5.6, 3.5, 53.1, 15, 148),
    (118, "Brenen Thompson", "LAC", 11, 23.1, 0, 7, None, 5.6, 3.8, 52.1, None, None),
    (119, "Xavier Legette", "CAR", 11, 25.6, 3, 5, None, 4.7, 4.2, 51.0, 15, 74),
    (120, "Elijah Sarratt", "BAL", 11, 23.3, 0, 13, "20.01", 4.5, 4.3, 49.1, None, None),
    (121, "Skyler Bell", "BUF", 11, 24.2, 0, 7, None, 3.5, 3.0, 48.1, None, None),
    (122, "Van Jefferson", "WAS", 11, 30.1, 7, 7, "50.04", 4.0, 2.0, 47.1, 16, 89),
    (123, "Tutu Atwell", "LAR", 11, 26.9, 6, 11, None, 5.0, 2.9, 46.1, 10, 128),
    (124, "Calvin Austin III", "NYG", 11, 27.5, 5, 8, None, 5.0, 2.9, 45.8, 14, 77),
    (125, "Devontez Walker", "BAL", 11, 25.2, 3, 13, None, 4.3, 3.0, 45.4, 12, 120),
    (126, "Jaylin Lane", "WAS", 11, 24.3, 2, 7, None, 4.0, 3.0, 44.6, 15, 113),
    (127, "Hollywood Brown", "PHI", 11, 29.3, 8, 10, None, 5.1, 3.7, 41.4, 16, 45),
    (128, "Cedric Tillman", "FA", 11, 26.4, 4, None, "56.07", 4.5, 3.6, 40.1, 13, 99),
    (129, "Chris Brazzell II", "CAR", 11, 22.9, 0, 5, "34.04", 7.0, 2.8, 36.8, None, None),
    (130, "Zavion Thomas", "CHI", 11, 22.6, 0, 10, None, 6.3, 4.3, 33.5, None, None),
    (131, "Kendrick Law", "DET", 11, 22.2, 0, 6, None, 7.5, 2.2, 17.5, None, None),
]

# TE: the source PDF's "GMS" and "'25" (prior-year finish) columns were cropped off the
# page layout for every single TE row (not a sampling issue — verified across all 54).
# games/finish_2025 are therefore None for all TEs below. Re-extract from a wider TE-column
# crop of the source PDF if those values are needed.
TE = [
    (1, "Brock Bowers", "LV", 1, 23.7, 3, 13, "2.11", 2.5, 9.8, 259.6, None, None),
    (2, "Trey McBride", "ARI", 1, 26.8, 5, 14, "2.11", 4.2, 8.3, 259.1, None, None),
    (3, "Tyler Warren", "IND", 2, 24.3, 2, 13, "4.12", 3.4, 8.8, 216.9, None, None),
    (4, "Colston Loveland", "CHI", 2, 22.4, 2, 10, "4.03", 4.2, 9.2, 215.7, None, None),
    (5, "Harold Fannin Jr.", "CLE", 3, 22.1, 2, 11, "6.09", 4.1, 8.6, 201.2, None, None),
    (6, "Tucker Kraft", "GB", 3, 25.8, 4, 11, "6.03", 5.5, 8.2, 190.0, None, None),
    (7, "George Kittle", "SF", 3, 32.9, 10, 8, "8.03", 8.0, 8.4, 188.3, None, None),
    (8, "Sam LaPorta", "DET", 4, 25.6, 4, 6, "5.12", 4.4, 6.2, 184.9, None, None),
    (9, "Kyle Pitts Sr.", "ATL", 4, 25.9, 6, 11, "6.08", 5.8, 6.3, 176.7, None, None),
    (10, "Juwan Johnson", "NO", 4, 30.0, 7, 8, "16.08", 3.8, 5.2, 167.6, None, None),
    (11, "Dalton Schultz", "HOU", 4, 30.2, 9, 8, "16.12", 3.1, 4.8, 166.0, None, None),
    (12, "Travis Kelce", "KC", 4, 36.9, 14, 5, "8.07", 4.8, 5.5, 165.2, None, None),
    (13, "Jake Ferguson", "DAL", 4, 27.6, 5, 14, "9.02", 5.3, 6.4, 161.5, None, None),
    (14, "Isaiah Likely", "NYG", 4, 26.4, 5, 8, "9.11", 3.8, 5.8, 157.6, None, None),
    (15, "Dalton Kincaid", "BUF", 4, 26.9, 4, 7, "8.03", 5.8, 7.7, 157.5, None, None),
    (16, "Dallas Goedert", "PHI", 4, 31.7, 9, 10, "11.02", 5.1, 6.3, 156.8, None, None),
    (17, "Brenton Strange", "JAX", 5, 25.7, 4, 7, "13.09", 3.6, 5.5, 155.6, None, None),
    (18, "Mark Andrews", "BAL", 5, 31.0, 9, 13, "11.08", 4.0, 5.5, 148.9, None, None),
    (19, "Hunter Henry", "NE", 5, 31.8, 11, 11, "12.11", 3.4, 5.9, 146.6, None, None),
    (20, "Chig Okonkwo", "WAS", 6, 27.0, 5, 7, "16.12", 3.8, 5.2, 143.3, None, None),
    (21, "Greg Dulcich", "MIA", 6, 26.4, 5, 6, "20.02", 4.8, 5.8, 130.4, None, None),
    (22, "T.J. Hockenson", "MIN", 6, 29.2, 8, 6, "14.08", 4.1, 5.2, 128.2, None, None),
    (23, "Kenyon Sadiq", "NYJ", 6, 21.5, 0, 13, "14.08", 4.6, 5.4, 126.4, None, None),
    (24, "Pat Freiermuth", "PIT", 6, 27.9, 6, 9, "20.12", 4.2, 3.8, 126.2, None, None),
    (25, "Cade Otton", "TB", 7, 27.4, 5, 10, "20.05", 3.8, 3.8, 123.1, None, None),
    (26, "AJ Barner", "SEA", 7, 24.3, 3, 11, "16.04", 3.9, 4.2, 113.0, None, None),
    (27, "Oronde Gadsden", "LAC", 7, 23.2, 2, 7, "11.12", 4.5, 6.8, 108.1, None, None),
    (28, "Colby Parkinson", "LAR", 7, 27.7, 7, 11, "21.11", 4.1, 4.8, 107.9, None, None),
    (29, "David Njoku", "LAC", 7, 30.2, 12, 7, "18.03", 5.3, 3.9, 105.3, None, None),
    (30, "Darren Waller", "CAR", 7, 34.0, 10, 5, None, 5.0, 3.8, 104.0, None, None),
    (31, "Mike Gesicki", "CIN", 7, 30.9, 9, 6, None, 3.6, 5.6, 102.6, None, None),
    (32, "Cole Kmet", "CHI", 7, 27.5, 7, 10, None, 3.5, 3.7, 99.5, None, None),
    (33, "Gunnar Helm", "TEN", 7, 24.0, 2, 9, "20.05", 4.2, 4.3, 96.9, None, None),
    (34, "Evan Engram", "DEN", 7, 32.0, 10, 10, None, 4.7, 2.8, 94.2, None, None),
    (35, "Terrance Ferguson", "LAR", 7, 23.5, 2, 11, "18.02", 5.1, 4.4, 85.9, None, None),
    (36, "Mason Taylor", "NYJ", 8, 22.3, 2, 13, "19.08", 4.1, 3.6, 84.2, None, None),
    (37, "Charlie Kolar", "LAC", 8, 27.6, 5, 7, None, 4.3, 2.7, 81.3, None, None),
    (38, "Michael Mayer", "LV", 8, 25.2, 4, 13, None, 4.8, 2.5, 80.6, None, None),
    (39, "Dawson Knox", "BUF", 8, 29.8, 8, 7, None, 2.5, 2.8, 79.3, None, None),
    (40, "Eli Stowers", "PHI", 8, 23.4, 0, 10, "20.11", 6.3, 5.3, 77.2, None, None),
    (41, "Luke Musgrave", "GB", 8, 26.0, 4, 11, None, 4.7, 3.8, 74.7, None, None),
    (42, "Ja'Tavion Sanders", "CAR", 8, 23.4, 3, 5, None, 4.0, 3.9, 72.8, None, None),
    (43, "Theo Johnson", "NYG", 8, 25.5, 3, 8, "20.04", 4.2, 4.8, 72.0, None, None),
    (44, "Noah Gray", "KC", 8, 27.4, 6, 5, None, 4.3, 2.3, 63.3, None, None),
    (45, "Tommy Tremble", "CAR", 8, 26.3, 6, 5, None, 3.0, 3.0, 60.0, None, None),
    (46, "Elijah Arroyo", "SEA", 8, 23.4, 2, 11, None, 4.5, 4.4, 57.4, None, None),
    (47, "Darnell Washington", "PIT", 8, 25.1, 4, 9, None, 4.6, 3.1, 57.2, None, None),
    (48, "Max Klare", "LAR", 8, 23.2, 0, 11, "21.09", 5.4, 4.6, 55.8, None, None),
    (49, "Jake Tonges", "SF", 8, 27.2, 4, 8, "21.01", 4.0, 2.5, 54.9, None, None),
    (50, "Ben Sinnott", "WAS", 8, 24.2, 3, 7, None, 8.0, 5.9, 49.1, None, None),
    (51, "Noah Fant", "NO", 8, 28.8, 8, 8, None, 4.8, 3.3, 43.1, None, None),
    (52, "Justin Joly", "DEN", 8, 22.2, 0, 10, None, 3.0, 2.0, 31.8, None, None),
    (53, "Nate Boerkircher", "JAX", 8, 25.0, 0, 7, None, 1.0, 1.0, 24.1, None, None),
    (54, "Oscar Delp", "NO", 8, 23.1, 0, 8, None, 6.9, 3.8, 13.2, None, None),
]

COLUMNS = [
    "rank", "name", "team", "tier", "age", "exp", "bye", "adp_positional",
    "risk", "upside", "proj_pts", "games", "finish_2025",
]


def rows_to_records(rows, position):
    records = []
    for row in rows:
        rec = dict(zip(COLUMNS, row))
        rec["position"] = position
        # Objectively derivable tag — see module docstring for why other tags
        # (My Guy / Value / Sleeper / Breakout / Bust / Injury Concerns) are NOT
        # auto-assigned here.
        rec["tags"] = ["Rookie"] if rec["exp"] == 0 else []
        records.append(rec)
    return records


def build():
    all_records = (
        rows_to_records(QB, "QB")
        + rows_to_records(RB, "RB")
        + rows_to_records(WR, "WR")
        + rows_to_records(TE, "TE")
    )

    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "sources", "udk")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "players_raw.json")
    with open(out_path, "w") as f:
        json.dump(
            {
                "source": "udk",
                "source_label": "Fantasy Footballers Ultimate Draft Kit — PPR (4pt QB) Redraft Rankings",
                "source_date": "2026-08-30",
                "extracted": "mechanical (rank/tier/bio/ADP/projection columns only — no synthesized notes)",
                "known_gaps": [
                    "Tag icons (My Guy/Value/Sleeper/Breakout/Bust/Injury Concerns) not extracted "
                    "except Rookie (derived from exp==0) — OCR/text layer doesn't reliably capture "
                    "the small glyph icons; needs a dedicated visual re-pass per player if wanted.",
                    "TE games and finish_2025 columns are None for all 54 TEs — cropped out of the "
                    "source page layout, not a transcription gap.",
                    "Rashid Shaheed (WR #54) shows games=18 in the source, which is impossible for "
                    "an NFL season (max 17) — kept as-is from the source with this flag rather than "
                    "silently corrected; likely a source typo.",
                ],
                "players": all_records,
            },
            f,
            indent=2,
        )
    print(f"Wrote {len(all_records)} players to {out_path}")
    print(f"  QB: {len(QB)}, RB: {len(RB)}, WR: {len(WR)}, TE: {len(TE)}")


if __name__ == "__main__":
    print(f"QB rows: {len(QB)}")
    print(f"RB rows: {len(RB)}")
    print(f"WR rows: {len(WR)}")
    print(f"TE rows: {len(TE)}")
    build()
