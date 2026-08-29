"""Full-text search (BM25 + RRF fusion) and HyDE query rewriting.

Builds entirely on the existing `text_card`/embeddings/`building_chunks` —
no re-embedding required.

DuckDB's FTS extension tokenizes on ASCII whitespace/punctuation by default,
which barely works on unsegmented Japanese text (this project's `text_card`
format): compound words and proper nouns (e.g. "広島駅") never get extracted
as standalone tokens, confirmed against real data (see work_log.md). This is
fixed by pre-segmenting with SudachiPy (split mode C) and applying the same
tokenization to both documents and queries — see `tokenize_ja()`,
`ensure_fts_index()`, `fts_search()`.
"""

import os
import time

import duckdb
import pandas as pd

# ============================================================
# Japanese tokenization (SudachiPy)
# ============================================================

# Module-level cache — dictionary loading is expensive, so build only once.
_sudachi_tokenizer = None

# Chunk size guarding against Sudachi's per-call tokenization limit (~49,000 chars).
_SUDACHI_CHUNK_SIZE = 10_000


def _get_sudachi_tokenizer():
    """Lazily build and cache the SudachiPy Tokenizer at module level."""
    global _sudachi_tokenizer
    if _sudachi_tokenizer is None:
        from sudachipy import Dictionary
        _sudachi_tokenizer = Dictionary().create()
    return _sudachi_tokenizer


def tokenize_ja(text: str) -> str:
    """Segment Japanese text with SudachiPy Mode C, space-joining the surface forms.

    Mode C keeps proper nouns / compound words (e.g. "広島駅") as a single
    token, fixing the "proper nouns never match" problem that DuckDB FTS's
    default ASCII-based tokenizer has on Japanese text.

    Args:
        text: The text to segment. Whitespace/symbol-only tokens are dropped.

    Returns:
        Space-separated surface forms, or "" if `text` is empty/blank.
    """
    if not text or not text.strip():
        return ""

    from sudachipy import SplitMode

    tokenizer = _get_sudachi_tokenizer()

    # Guard against Sudachi's per-call character limit. text_card averages
    # 579 chars so chunking is rarely needed, but this protects against
    # unusually long input.
    surfaces: list[str] = []
    for i in range(0, len(text), _SUDACHI_CHUNK_SIZE):
        chunk = text[i:i + _SUDACHI_CHUNK_SIZE]
        for m in tokenizer.tokenize(chunk, SplitMode.C):
            surface = m.surface().strip()
            if surface:
                surfaces.append(surface)

    return " ".join(surfaces)


# ============================================================
# FTS index and search
# ============================================================

def ensure_fts_index(rag_con: duckdb.DuckDBPyConnection) -> None:
    """Build the FTS index, creating `building_chunks_fts` if needed.

    Kept as a separate table (rather than an `ALTER TABLE` adding a
    tokenized column to `building_chunks`) since `building_chunks` carries
    an HNSW index with experimental persistence enabled. Only rebuilds when
    the row count doesn't match `building_chunks` — `tokenize_ja()` runs in
    Python, so recomputing every row unconditionally would be expensive.

    Args:
        rag_con: An open connection from `connect_rag()`.
    """
    rag_con.execute("INSTALL fts; LOAD fts;")
    rag_con.execute("""
        CREATE TABLE IF NOT EXISTS building_chunks_fts (
            id     VARCHAR PRIMARY KEY,
            wakati VARCHAR NOT NULL
        )
    """)

    src_count = rag_con.execute("SELECT COUNT(*) FROM building_chunks").fetchone()[0]
    fts_count = rag_con.execute("SELECT COUNT(*) FROM building_chunks_fts").fetchone()[0]

    if fts_count != src_count:
        print(f"  building_chunks_fts を再構築中（{fts_count} → {src_count} 件）...")
        rag_con.execute("DELETE FROM building_chunks_fts")
        rows = rag_con.execute("SELECT id, text_card FROM building_chunks").fetchall()
        wakati_rows = [(row_id, tokenize_ja(text_card)) for row_id, text_card in rows]
        wakati_df = pd.DataFrame(wakati_rows, columns=["id", "wakati"])
        rag_con.register("_tmp_wakati", wakati_df)
        rag_con.execute("INSERT INTO building_chunks_fts SELECT id, wakati FROM _tmp_wakati")
        rag_con.unregister("_tmp_wakati")
        print(f"  building_chunks_fts 再構築完了: {len(wakati_rows)} 件")

    # Try to drop a leftover old-style index (directly on
    # building_chunks.text_card), if one exists from a prior implementation.
    try:
        rag_con.execute("PRAGMA drop_fts_index('building_chunks')")
    except duckdb.Error:
        pass

    rag_con.execute("""
        PRAGMA create_fts_index(
            'building_chunks_fts', 'id', 'wakati',
            stemmer='none', overwrite=1
        )
    """)


