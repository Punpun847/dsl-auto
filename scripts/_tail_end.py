"""Show last N lines of a log file"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.stdout.reconfigure(encoding="utf-8")

log_file = ROOT / sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 30

with open(log_file, encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

for line in lines[-n:]:
    print(line.rstrip())
