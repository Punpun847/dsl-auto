import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "stubs"))

from app.utils.pending_dump import read_pending

items = read_pending()
print(f"Total pending: {len(items)}")
print()
for i, q in enumerate(items, 1):
    print(f"=== Q{i}  [hash={q['q_hash']}] [exam={q.get('exam_type','')}] [course={q.get('course_id','')}] ===")
    print(q["q_text"])
    for j, opt in enumerate(q.get("options", [])):
        print(f"  [{j}] value={opt.get('value')!r}  text={opt.get('text', '')[:200]}")
    print()
