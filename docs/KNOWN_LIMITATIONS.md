# Known limitations & next steps

* **Dataset size** — default download recipe is ~1.5-3 GB (limited by time/bandwidth). Scale with the flags in
  `fetch_dataset.py`; the pipeline streams and checkpoints per file, so 5-10 GB only costs time (CPU: roughly 5-10 images/s).
* **No OCR** — scanned PDFs are searchable only via page-1 visual embedding. Next: Tesseract/PaddleOCR for pages without text.
* **No audio** — video speech (testimonials!) is not used. Next: Whisper transcripts embedded like PDF chunks.
* **Frame sampling is uniform** — can miss very short events. Next: scene-change detection (PySceneDetect).
* **CLIP weaknesses** — relations/counting/abstract concepts ("testimonial"), text inside images. Next: re-rank top-k with a
  captioning/VLM model (BLIP-2 / Qwen-VL), add query expansion.
* **Brute-force vector search** — exact but O(N). Next: FAISS/HNSW or pgvector.
* **Score calibration** is empirical (constants in `search.py`), tuned on a small set. Next: learn fusion weights from labelled queries.
* **No per-file timeout** — a pathological file could stall the single worker. Next: process pool with timeout + kill.
* **Single worker** — one file at a time. Next: parallel decode, batched GPU inference.
* **Same-content detection is exact-hash only** — near-duplicates (re-encoded video, resized image) are not merged. Next: perceptual hashes / embedding similarity.
* **"Show in folder"** works only because the app runs on the same machine as the files.
