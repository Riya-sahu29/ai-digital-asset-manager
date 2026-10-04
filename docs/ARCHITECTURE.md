# Architecture & data flow

```
 media folder ──► SCAN (stat only) ──► assets table (pending/unsupported)
                                           │
                    ┌──────────────────────┘      one asset at a time, each its own DB transaction
                    ▼
        PROCESS: blake2b hash ─► duplicate? ──yes──► status=duplicate (no AI work)
                    │no
        ┌───────────┼───────────────────────┐
     image         video                    pdf
  CLIP embed   N frames (1 / 4 s, ≤16)   text per page → 800-char chunks → MiniLM embeddings
  zero-shot    CLIP embed each frame,    + page-1 render → CLIP embedding
  tags         drop near-identical,      keywords + summary from text
               tags = mean over frames
        └───────────┬───────────────────────┘
                    ▼
   SQLite: assets (metadata, status, tags, summary, thumb path) + embeddings (float32 BLOBs)
                    ▼
 QUERY ─► CLIP text encoder ─► cosine vs image / frame / page-1 vectors ┐ per asset keep best row
       └► MiniLM encoder    ─► cosine vs PDF chunk vectors            ┘ (best frame / best chunk)
          → normalise each modality to 0..1 → fuse (max + 0.2·min) → +0.15 if query names the type
          → threshold (MIN_SCORE) → ranked results (+ thumbnail, match location, duplicates)
```

## Key decisions
| Topic | Decision | Why |
|---|---|---|
| Image/video understanding | CLIP ViT-B/32 (open source, local) | One shared text-image space → natural-language search with no captioning step; fast on CPU |
| Video | ~1 frame / 4 s (max 16), near-duplicate frames dropped, score = best frame, player seeks to that timestamp | Bounded cost per video regardless of length; scene changes are captured by even spacing |
| PDFs | text chunks → MiniLM (semantic) **and** page-1 render → CLIP | Text-heavy PDFs match on content; visual brochures match on look |
| Vector store | Embeddings in SQLite, brute-force cosine in NumPy (matrices cached, reloaded when table changes) | Zero infra, exact results; fine to ~1M vectors. Swap for FAISS/pgvector beyond that |
| Incremental indexing | Scan compares size+mtime; unchanged files skipped, changed files re-queued, deleted files removed | Re-runs cost one directory walk |
| Duplicates | Content hash; first copy indexed, later copies marked `duplicate` and listed under the original ("also at") | No double indexing, no double results |
| Reliability | Per-asset transaction (checkpoint), status machine `pending→processing→done/failed/duplicate/unsupported`, `processing` reset on restart, corrupt files = permanent failure (not retried), model/memory errors = retried with backoff, infra errors (model download) abort the run without touching the queue | Crash/Ctrl-C safe, resumable, failures visible in UI with reasons |
| Search while indexing | WAL mode + thread-local connections; vector cache refreshes when embeddings change | UI usable during long runs |
| Filters | type, extension, top-level folder, size range, AI tag — applied *before* ranking | Avoids empty pages when filters exclude top hits |

## Scaling to a larger collection
Same code works (everything is streaming + checkpointed). For 100k+ assets: run indexing in the CLI, batch frames
across files on GPU, parallelise decode with a process pool, move vectors to FAISS (HNSW) or pgvector, add scene-change
based frame sampling and Whisper transcripts for video speech.
