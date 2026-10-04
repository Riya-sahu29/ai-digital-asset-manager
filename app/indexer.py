"""Incremental, resumable indexing pipeline.

Phase 1 SCAN   (fast, stat only): walk MEDIA_DIR, upsert one row per file.
               unchanged (size+mtime) -> untouched | new/changed -> pending | gone -> deleted
Phase 2 PROCESS (slow): for each pending asset: hash -> duplicate check -> AI processing
               -> one transaction writes embeddings + metadata. Every asset is its own checkpoint, so a
               crash / Ctrl-C loses at most the file in flight; re-running resumes automatically.
"""
import hashlib
import os
import threading
import time

import numpy as np

from . import config, db, models, processors


def file_hash(path: str) -> str:
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def release_duplicates(c, asset_id: int):
    """If asset_id is the canonical copy of duplicates and is going away / changing,
    promote the oldest duplicate to canonical so it gets indexed."""
    dups = c.execute("SELECT id FROM assets WHERE duplicate_of=? ORDER BY id", (asset_id,)).fetchall()
    if not dups:
        return
    first = dups[0][0]
    c.execute("UPDATE assets SET status='pending', duplicate_of=NULL WHERE id=?", (first,))
    for d in dups[1:]:
        c.execute("UPDATE assets SET duplicate_of=? WHERE id=?", (first, d[0]))


