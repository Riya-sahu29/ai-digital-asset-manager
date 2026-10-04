"""Hybrid semantic search over the persisted embeddings.

query --CLIP text encoder--> compare to image / video-frame / pdf-page-1 vectors
query --MiniLM-----------------> compare to pdf text-chunk vectors
Per asset we keep the best matching row (best frame for videos, best chunk for PDFs), normalise each
modality's cosine to 0..1 (calibrated constants below), fuse, add a soft boost when the query names a
type ("videos", "brochures"), and rank. Filters are applied BEFORE ranking."""
import re
import threading
import time

import numpy as np

from . import config, db, models

# cosine -> 0..1 calibration (empirical; CLIP text-image cosines are naturally low)
CLIP_LO, CLIP_HI = 0.16, 0.32
TEXT_LO, TEXT_HI = 0.15, 0.60

TYPE_HINTS = {
    "video": "video", "videos": "video", "clip": "video", "clips": "video", "footage": "video",
    "image": "image", "images": "image", "photo": "image", "photos": "image",
    "picture": "image", "pictures": "image",
    "brochure": "pdf", "brochures": "pdf", "pdf": "pdf", "pdfs": "pdf", "document": "pdf",
    "documents": "pdf", "paper": "pdf", "papers": "pdf", "report": "pdf", "reports": "pdf",
}
FILLER = {"containing", "contain", "contains", "showing", "show", "shows", "related", "find", "me", "all",
          "that", "which", "files", "file", "about"} | set(TYPE_HINTS)


def detect_type(q: str):
    for w in re.findall(r"[a-z]+", q.lower()):
        if w in TYPE_HINTS:
            return TYPE_HINTS[w]
    return None


