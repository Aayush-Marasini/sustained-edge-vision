"""
powerz_profile.py
=================
Inspect PowerZ .db power profile to find idle vs inference windows.
Saves a text profile showing power every 10s.

Usage:
    python 03_code/analysis/powerz_profile.py <db_file>
"""
import sqlite3
import sys
import statistics
from pathlib import Path

db_path = Path(sys.argv[1])
conn = sqlite3.connect(str(db_path))
c = conn.cursor()

c.execute("SELECT COUNT(*), MIN(Unix), MAX(Unix) FROM table_1")
count, t_start, t_end = c.fetchone()
print(f"File: {db_path.name}")
print(f"Total samples: {count:,}  Duration: {t_end - t_start:.1f}s")
print(f"Start Unix: {t_start}  End Unix: {t_end}")

c.execute("SELECT * FROM table_1_param")
print(f"Params: {c.fetchall()}")

print(f"\n{'Time(s)':>8} {'Avg W':>8} {'Min W':>8} {'Max W':>8}")
print("-"*38)

c.execute("SELECT Unix, VBUS*IBUS FROM table_1 ORDER BY Unix")
rows = c.fetchall()

bucket = 10000  # 10s at 1kSPS
for i in range(0, len(rows), bucket):
    chunk = rows[i:i+bucket]
    t_off = chunk[0][0] - t_start
    powers = [r[1] for r in chunk]
    print(f"{t_off:>8.0f} {statistics.mean(powers):>8.3f} "
          f"{min(powers):>8.3f} {max(powers):>8.3f}")

conn.close()