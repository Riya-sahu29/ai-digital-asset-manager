import mimetypes
import os
import subprocess
import sys
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, models, search as search_mod
from .indexer import indexer

STATIC = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app):
    db.init()
    threading.Thread(target=_safe_warmup, daemon=True).start()   # so first search is fast
    if config.AUTO_INDEX:
        indexer.start()
    yield
    indexer.stop()


def _safe_warmup():
    try:
        models.warmup()
    except Exception as e:  # models are re-attempted by indexer / search later
        print("model warmup failed:", e)


app = FastAPI(title="AI Digital Asset Manager", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC, "index.html"))


# ------------------------------------------------------------------ indexing
class StartBody(BaseModel):
    retry_failed: bool = False


@app.post("/api/index/start")
def index_start(body: StartBody = StartBody()):
    return {"started": indexer.start(retry_failed=body.retry_failed)}


@app.post("/api/index/stop")
def index_stop():
    indexer.stop()
    return {"stopping": True}


@app.get("/api/index/status")
def index_status():
    c = db.conn()
    counts = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM assets GROUP BY status")}
    return {"run": indexer.state, "counts": counts, "media_dir": str(config.MEDIA_DIR)}


@app.get("/api/stats")
def stats():
    c = db.conn()
    by_type = [dict(r) for r in c.execute(
        "SELECT type, COUNT(*) files, COALESCE(SUM(size),0) bytes FROM assets WHERE type IS NOT NULL GROUP BY type")]
    by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM assets GROUP BY status")}
    total = c.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM assets").fetchone()
    return {"total_files": total[0], "total_bytes": total[1], "by_type": by_type, "by_status": by_status}


# ------------------------------------------------------------------ search
@app.get("/api/search")
def api_search(q: str = "", type: str = None, ext: str = None, folder: str = None,
               min_mb: float = None, max_mb: float = None, tag: str = None,
               limit: int = Query(24, ge=1, le=100)):
    return search_mod.search(q, type or None, ext or None, folder or None, min_mb, max_mb, tag or None, limit)


@app.get("/api/facets")
def facets():
    c = db.conn()
    exts = [dict(r) for r in c.execute(
        "SELECT ext, COUNT(*) n FROM assets WHERE status='done' GROUP BY ext ORDER BY n DESC")]
    folders, tags = {}, {}
    for r in c.execute("SELECT rel_path, tags, type FROM assets WHERE status='done'"):
        parts = r["rel_path"].replace("\\", "/").split("/")
        if len(parts) > 1:
            folders[parts[0]] = folders.get(parts[0], 0) + 1
        if r["type"] != "pdf":
            for t in (r["tags"] or "").split(", "):
                if t:
                    tags[t] = tags.get(t, 0) + 1
    return {"exts": exts,
            "folders": sorted(folders, key=lambda k: -folders[k]),
            "tags": sorted(tags, key=lambda k: -tags[k])[:40]}


# ------------------------------------------------------------------ assets
@app.get("/api/assets")
def list_assets(status: str = "failed", limit: int = Query(200, le=1000), offset: int = 0):
    rows = db.conn().execute(
        "SELECT id, filename, rel_path, ext, type, size, status, error, attempts FROM assets "
        "WHERE status=? ORDER BY id LIMIT ? OFFSET ?", (status, limit, offset)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/assets/{aid}/retry")
def retry_asset(aid: int):
    c = db.conn()
    c.execute("UPDATE assets SET status='pending', attempts=0, error=NULL WHERE id=? AND status='failed'", (aid,))
    c.commit()
    return {"queued": True, "note": "click 'Index' to process queued files"}


def _asset(aid: int):
    r = db.conn().execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
    if r is None:
        raise HTTPException(404, "asset not found")
    return r


@app.get("/api/thumb/{aid}")
def thumb(aid: int):
    r = _asset(aid)
    p = config.THUMB_DIR / (r["thumb"] or "")
    if not r["thumb"] or not p.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/file/{aid}")
def file(aid: int):
    r = _asset(aid)
    if not os.path.exists(r["path"]):
        raise HTTPException(404, "original file is missing on disk")
    mt = mimetypes.guess_type(r["path"])[0] or "application/octet-stream"
    return FileResponse(r["path"], media_type=mt, filename=None)   # Range requests supported -> video seeking


@app.post("/api/reveal/{aid}")
def reveal(aid: int):
    """Open the OS file manager at the original file (local use only)."""
    r = _asset(aid)
    p = r["path"]
    if not os.path.exists(p):
        raise HTTPException(404, "original file is missing on disk")
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{p}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", p])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(p)])
    return {"opened": p}
