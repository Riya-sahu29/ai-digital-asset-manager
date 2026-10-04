"""Print / save dataset summary (file counts + sizes per type) -> docs/DATASET_SUMMARY.md"""
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

stats = defaultdict(lambda: [0, 0])
for dp, dn, fn in os.walk(config.MEDIA_DIR):
    for f in fn:
        if f.startswith("."):
            continue
        k = config.type_of(os.path.splitext(f)[1]) or "unsupported"
        stats[k][0] += 1
        stats[k][1] += os.path.getsize(os.path.join(dp, f))

gb = lambda b: f"{b / 1024 ** 3:.2f} GB" if b > 1024 ** 3 else f"{b / 1024 ** 2:.1f} MB"
lines = ["# Dataset summary", "", f"Folder: `{config.MEDIA_DIR}`", "", "| Type | Files | Size |", "|---|---:|---:|"]
for k in ("image", "video", "pdf", "unsupported"):
    if k in stats:
        lines.append(f"| {k} | {stats[k][0]} | {gb(stats[k][1])} |")
lines.append(f"| **total** | **{sum(v[0] for v in stats.values())}** | **{gb(sum(v[1] for v in stats.values()))}** |")
out = "\n".join(lines)
print(out)
(config.ROOT / "docs" / "DATASET_SUMMARY.md").write_text(out + "\n")
