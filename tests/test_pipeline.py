"""End-to-end pipeline test with deterministic fake embeddings (no model download needed).
Verifies: ingestion of image/video/pdf, corrupt + unsupported handling, duplicate detection,
incremental re-run, change detection, deletion cleanup, filters, API endpoints."""
import hashlib
import importlib
import os
import shutil

import numpy as np
import pytest
from PIL import Image


def _fake_vec(seed_bytes: bytes, dim: int):
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(seed_bytes).digest()[:8], "little"))
    v = rng.normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    media, data = tmp_path / "media", tmp_path / "data"
    (media / "a").mkdir(parents=True); (media / "b").mkdir()
    monkeypatch.setenv("MEDIA_DIR", str(media)); monkeypatch.setenv("DATA_DIR", str(data))
    from app import config, db, models, processors, indexer, search
    for m in (config, db, models, processors, indexer, search):
        importlib.reload(m)
    # fake models: image vec depends on pixels, text vec on query words (same words -> same vec)
    def clip_images(imgs):
        return np.vstack([_fake_vec(np.asarray(i.resize((8, 8))).tobytes(), 512) for i in imgs])
    monkeypatch.setattr(models, "clip_images", clip_images)
    monkeypatch.setattr(models, "clip_text", lambda ts: np.vstack([_fake_vec(t.lower().encode(), 512) for t in ts]))
    monkeypatch.setattr(models, "text", lambda ts: np.vstack([_fake_vec(t.lower().encode(), 384) for t in ts]))
    monkeypatch.setattr(models, "warmup", lambda: None)
    db.init()
    return media, db, indexer, search


def make_media(media):
    import cv2
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    Image.new("RGB", (64, 48), (200, 30, 30)).save(media / "a" / "red.jpg")
    Image.new("RGB", (64, 48), (30, 30, 200)).save(media / "a" / "blue.png")
    shutil.copy(media / "a" / "red.jpg", media / "b" / "red_copy.jpg")          # duplicate
    (media / "a" / "broken.jpg").write_bytes(os.urandom(2000))                    # corrupt
    (media / "a" / "notes.txt").write_text("hello")                               # unsupported
    (media / "a" / "empty.mp4").write_bytes(b"")                                  # corrupt video
    (media / "a" / "bad.pdf").write_bytes(b"%PDF-1.4 garbage")                    # corrupt pdf
    vw = cv2.VideoWriter(str(media / "b" / "clip.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for i in range(60):
        vw.write(np.full((48, 64, 3), (i * 4) % 255, dtype=np.uint8))
    vw.release()
    d = fitz.open(); p = d.new_page(); p.insert_text((72, 72), "Residential apartment project brochure. " * 20)
    d.save(media / "b" / "brochure.pdf"); d.close()


def run(indexer):
    indexer.indexer.start(); indexer.indexer.join()
    return indexer.indexer.state


def status_of(db):
    return {r["filename"]: r["status"] for r in db.conn().execute("SELECT filename,status FROM assets")}


def test_full_flow(env):
    media, db, indexer, search = env
    make_media(media)
    st = run(indexer)
    s = status_of(db)
    assert st["error"] is None, st
    assert s["red.jpg"] == "done" and s["blue.png"] == "done"
    assert s["red_copy.jpg"] == "duplicate"
    assert s["broken.jpg"] == "failed" and s["empty.mp4"] == "failed" and s["bad.pdf"] == "failed"
    assert s["notes.txt"] == "unsupported"
    assert s["clip.mp4"] == "done" and s["brochure.pdf"] == "done"

    # incremental: second run processes nothing
    st = run(indexer)
    assert st["queued"] == 0 and st["unchanged"] == 9 and st["done"] == 0

    # search works, ranks, filters, hints
    r = search.search("residential apartment project brochure")
    assert r["results"] and r["results"][0]["filename"] == "brochure.pdf"
    assert r["detected_type"] == "pdf"
    assert all(x["type"] == "video" for x in search.search("anything", type="video")["results"])
    red = search.search("x", ext="jpg", min_mb=0)["results"]
    assert all(x["ext"] == ".jpg" for x in red)

    # change detection: modify a file -> only that one reprocessed
    Image.new("RGB", (64, 48), (10, 200, 10)).save(media / "a" / "blue.png")
    st = run(indexer)
    assert st["queued"] == 1 and st["done"] == 1

    # deleting canonical copy promotes the duplicate
    os.remove(media / "a" / "red.jpg")
    st = run(indexer)
    s = status_of(db)
    assert "red.jpg" not in s and s["red_copy.jpg"] == "done" and st["removed"] == 1
    n = db.conn().execute("SELECT COUNT(*) FROM embeddings WHERE asset_id IN "
                          "(SELECT id FROM assets WHERE filename='red.jpg')").fetchone()[0]
    assert n == 0

    # failed files are not retried automatically, only on request
    assert run(indexer)["queued"] == 0
    indexer.indexer.start(retry_failed=True); indexer.indexer.join()
    assert indexer.indexer.state["queued"] == 3


def test_crash_recovery(env):
    media, db, indexer, search = env
    Image.new("RGB", (32, 32), (1, 2, 3)).save(media / "a" / "x.jpg")
    run(indexer)
    db.conn().execute("UPDATE assets SET status='processing'"); db.conn().commit()
    db.init()  # simulates app restart
    assert status_of(db)["x.jpg"] == "pending"
    run(indexer)
    assert status_of(db)["x.jpg"] == "done"


def test_api(env):
    media, db, indexer, search = env
    make_media(media)
    run(indexer)
    from fastapi.testclient import TestClient
    from app import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        assert c.get("/").status_code == 200
        assert c.get("/api/index/status").json()["counts"]["done"] >= 4
        res = c.get("/api/search", params={"q": "residential apartment project brochure"}).json()
        top = res["results"][0]
        assert c.get(top["thumb_url"]).status_code == 200
        assert c.get(top["file_url"]).status_code == 200
        assert c.get("/api/assets", params={"status": "failed"}).json()
        assert "exts" in c.get("/api/facets").json()
        assert c.get("/api/stats").json()["total_files"] == 9
