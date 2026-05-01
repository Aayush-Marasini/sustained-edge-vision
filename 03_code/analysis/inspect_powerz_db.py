"""
inspect_powerz_db.py
====================
Discover the schema of PowerZ KM003C .db SQLite files.
Run once to understand structure before writing the analysis script.

Usage:
    python 03_code/analysis/inspect_powerz_db.py 05_results/power_data/2026-05-01_inferonly_int8_rep1.db
"""
import sqlite3
import sys
from pathlib import Path

if len(sys.argv) != 2:
    print("Usage: inspect_powerz_db.py <path_to.db>")
    sys.exit(1)

db_path = Path(sys.argv[1])
if not db_path.exists():
    print(f"ERROR: {db_path} does not exist")
    sys.exit(1)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# List tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print(f"=== Tables in {db_path.name} ===")
for t in tables:
    print(f"  - {t}")

# Schema for each table
for t in tables:
    print(f"\n=== Schema: {t} ===")
    cursor.execute(f"PRAGMA table_info({t})")
    for col in cursor.fetchall():
        cid, name, ctype, notnull, dflt, pk = col
        print(f"  {name:20s} {ctype:15s} {'NOT NULL' if notnull else '':10s} {'PK' if pk else ''}")

# Row count and sample rows
for t in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {t}")
    count = cursor.fetchone()[0]
    print(f"\n=== {t}: {count} rows ===")
    cursor.execute(f"SELECT * FROM {t} LIMIT 3")
    rows = cursor.fetchall()
    cursor.execute(f"PRAGMA table_info({t})")
    cols = [c[1] for c in cursor.fetchall()]
    print(f"Columns: {cols}")
    for i, row in enumerate(rows):
        print(f"  Row {i}: {row}")

conn.close()