def clean_for_clip(q: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9'-]+", q) if w.lower() not in FILLER]
    return " ".join(words) or q


def _norm(x, lo, hi):
    return float(min(1.0, max(0.0, (x - lo) / (hi - lo))))


class VectorIndex:
    """In-memory matrices rebuilt from SQLite whenever the embeddings table changes."""

    def __init__(self):
        self.sig = None
        self.m = {}
        self._lock = threading.Lock()

    def refresh(self):
        c = db.conn()
        sig = tuple(c.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM embeddings").fetchone())
        if sig == self.sig:
            return
        with self._lock:
            data = {"clip": ([], [], []), "text": ([], [], [])}
            for r in c.execute("SELECT asset_id,kind,ref,vec FROM embeddings"):
                a, rf, v = data[r["kind"]]
                a.append(r["asset_id"])
                rf.append(r["ref"])
                v.append(np.frombuffer(r["vec"], dtype=np.float32))
            self.m = {k: (np.vstack(v) if v else np.zeros((0, 1), np.float32),
                          np.array(a, dtype=np.int64), rf) for k, (a, rf, v) in data.items()}
            self.sig = sig


index = VectorIndex()


def _allowed_ids(type=None, ext=None, folder=None, min_mb=None, max_mb=None, tag=None):
    sql, args = "SELECT id FROM assets WHERE status='done'", []
    if type:
        sql += " AND type=?"; args.append(type)
    if ext:
        sql += " AND ext=?"; args.append(ext.lower() if ext.startswith(".") else "." + ext.lower())
    if folder:
        f = folder.strip("/\\")
        sql += " AND (rel_path LIKE ? OR rel_path LIKE ?)"; args += [f + "/%", f + "\\%"]
    if min_mb is not None:
        sql += " AND size>=?"; args.append(int(min_mb * 1024 * 1024))
    if max_mb is not None:
        sql += " AND size<=?"; args.append(int(max_mb * 1024 * 1024))
    if tag:
        sql += " AND tags LIKE ?"; args.append(f"%{tag}%")
    return {r[0] for r in db.conn().execute(sql, args)}


def _fetch(ids):
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        q = ",".join("?" * len(part))
        for r in db.conn().execute(f"SELECT * FROM assets WHERE id IN ({q})", part):
            out[r["id"]] = r
    return out


def search(q, type=None, ext=None, folder=None, min_mb=None, max_mb=None, tag=None, limit=24):
    t0 = time.time()
    q = (q or "").strip()
    empty = {"query": q, "results": [], "total": 0, "detected_type": None, "took_ms": 0}
    if not q:
        return empty
    index.refresh()
    allowed = _allowed_ids(type, ext, folder, min_mb, max_mb, tag)
    if not allowed:
        return empty
    allowed_arr = np.fromiter(allowed, dtype=np.int64)
    hint = detect_type(q)

    qvecs = {"clip": models.clip_text([clean_for_clip(q)])[0], "text": models.text([q])[0]}
    best = {}  # asset_id -> {"clip": (sim, ref), "text": (sim, ref)}
    for kind, qv in qvecs.items():
        mat, aids, refs = index.m.get(kind, (None, None, None))
        if mat is None or len(aids) == 0 or mat.shape[1] != qv.shape[0]:
            continue
        sims = mat @ qv
        sims[~np.isin(aids, allowed_arr)] = -9.0
        for i in np.argsort(-sims)[:800]:
            if sims[i] < -1.0:
                break
            d = best.setdefault(int(aids[i]), {})
            if kind not in d:
                d[kind] = (float(sims[i]), refs[i])

    cand = []
    for aid, d in best.items():
        a = _norm(d["clip"][0], CLIP_LO, CLIP_HI) if "clip" in d else 0.0
        b = _norm(d["text"][0], TEXT_LO, TEXT_HI) if "text" in d else 0.0
        cand.append((aid, max(a, b) + 0.2 * min(a, b), a, b))
    cand.sort(key=lambda x: -x[1])
    cand = cand[:300]
    rows = _fetch([c[0] for c in cand])

    scored = []
    for aid, s, a, b in cand:
        r = rows.get(aid)
        if r is None:
            continue
        if hint and r["type"] == hint:
            s += 0.15
        if s >= config.MIN_SCORE:
            scored.append((aid, s, a, b))
    scored.sort(key=lambda x: -x[1])
    total = len(scored)
    scored = scored[:limit]

    dups = {}
    for i in range(0, len(scored), 400):
        part = [x[0] for x in scored[i:i + 400]]
        for r in db.conn().execute(
                f"SELECT duplicate_of, path FROM assets WHERE status='duplicate' AND duplicate_of IN "
                f"({','.join('?' * len(part))})", part):
            dups.setdefault(r["duplicate_of"], []).append(r["path"])

    results = []
    for aid, s, a, b in scored:
        r, d = rows[aid], best[aid]
        if b > a and "text" in d:
            page, snippet = d["text"][1].split("|", 1)
            match = {"kind": "text", "page": int(page), "snippet": snippet}
        elif r["type"] == "video" and "clip" in d:
            match = {"kind": "frame", "at": float(d["clip"][1])}
        elif r["type"] == "pdf":
            match = {"kind": "page_visual", "page": 1}
        else:
            match = {"kind": "image"}
        results.append({
            "id": aid, "filename": r["filename"], "type": r["type"], "ext": r["ext"], "size": r["size"],
            "path": r["path"], "rel_path": r["rel_path"], "score": round(min(s, 1.0), 3), "match": match,
            "tags": [t for t in (r["tags"] or "").split(", ") if t], "summary": r["summary"],
            "width": r["width"], "height": r["height"], "duration": r["duration"], "pages": r["pages"],
            "mtime": r["mtime"], "also_at": dups.get(aid, []),
            "thumb_url": f"/api/thumb/{aid}" if r["thumb"] else None, "file_url": f"/api/file/{aid}",
        })
    return {"query": q, "results": results, "total": total, "detected_type": hint,
            "took_ms": int((time.time() - t0) * 1000)}
