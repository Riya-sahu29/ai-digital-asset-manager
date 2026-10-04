# AI-Powered Digital Asset Management (local)

Index a folder of **images, videos and PDFs**, then find assets with **natural-language search** based on their
*actual content* (CLIP + sentence embeddings). Runs fully locally: FastAPI + SQLite + open-source models, no API keys.

## Quick start (≈10 min + model download ~600 MB on first run)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# optional, much smaller CPU-only torch:  pip install torch --index-url https://download.pytorch.org/whl/cpu
cp .env.example .env            # Windows: copy .env.example .env
```

**1. Get data** (or just drop your own files into `./media`):
```bash
# free key: https://www.pexels.com/api/  ->  put it in .env as PEXELS_API_KEY
python scripts/fetch_dataset.py --coco 2000 --pexels-photos 15 --pexels-videos 4 --arxiv 6 --commons-pdfs 6 --edge-cases
python scripts/dataset_summary.py          # writes docs/DATASET_SUMMARY.md
```
Raise the numbers (`--coco 5000 --pexels-videos 20 ...`) to approach 5-10 GB. `--edge-cases` adds corrupted, empty,
truncated, unsupported and duplicate files so you can demo failure handling.

**2. Run the app**
```bash
uvicorn app.main:app --port 8000          # open http://localhost:8000
```
Click **Index / re-scan folder**. Search works while indexing runs (already-indexed files are searchable).
For huge folders you can index from the terminal instead: `python -m app.cli index` (Ctrl-C is safe; re-run resumes).

**3. Evaluate & test**
```bash
python eval/run_eval.py        # 14 queries -> docs/EVALUATION_RESULTS.md + data/eval_report.html
python -m pytest -q tests      # pipeline tests with fake embeddings (no model download)
```

## Config (`.env`)
`MEDIA_DIR`, `DATA_DIR`, `VIDEO_SECONDS_PER_FRAME`, `VIDEO_MAX_FRAMES`, `PDF_MAX_PAGES`, `MIN_SCORE`, `MAX_ATTEMPTS` — see `.env.example`.

## Layout
```
app/main.py        FastAPI endpoints          app/indexer.py    scan + resumable processing queue
app/processors.py  image / video / pdf AI     app/search.py     hybrid semantic ranking + filters
app/models.py      CLIP + MiniLM wrappers     app/db.py         SQLite schema
app/static/        search UI                  scripts/          dataset download + summary
eval/              queries + evaluation run   tests/            pipeline tests
docs/              ARCHITECTURE, EVALUATION, LIMITATIONS
```

## Demo video checklist (2-3 min)
1. Empty DB → click Index → show progress bar, counters, Failed/unsupported tab (corrupt + unsupported + duplicate files).
2. Search: "a woman standing with a cat", "Videos containing construction activity" (player jumps to best moment),
   "Brochures related to residential projects" (PDF preview + matched text), "kitchen interior" + filters (type / extension / size).
3. Click a result → preview → **Show in folder** / **Copy path**.
4. Click Index again → "unchanged" count shows nothing is re-processed. Add/modify one file → only that file is processed.
