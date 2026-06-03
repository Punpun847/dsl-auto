"""Merge ทุกคนใน accounts.csv ที่มี cert พร้อม"""
import csv
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

def main():
    csv_path = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "accounts.csv")
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 1 and row[0].strip():
                rows.append(row[0].strip())

    for nid in rows:
        print(f"\n{'='*60}")
        print(f"  Processing: {nid}")
        print(f"{'='*60}")
        subprocess.run(
            [sys.executable, "scripts/merge_user_certs.py", nid],
            cwd=ROOT,
        )

if __name__ == "__main__":
    main()
