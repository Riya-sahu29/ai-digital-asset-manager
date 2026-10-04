"""Download a public, free-to-use mixed media dataset into ./media (resumable, skips existing files).

Sources (all free to use):
  --coco N            COCO val2017 images (CC BY 2.0 Flickr), N images (max 5000, ~800MB zip) + captions for eval
  --pexels-photos N   N photos per query from Pexels  (needs PEXELS_API_KEY, free)
  --pexels-videos N   N videos per query from Pexels  (needs PEXELS_API_KEY, free)
  --arxiv N           N open-access PDFs per query from arXiv
  --commons-pdfs N    N brochure-like PDFs per query from Wikimedia Commons
  --edge-cases        corrupted / unsupported / duplicate files to demo failure handling
Example (small, ~1.5GB):  python scripts/fetch_dataset.py --coco 2000 --pexels-photos 15 --pexels-videos 4 --arxiv 6 --commons-pdfs 6 --edge-cases
Scale up by raising the numbers (e.g. --pexels-videos 20 --coco 5000) to reach 5-10GB."""
import argparse
import json
import os
import re
import shutil
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

MEDIA = config.MEDIA_DIR
DL = config.DATA_DIR / "downloads"
UA = {"User-Agent": "dam-assignment/1.0 (educational project; contact: local)"}

PHOTO_QUERIES = ["construction site", "modern living room", "residential building", "apartment interior",
                 "woman with cat", "house exterior architecture", "office meeting", "kitchen interior",
                 "bedroom interior", "city skyline", "dog running park", "people walking street"]
VIDEO_QUERIES = ["construction site", "building construction crane", "excavator", "modern living room",
                 "house tour interior", "person talking to camera", "interview", "city traffic",
                 "nature landscape", "cooking", "office meeting", "real estate drone"]
ARXIV_QUERIES = ["residential construction", "urban planning housing", "building information modeling",
                 "machine learning", "computer vision", "architecture design"]
COMMONS_QUERIES = ["real estate brochure", "residential project brochure", "apartment brochure",
                   "housing brochure", "construction company brochure", "product brochure"]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def download(url, dest: Path, headers=None, retries=3):
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=60, headers={**UA, **(headers or {})}) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            part.rename(dest)
            return True
        except Exception as e:
            print(f"  retry {attempt + 1}/{retries} {dest.name}: {e}")
            time.sleep(2 * (attempt + 1))
    if part.exists():
        part.unlink()
    return False