def fts_search(
    rag_con: duckdb.DuckDBPyConnection,
    query_text: str,
    top_k: int = 30,
) -> pd.DataFrame:
    """Run BM25 full-text search with a tokenized query.

    Requires `ensure_fts_index()` to have already run. Applies the same
    `tokenize_ja()` to the query as was used for the document side
    (`building_chunks_fts.wakati`) — required, since mismatched tokenization
    between query and documents would silently break matching.

    Args:
        rag_con: An open connection from `connect_rag()`.
        query_text: The raw (untokenized) query text.
        top_k: Maximum number of results to return.

    Returns:
        A DataFrame with `id`, `bm25_score` columns, sorted by score
        descending. Empty if there's no FTS index or no matches.
    """
    wakati_query = tokenize_ja(query_text)
    if not wakati_query:
        return pd.DataFrame(columns=["id", "bm25_score"])

    try:
        df = rag_con.execute(
            """
            SELECT id, fts_main_building_chunks_fts.match_bm25(id, ?) AS bm25_score
            FROM building_chunks_fts
            WHERE bm25_score IS NOT NULL
            ORDER BY bm25_score DESC
            LIMIT ?
            """,
            [wakati_query, top_k],
        ).df()
    except duckdb.Error:
        # E.g. the FTS index doesn't exist yet — caller treats this as empty
        # and skips RRF fusion.
        return pd.DataFrame(columns=["id", "bm25_score"])
    return df


def rrf_merge(
    vec_df: pd.DataFrame,
    fts_df: pd.DataFrame,
    k: int = 60,
    id_col: str = "id",
) -> pd.DataFrame:
    """Fuse vector search and FTS results via Reciprocal Rank Fusion.

    `rrf_score = 1/(k + rank_vec) + 1/(k + rank_fts)` (a missing rank
    contributes 0 to its term).

    Args:
        vec_df: Vector search results, already ranked (row order = rank).
        fts_df: FTS results, already ranked.
        k: RRF's rank-damping constant.
        id_col: The column both DataFrames use as their join key.

    Returns:
        `vec_df`'s columns plus `rrf_score`, sorted by `rrf_score` descending.
        IDs present only in `fts_df` are added as rows with NaN in `vec_df`'s
        other columns.
    """
    vec_ranked = vec_df.reset_index(drop=True)
    vec_ranked["_rank_vec"] = range(1, len(vec_ranked) + 1)

    fts_ranked = fts_df.reset_index(drop=True)[[id_col]].copy()
    fts_ranked["_rank_fts"] = range(1, len(fts_ranked) + 1)

    merged = pd.merge(vec_ranked, fts_ranked, on=id_col, how="outer")
    merged["_rank_vec"] = merged["_rank_vec"].fillna(float("inf"))
    merged["_rank_fts"] = merged["_rank_fts"].fillna(float("inf"))

    merged["rrf_score"] = (
        1.0 / (k + merged["_rank_vec"]) + 1.0 / (k + merged["_rank_fts"])
    )
    merged = merged.sort_values("rrf_score", ascending=False).reset_index(drop=True)
    merged = merged.drop(columns=["_rank_vec", "_rank_fts"])
    return merged


# ============================================================
# HyDE-style query rewriting
# ============================================================

def hyde_rewrite(semantic_residual: str) -> str:
    """Rewrite semantic residual text into a hypothetical building card via Gemini.

    Uses Gemini Flash (temperature=0) to turn a short query intent into a
    concise passage resembling a real building card, which embeds closer to
    matching cards than the raw query does. Falls back to the original text
    on any failure — never blocks the caller.

    Args:
        semantic_residual: The query's semantic residual text.

    Returns:
        The rewritten text, or the original `semantic_residual` unchanged if
        rewriting failed or wasn't attempted (empty input, no API key, error).
    """
    if not semantic_residual or not semantic_residual.strip():
        return semantic_residual

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return semantic_residual

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = (
            "以下の検索意図を満たす建物の特徴を、実際の建物カルテと同じ簡潔な"
            "日本語の説明文として2〜3文で生成してください。"
            "建物IDや具体的な数値は創作しないこと。\n\n"
            f"【検索意図】\n{semantic_residual}"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0),
        )
        text = response.text.strip()
        return text if text else semantic_residual
    except Exception as exc:
        print(f"  [WARN] hyde_rewrite 失敗（フォールバック）: {exc}")
        return semantic_residual
