"""Run eval/queries.json against the index -> docs/EVALUATION_RESULTS.md + data/eval_report.html
A result counts as relevant if its filename contains the query's `expected` text.
`expect_empty` queries pass if the best score stays below 0.5 (no confident false positive)."""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config, db, search  # noqa: E402

db.init()
queries = json.loads((ROOT / "eval" / "queries.json").read_text())
rows, report = [], []
for q in queries:
    res = search.search(q["query"], limit=10)["results"]
    top = res[0]["score"] if res else 0.0
    exp = q.get("expected", "").lower()
    rank = next((i + 1 for i, r in enumerate(res) if exp and exp in r["filename"].lower()), None)
    if q.get("expect_empty"):
        verdict = "PASS (no confident hit)" if top < 0.5 else "WEAK (confident false positive)"
    else:
        verdict = "good" if rank == 1 else "ok" if rank and rank <= 3 else "poor"
    top3 = "<br>".join(f"{r['score']:.2f} {r['filename'][:38]}" for r in res[:3]) or "(no results)"
    rows.append((q, rank, top, verdict, top3))
    cards = "".join(
        f"<div style='display:inline-block;width:170px;margin:4px;vertical-align:top;font:12px sans-serif;"
        f"border:3px solid {'#3c3' if exp and exp in r['filename'].lower() else '#999'}'>"
        f"<img src='thumbs/{r['id']}.jpg' width=164><br>{html.escape(r['filename'][:24])}<br>{r['type']} {r['score']}</div>"
        for r in res)
    report.append(f"<h3>{q['id']}. {html.escape(q['query'])}</h3>{cards}")

(config.DATA_DIR / "eval_report.html").write_text(
    "<body style='background:#fff'><h2>Search evaluation (green = expected asset)</h2>" + "".join(report))

md = ["# Search evaluation results", "",
      "Dataset: 3 images + 3 videos + 3 PDFs (plus edge-case files). Relevant = expected file appears in results.", "",
      "| # | Query | What the user wants | Expected asset | Rank of expected | Top score | Top 3 returned | Verdict |",
      "|---|---|---|---|---|---|---|---|"]
for q, rank, top, verdict, top3 in rows:
    md.append(f"| {q['id']} | {q['query']} | {q['intent']} | {q.get('expected', 'none')} | {rank or '-'} | {top:.2f} | {top3} | {verdict} |")
good = sum(1 for r in rows if r[3] in ("good",) or r[3].startswith("PASS"))
md += ["", f"**Summary:** {good}/{len(rows)} queries fully correct (rank 1 or correctly empty).", "",
       "## Where search performs poorly", "", "_Write 3-4 observations here (see the failing rows above)._"]
(ROOT / "docs" / "EVALUATION_RESULTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