# ------------------------------------------------------------------ COCO
def get_coco(n):
    out = MEDIA / "images" / "coco_val2017"
    out.mkdir(parents=True, exist_ok=True)
    z = DL / "val2017.zip"
    print("COCO val2017 images ...")
    if not download("http://images.cocodataset.org/zips/val2017.zip", z):
        return print("  failed")
    with zipfile.ZipFile(z) as zf:
        names = [m for m in zf.namelist() if m.lower().endswith(".jpg")][:n]
        for m in names:
            target = out / os.path.basename(m)
            if not target.exists():
                with zf.open(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    print(f"  extracted {len(names)} images")
    cap = config.DATA_DIR / "coco_captions_val2017.json"
    if not cap.exists():
        print("COCO captions (ground truth for evaluation only) ...")
        az = DL / "annotations_trainval2017.zip"
        if download("http://images.cocodataset.org/annotations/annotations_trainval2017.zip", az):
            with zipfile.ZipFile(az) as zf, zf.open("annotations/captions_val2017.json") as src, open(cap, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ------------------------------------------------------------------ Pexels
def pexels(kind, per_query):
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return print(f"PEXELS_API_KEY not set -> skipping pexels {kind}")
    H = {"Authorization": key}
    queries = PHOTO_QUERIES if kind == "photos" else VIDEO_QUERIES
    for q in queries:
        print(f"Pexels {kind}: {q}")
        url = ("https://api.pexels.com/v1/search" if kind == "photos" else "https://api.pexels.com/videos/search")
        try:
            r = requests.get(url, params={"query": q, "per_page": min(per_query, 80)}, headers=H, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print("  api error:", e)
            continue
        if kind == "photos":
            for p in data.get("photos", [])[:per_query]:
                download(p["src"]["large2x"], MEDIA / "images" / f"pexels-{slug(q)}" / f"pexels_{p['id']}.jpg")
        else:
            for v in data.get("videos", [])[:per_query]:
                files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
                files = [f for f in files if f["width"] <= 1920] or files
                if not files:
                    continue
                f = max(files, key=lambda x: x["width"])
                download(f["link"], MEDIA / "videos" / f"pexels-{slug(q)}" / f"pexels_{v['id']}.mp4")


# ------------------------------------------------------------------ PDFs
def arxiv(per_query):
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for q in ARXIV_QUERIES:
        print(f"arXiv: {q}")
        try:
            r = requests.get("http://export.arxiv.org/api/query", headers=UA, timeout=30,
                             params={"search_query": f'all:"{q}"', "max_results": per_query})
            root = ET.fromstring(r.text)
        except Exception as e:
            print("  api error:", e)
            continue
        for e in root.findall("a:entry", ns):
            raw = e.find("a:id", ns).text.rsplit("/abs/", 1)[-1]
            download(f"https://arxiv.org/pdf/{raw}", MEDIA / "pdfs" / f"arxiv-{slug(q)}" / f"arxiv_{raw.replace('/', '_')}.pdf")
        time.sleep(3)  # arXiv API etiquette


def commons(per_query):
    for q in COMMONS_QUERIES:
        print(f"Wikimedia Commons PDFs: {q}")
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
                "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"filetype:pdf {q}", "gsrlimit": per_query, "prop": "imageinfo",
                "iiprop": "url|mime|size"})
            pages = r.json().get("query", {}).get("pages", {})
        except Exception as e:
            print("  api error:", e)
            continue
        for p in pages.values():
            info = (p.get("imageinfo") or [{}])[0]
            if info.get("mime") == "application/pdf" and info.get("size", 0) < 60 * 1024 * 1024:
                download(info["url"], MEDIA / "pdfs" / f"commons-{slug(q)}" / (slug(p["title"][5:-4]) + ".pdf"))


# ------------------------------------------------------------------ edge cases
def edge_cases():
    d = MEDIA / "edge_cases"
    d.mkdir(parents=True, exist_ok=True)
    (d / "corrupted.jpg").write_bytes(os.urandom(4096))
    (d / "empty.mp4").write_bytes(b"")
    (d / "truncated.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog")
    (d / "notes.txt").write_text("unsupported file type example")
    (d / "archive.zip").write_bytes(b"PK\x03\x04 not really a zip")
    imgs = sorted((MEDIA / "images").rglob("*.jpg"))
    if imgs:
        shutil.copy(imgs[0], d / f"duplicate_of_{imgs[0].name}")      # exact duplicate in another folder
    vids = sorted((MEDIA / "videos").rglob("*.mp4"))
    if vids:
        with open(vids[0], "rb") as src, open(d / "truncated_video.mp4", "wb") as dst:
            dst.write(src.read(150_000))                                # cut-off video
    print("edge cases written to", d)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coco", type=int, default=0)
    ap.add_argument("--pexels-photos", type=int, default=0)
    ap.add_argument("--pexels-videos", type=int, default=0)
    ap.add_argument("--arxiv", type=int, default=0)
    ap.add_argument("--commons-pdfs", type=int, default=0)
    ap.add_argument("--edge-cases", action="store_true")
    a = ap.parse_args()
    MEDIA.mkdir(parents=True, exist_ok=True)
    if a.coco: get_coco(a.coco)
    if a.pexels_photos: pexels("photos", a.pexels_photos)
    if a.pexels_videos: pexels("videos", a.pexels_videos)
    if a.arxiv: arxiv(a.arxiv)
    if a.commons_pdfs: commons(a.commons_pdfs)
    if a.edge_cases: edge_cases()
    print("done ->", MEDIA)
