# -*- coding: utf-8 -*-
"""A dense retrieval baseline, given every advantage it can fairly have.

This exists to measure the lane where an embedding model beats both lexical search and a graph:
finding text worded differently from the question. Without it, a comparison quietly omits the one
dimension where the alternative wins, and a report that omits its opponent's best case is marketing.

Fairness is the whole design, because a handicapped baseline proves nothing:

  * **Same corpus, same database.** It reads the passages the other systems read.
  * **Chunked, not truncated.** The model has a token limit. Truncating a document to its first few
    hundred words throws away most of its content and makes the baseline look weak for a reason that
    has nothing to do with the method. Documents are split into overlapping passages and a document
    scores as its best passage.
  * **Cached outside the project.** Embedding thousands of passages is slow, so results are cached in
    the system temp directory, keyed by the database's content. Nothing is written into the project,
    because an untracked file there would dirty the project's own repository.

It is optional. Without the dependency the harness runs and says the dense lane is **unmeasured**,
which is honest. Silently dropping the baseline and reporting the rest is not.
"""
import hashlib
import os
import sqlite3
import tempfile

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHUNK_WORDS = 220
CHUNK_OVERLAP = 40


def available():
    """(usable, reason). Reason explains what is missing when it is not."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False, "numpy is not installed"
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False, ("fastembed is not installed. It is a benchmarking dependency only, never a "
                       "runtime one: pip install 'oto-kg[bench]'")
    return True, ""


def _chunks(text):
    words = (text or "").split()
    if not words:
        return []
    step = max(1, CHUNK_WORDS - CHUNK_OVERLAP)
    out = []
    for start in range(0, len(words), step):
        piece = words[start:start + CHUNK_WORDS]
        if piece:
            out.append(" ".join(piece))
        if start + CHUNK_WORDS >= len(words):
            break
    return out


def _cache_path(database):
    """Keyed on the database's CONTENT, not its modification time.

    OTO rebuilds are deterministic, so a rebuild produces a byte-identical database with a new
    mtime. Keying on mtime threw away a cache that was still perfectly valid, and re-earning it costs
    twenty minutes on a corpus this size. Hashing 40 MB takes a fraction of a second, which is the
    right trade.
    """
    digest = hashlib.sha256()
    digest.update(MODEL_NAME.encode())
    digest.update(str(CHUNK_WORDS).encode())
    digest.update(str(CHUNK_OVERLAP).encode())
    with open(database, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return os.path.join(tempfile.gettempdir(), "oto-bench-%s.npz" % digest.hexdigest()[:24])


def _passages(database):
    """(source slug, chunk text) for every document. The same corpus the other systems see."""
    from .systems import _source_slug

    connection = sqlite3.connect("file:%s?mode=ro" % database, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("SELECT path, body FROM docs").fetchall()
    finally:
        connection.close()
    out = []
    for row in rows:
        slug = _source_slug(row["path"])
        for chunk in _chunks(row["body"]):
            out.append((slug, chunk))
    return out


def build_index(database, progress=None):
    """Embed the corpus once and cache it. Returns (slugs, matrix)."""
    import numpy as np

    path = _cache_path(database)
    if os.path.exists(path):
        cached = np.load(path, allow_pickle=True)
        return list(cached["slugs"]), cached["vectors"]

    passages = _passages(database)
    if not passages:
        return [], np.zeros((0, 1), dtype="float32")
    if progress:
        progress("embedding %d passage(s) from %d document(s); this is cached afterwards"
                 % (len(passages), len({s for s, _ in passages})))

    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL_NAME)
    vectors = np.array(list(model.embed([text for _slug, text in passages])), dtype="float32")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms                        # normalize once, so scoring is a dot product
    slugs = [slug for slug, _text in passages]
    np.savez_compressed(path, slugs=np.array(slugs, dtype=object), vectors=vectors)
    return slugs, vectors


class DenseSystem:
    """Nearest passages by embedding similarity. A document scores as its best passage."""

    name = "dense"

    def __init__(self, database, progress=None):
        self.database = database
        self.slugs, self.vectors = build_index(database, progress=progress)
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=MODEL_NAME)

    def _score(self, unit_query):
        """Cosine similarity against every passage, with the result actually checked.

        Both sides are unit-normalized, so every score must lie in [-1, 1] and be finite. That is
        asserted rather than assumed, because the alternative is a silently wrong ranking.

        The suppressed warning is noise, and it was verified before being silenced: on macOS with
        numpy 2.x over Apple's Accelerate BLAS, this matmul emits "overflow encountered" for inputs
        that contain no large values. It appears identically in float64, the two agree to 5e-08, and
        the ranking is unchanged. Silencing it without that check would be how a real numerical bug
        gets hidden, so the invariant below stays.
        """
        import numpy as np

        # numpy's own mechanism for floating-point flags, rather than matching warning text. The BLAS
        # raises overflow, invalid and divide-by-zero for the same non-event, and enumerating the
        # message strings meant a third variant slipped through.
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            scores = self.vectors @ unit_query

        if not np.all(np.isfinite(scores)):
            raise ValueError("similarity scores are not finite: the index or the query is corrupt")
        worst = float(np.max(np.abs(scores))) if scores.size else 0.0
        if worst > 1.001:
            raise ValueError("similarity score of %.4g is outside [-1, 1]: the vectors are not "
                             "unit-normalized" % worst)
        return scores

    def answer(self, question):
        import numpy as np

        from .systems import _blank

        result = _blank(self.name, question.get("id"))
        if not len(self.slugs):
            return result
        query = np.array(list(self._model.embed([question.get("question") or ""]))[0],
                         dtype="float32")
        norm = np.linalg.norm(query) or 1.0
        scores = self._score(query / norm)

        best = {}
        for index in np.argsort(-scores)[:200]:
            slug = self.slugs[int(index)]
            if slug not in best:
                best[slug] = float(scores[int(index)])
            if len(best) >= 20:
                break
        ranked = [slug for slug, _score in sorted(best.items(), key=lambda kv: -kv[1])]

        result["retrieved_sources"] = ranked
        result["surfaced_sources"] = ranked      # a passage retriever surfaces only passages
        # Like any passage retriever, it can only cite what it pulled. That is the honest limit of the
        # approach, and measuring it is the point of the comparison.
        result["cited_sources"] = ranked[:3]
        # No notion of entities and no notion of time. Recording that plainly, rather than guessing,
        # is what keeps the temporal column meaningful.
        result["answer_status"] = "unknown"
        return result