class Indexer:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self._mu = threading.Lock()
        self.state = self._fresh_state()

    @staticmethod
    def _fresh_state():
        return dict(running=False, phase="idle", scanned=0, new_or_changed=0, unchanged=0, unsupported=0,
                    removed=0, queued=0, processed=0, done=0, failed=0, duplicates=0,
                    current=None, started_at=None, finished_at=None, error=None)

    # ------------------------------------------------------------------ control
    def start(self, retry_failed: bool = False) -> bool:
        with self._mu:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self.state = self._fresh_state()
            self.state.update(running=True, phase="starting", started_at=time.time())
            self._thread = threading.Thread(target=self._run, args=(retry_failed,), daemon=True)
            self._thread.start()
            return True

    def stop(self):
        self._stop.set()

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def join(self):
        if self._thread:
            self._thread.join()

    # ------------------------------------------------------------------ main loop
    def _run(self, retry_failed: bool):
        s = self.state
        try:
            c = db.conn()
            if retry_failed:
                c.execute("UPDATE assets SET status='pending', attempts=0, error=NULL WHERE status='failed'")
                c.commit()
            s["phase"] = "scanning"
            self._scan(c)
            if self._stop.is_set():
                s["phase"] = "stopped"
                return
            s["phase"] = "loading models"
            models.warmup()
            ids = [r[0] for r in c.execute("SELECT id FROM assets WHERE status='pending' ORDER BY id")]
            s["queued"] = len(ids)
            s["phase"] = "processing"
            for aid in ids:
                if self._stop.is_set():
                    s["phase"] = "stopped"
                    return
                self._process_one(c, aid)
            s["phase"] = "finished"
        except Exception as e:  # infra failure (model download, disk...) - queue stays intact for next run
            s["error"] = f"{type(e).__name__}: {e}"
            s["phase"] = "error"
        finally:
            s["running"] = False
            s["current"] = None
            s["finished_at"] = time.time()

    # ------------------------------------------------------------------ phase 1
    def _scan(self, c):
        s = self.state
        root = str(config.MEDIA_DIR)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"MEDIA_DIR does not exist: {root}")
        seen = set()
        n = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))   # deterministic order
            for fn in sorted(filenames):
                if self._stop.is_set():
                    c.commit()
                    return
                if fn.startswith("."):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                seen.add(path)
                s["scanned"] += 1
                ext = os.path.splitext(fn)[1].lower()
                kind = config.type_of(ext)
                status = "pending" if kind else "unsupported"
                row = c.execute("SELECT id,size,mtime FROM assets WHERE path=?", (path,)).fetchone()
                if row is None:
                    c.execute("INSERT INTO assets(path,rel_path,filename,ext,type,size,mtime,status) "
                              "VALUES(?,?,?,?,?,?,?,?)",
                              (path, os.path.relpath(path, root), fn, ext, kind, st.st_size, st.st_mtime, status))
                    s["new_or_changed"] += 1
                elif row["size"] != st.st_size or abs(row["mtime"] - st.st_mtime) > 1e-6:
                    release_duplicates(c, row["id"])
                    c.execute("DELETE FROM embeddings WHERE asset_id=?", (row["id"],))
                    c.execute("UPDATE assets SET size=?, mtime=?, type=?, status=?, content_hash=NULL, error=NULL, "
                              "attempts=0, duplicate_of=NULL WHERE id=?",
                              (st.st_size, st.st_mtime, kind, status, row["id"]))
                    s["new_or_changed"] += 1
                else:
                    s["unchanged"] += 1
                if not kind:
                    s["unsupported"] += 1
                n += 1
                if n % 500 == 0:
                    c.commit()
        # remove assets whose file disappeared
        for r in c.execute("SELECT id,path FROM assets").fetchall():
            if r["path"] not in seen:
                release_duplicates(c, r["id"])
                c.execute("DELETE FROM assets WHERE id=?", (r["id"],))
                s["removed"] += 1
        c.commit()

    # ------------------------------------------------------------------ phase 2
    def _process_one(self, c, aid: int):
        s = self.state
        row = c.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
        if row is None or row["status"] != "pending":
            return
        s["current"] = row["rel_path"]
        c.execute("UPDATE assets SET status='processing', attempts=attempts+1 WHERE id=?", (aid,))
        c.commit()
        err = None
        try:
            if not os.path.exists(row["path"]):
                raise processors.CorruptFile("file disappeared during indexing")
            h = file_hash(row["path"])
            dup = c.execute("SELECT id FROM assets WHERE content_hash=? AND id!=? AND status='done' "
                            "ORDER BY id LIMIT 1", (h, aid)).fetchone()
            if dup:                                    # exact duplicate -> skip all AI work
                c.execute("UPDATE assets SET content_hash=?, status='duplicate', duplicate_of=?, error=NULL, "
                          "indexed_at=? WHERE id=?", (h, dup["id"], time.time(), aid))
                c.commit()
                s["duplicates"] += 1
                return
            res = None
            for attempt in range(config.MAX_ATTEMPTS):
                try:
                    res = processors.process(row["path"], row["type"])
                    break
                except processors.CorruptFile:
                    raise                               # permanent
                except Exception:                       # transient (model / memory) -> retry w/ backoff
                    if attempt == config.MAX_ATTEMPTS - 1:
                        raise
                    time.sleep(1.5 * (attempt + 1))
            thumb_name = f"{aid}.jpg"
            if res.thumb is not None:
                res.thumb.convert("RGB").save(config.THUMB_DIR / thumb_name, quality=82)
            c.execute("DELETE FROM embeddings WHERE asset_id=?", (aid,))
            c.executemany("INSERT INTO embeddings(asset_id,kind,ref,vec) VALUES(?,?,?,?)",
                          [(aid, k, ref, np.asarray(v, dtype=np.float32).tobytes()) for k, ref, v in res.embeds])
            c.execute("UPDATE assets SET status='done', error=NULL, content_hash=?, width=?, height=?, duration=?, "
                      "pages=?, summary=?, tags=?, thumb=?, indexed_at=? WHERE id=?",
                      (h, res.width, res.height, res.duration, res.pages, res.summary, ", ".join(res.tags),
                       thumb_name if res.thumb is not None else None, time.time(), aid))
            c.commit()
            s["done"] += 1
        except Exception as e:
            c.rollback()
            err = f"{type(e).__name__}: {e}"[:500]
            c.execute("UPDATE assets SET status='failed', error=? WHERE id=?", (err, aid))
            c.commit()
            s["failed"] += 1
        finally:
            s["processed"] = s["done"] + s["failed"] + s["duplicates"]


indexer = Indexer()
