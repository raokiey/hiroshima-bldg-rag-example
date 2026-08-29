"""Runtime query-side embedding with RURI v3 310m.

Split out of the old `phase22_ruri_embed.py` (Phase 32): this half runs inside
the FastAPI server process and must stay in the `app` package, while the batch
indexing half moved to `src/pipeline/ruri_embed.py`. The two files intentionally
each keep their own lazily-loaded model cache — they never run in the same
process, so sharing a cache across them would add coupling for no benefit.
"""

MODEL_NAME = "cl-nagoya/ruri-v3-310m"
QUERY_PREFIX = "検索クエリ: "

# Module-level cache so the model survives across requests within one server
# process. src/app/main.py's startup lifespan calls embed_query_ruri() once at
# boot specifically to populate this cache before the first real request.
_model = None


def _get_model():
    """Lazily load and cache the SentenceTransformer model for this process."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_query_ruri(text: str) -> list[float]:
    """Embed a user query with RURI v3, matching the "1+3 prefix" convention.

    Args:
        text: The query text (already resolved to the semantic residual or raw
            query by the caller).

    Returns:
        A 768-dimensional embedding vector as a plain list of floats (so it can
        be passed straight into a DuckDB parameterized query).
    """
    model = _get_model()
    vec = model.encode([QUERY_PREFIX + text], show_progress_bar=False)[0]
    return vec.tolist()
