"""Embedding models (lazy-loaded singletons).

* CLIP (clip-ViT-B-32): images / video frames / PDF page renders  <->  text queries (shared space)
* MiniLM (all-MiniLM-L6-v2): PDF text chunks  <->  text queries
"""
import threading

import numpy as np

from . import config
from .vocab import TAG_VOCAB

_lock = threading.Lock()
_clip = None
_text = None
_tag_mat = None


def _get_clip():
    global _clip
    with _lock:
        if _clip is None:
            from sentence_transformers import SentenceTransformer
            _clip = SentenceTransformer(config.CLIP_MODEL)
        return _clip


def _get_text():
    global _text
    with _lock:
        if _text is None:
            from sentence_transformers import SentenceTransformer
            _text = SentenceTransformer(config.TEXT_MODEL)
        return _text


def clip_images(images) -> np.ndarray:
    return _get_clip().encode(images, batch_size=16, convert_to_numpy=True,
                              normalize_embeddings=True, show_progress_bar=False).astype(np.float32)


def clip_text(texts) -> np.ndarray:
    texts = [t[:120] for t in texts]  # CLIP context window is 77 tokens
    return _get_clip().encode(texts, convert_to_numpy=True,
                              normalize_embeddings=True, show_progress_bar=False).astype(np.float32)


def text(texts) -> np.ndarray:
    return _get_text().encode(texts, batch_size=64, convert_to_numpy=True,
                              normalize_embeddings=True, show_progress_bar=False).astype(np.float32)


def _tags():
    global _tag_mat
    if _tag_mat is None:
        _tag_mat = clip_text([f"a photo of {t}" for t in TAG_VOCAB])
    return _tag_mat


def tag_probs(vecs: np.ndarray) -> np.ndarray:
    logits = 100.0 * vecs @ _tags().T
    logits = logits - logits.max(axis=1, keepdims=True)
    e = np.exp(logits)
    return e / e.sum(axis=1, keepdims=True)


def top_tags(prob: np.ndarray, k: int = 6, min_p: float = 0.05):
    idx = np.argsort(-prob)[:k]
    out = []
    for i in idx:
        if prob[i] >= min_p:
            label = TAG_VOCAB[i]
            for art in ("a ", "an "):
                if label.startswith(art):
                    label = label[len(art):]
                    break
            out.append(label)
    return out


def warmup():
    _get_clip()
    _get_text()
    _tags()
