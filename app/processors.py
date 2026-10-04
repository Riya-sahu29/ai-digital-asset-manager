"""Per-type content understanding. Each processor returns a Result:
   metadata + AI tags + summary + embeddings (+ a thumbnail image)."""
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

from . import config, models

Image.MAX_IMAGE_PIXELS = 200_000_000  # decompression-bomb guard


class CorruptFile(ValueError):
    """File is unreadable / unsupported content. Permanent failure -> never retried automatically."""


@dataclass
class Result:
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    pages: Optional[int] = None
    summary: str = ""
    tags: list = field(default_factory=list)
    thumb: Optional[Image.Image] = None
    embeds: list = field(default_factory=list)  # (kind, ref, np.ndarray)


# --------------------------------------------------------------------------- images
def process_image(path: str) -> Result:
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.load()                      # forces full decode -> catches truncated files
            img = im.convert("RGB")
    except Exception as e:
        raise CorruptFile(f"cannot decode image: {e}") from e
    w, h = img.size
    small = img.copy()
    small.thumbnail((512, 512))
    vec = models.clip_images([small])[0]
    tags = models.top_tags(models.tag_probs(vec[None])[0])
    return Result(width=w, height=h, tags=tags, thumb=small,
                  summary=("Image: " + ", ".join(tags[:4])) if tags else "Image",
                  embeds=[("clip", "", vec)])


# --------------------------------------------------------------------------- videos
def process_video(path: str) -> Result:
    """Sample N frames evenly across the video (1 per VIDEO_SECONDS_PER_FRAME, max VIDEO_MAX_FRAMES),
    embed each with CLIP, drop near-identical neighbours. Video score at search time = best frame."""
    import cv2
    cap = cv2.VideoCapture(path)
    frames, stamps = [], []
    try:
        if not cap.isOpened():
            raise CorruptFile("cannot open video")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if fps <= 0 or n_frames <= 0:
            raise CorruptFile("no fps/frame-count (corrupt or unsupported container)")
        duration = n_frames / fps
        k = max(1, min(config.VIDEO_MAX_FRAMES, math.ceil(duration / config.VIDEO_SECONDS_PER_FRAME)))
        for i in range(k):
            pos = int((i + 0.5) * n_frames / k)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, fr = cap.read()
            if not ok or fr is None:
                continue
            im = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
            im.thumbnail((512, 512))
            frames.append(im)
            stamps.append(pos / fps)
    finally:
        cap.release()
    if not frames:
        raise CorruptFile("no decodable frames")

    vecs = models.clip_images(frames)
    keep = [0]
    for i in range(1, len(vecs)):
        if float(vecs[i] @ vecs[keep[-1]]) < 0.97:
            keep.append(i)
    probs = models.tag_probs(vecs[keep]).mean(axis=0)
    tags = models.top_tags(probs)
    thumb = frames[keep[len(keep) // 2]]
    return Result(width=w, height=h, duration=duration, tags=tags, thumb=thumb,
                  summary=f"Video ({duration:.0f}s, {len(keep)} keyframes): " + ", ".join(tags[:4]),
                  embeds=[("clip", f"{stamps[i]:.2f}", vecs[i]) for i in keep])


# --------------------------------------------------------------------------- pdfs
_STOP = set("""this that with from have were been their there which about would could should these those than then
into over also such only other more most some what when where will your they them being does done each very much
many using used use based between within without through after before under while both however thus can may
figure table page pages the and for are not was has had its our you all any one two""".split())


def _chunks(text: str, size: int, overlap: int = 100):
    step = max(1, size - overlap)
    for i in range(0, len(text), step):
        piece = text[i:i + size].strip()
        if len(piece) >= 40:
            yield piece
        if i + size >= len(text):
            break


def process_pdf(path: str) -> Result:
    try:
        import pymupdf as fitz  # PyMuPDF >= 1.24.3
    except ImportError:
        import fitz
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise CorruptFile(f"cannot open PDF: {e}") from e
    chunks, all_text = [], []
    try:
        if doc.needs_pass:
            raise CorruptFile("encrypted PDF")
        pages = doc.page_count
        if pages == 0:
            raise CorruptFile("PDF has no pages")
        try:
            for pno in range(min(pages, config.PDF_MAX_PAGES)):
                txt = re.sub(r"\s+", " ", doc.load_page(pno).get_text("text")).strip()
                all_text.append(txt)
                for piece in _chunks(txt, config.PDF_CHUNK_CHARS):
                    chunks.append((pno + 1, piece))
                if len(chunks) >= config.PDF_MAX_CHUNKS:
                    break
            pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            page_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except CorruptFile:
            raise
        except Exception as e:
            raise CorruptFile(f"cannot read PDF content: {e}") from e
    finally:
        doc.close()

    page_img.thumbnail((512, 512))
    embeds = []
    cvec = models.clip_images([page_img])[0]          # visual look of page 1 (brochures are visual)
    embeds.append(("clip", "page 1", cvec))
    if chunks:
        tvecs = models.text([c[1] for c in chunks])    # semantic text search
        for (pno, piece), v in zip(chunks, tvecs):
            embeds.append(("text", f"{pno}|{piece[:220]}", v))

    full = " ".join(all_text)
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", full.lower()) if w not in _STOP]
    keywords = [w for w, _ in Counter(words).most_common(8)]
    summary = (full[:300] + "...") if full else "No extractable text (scanned PDF? OCR not enabled)"
    return Result(width=pix.width, height=pix.height, pages=pages, tags=keywords,
                  thumb=page_img, summary=summary, embeds=embeds)


def process(path: str, kind: str) -> Result:
    return {"image": process_image, "video": process_video, "pdf": process_pdf}[kind](path)
