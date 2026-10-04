import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(name: str, default: Path) -> Path:
    v = os.getenv(name)
    p = Path(v) if v else default
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


MEDIA_DIR = _path("MEDIA_DIR", ROOT / "media")
DATA_DIR = _path("DATA_DIR", ROOT / "data")
DB_PATH = DATA_DIR / "dam.db"
THUMB_DIR = DATA_DIR / "thumbs"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
PDF_EXT = {".pdf"}

CLIP_MODEL = os.getenv("CLIP_MODEL", "clip-ViT-B-32")
TEXT_MODEL = os.getenv("TEXT_MODEL", "all-MiniLM-L6-v2")

VIDEO_SECONDS_PER_FRAME = float(os.getenv("VIDEO_SECONDS_PER_FRAME", 4))
VIDEO_MAX_FRAMES = int(os.getenv("VIDEO_MAX_FRAMES", 16))

PDF_MAX_PAGES = int(os.getenv("PDF_MAX_PAGES", 40))
PDF_CHUNK_CHARS = int(os.getenv("PDF_CHUNK_CHARS", 800))
PDF_MAX_CHUNKS = int(os.getenv("PDF_MAX_CHUNKS", 120))

MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", 3))
MIN_SCORE = float(os.getenv("MIN_SCORE", 0.12))
AUTO_INDEX = os.getenv("AUTO_INDEX", "false").lower() == "true"


def type_of(ext: str):
    ext = ext.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in PDF_EXT:
        return "pdf"
    return None
