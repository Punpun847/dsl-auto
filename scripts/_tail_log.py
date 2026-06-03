import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.stdout.reconfigure(encoding="utf-8")

log_file = ROOT / sys.argv[1]
after = sys.argv[2] if len(sys.argv) > 2 else ""

with open(log_file, encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

found = not after
out = []
for l in lines:
    if not found and after in l:
        found = True
    if found:
        out.append(l.rstrip())

for l in out[:60]:
    print(l)
