"""Batch-embeds all building_chunks rows with RURI v3 310m (offline, run manually).

Purpose: build `building_chunks_ruri_embed`, an additional table used to compare
retrieval quality against `gemini-embedding-001` (and also to serve
production queries — RURI runs locally, avoiding the Gemini embedding API's
network round-trip). The existing `building_chunks` table and its HNSW index are
never touched; rollback is a single `DROP TABLE building_chunks_ruri_embed;`.

RURI v3 uses a "1 model + 3 prefixes" convention: documents get "検索文書: " and
queries get "検索クエリ: " (see `src/app/ruri_query.py` for the query side).

Usage:
    pixi run python -m src.pipeline.ruri_embed
"""

import time

from src.common.db import connect_rag

MODEL_NAME = "cl-nagoya/ruri-v3-310m"
DOC_PREFIX = "検索文書: "
EMBEDDING_DIM = 768

# Module-level cache so repeated calls within one process don't reload the model.
_model = None


def _get_model():
    """Lazily load and cache the SentenceTransformer model for this process."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def build_ruri_index(batch_size: int = 32) -> None:
    """Embed every `building_chunks` row with RURI v3 and store the result.

    Drops and recreates `building_chunks_ruri_embed` (same convention as the
    other pipeline scripts that rebuild derived tables from scratch).

    Args:
        batch_size: Batch size passed to `SentenceTransformer.encode()`. Testing
            showed no meaningful speed difference between 8 and 32, so this is
            mostly about memory/progress-bar granularity.
    """
    rag_con = connect_rag()
    try:
        df = rag_con.execute("SELECT id, text_card FROM building_chunks").df()
        n = len(df)
        print(f"対象件数: {n:,} 件")

        model = _get_model()
        texts = [DOC_PREFIX + t for t in df["text_card"].tolist()]

        t0 = time.perf_counter()
        embeddings = model.encode(
            texts, batch_size=batch_size, show_progress_bar=True
        )
        elapsed = time.perf_counter() - t0
        print(f"埋め込み生成完了: {elapsed:.1f}秒（{elapsed / n:.3f}秒/件）")

        rag_con.execute("DROP TABLE IF EXISTS building_chunks_ruri_embed;")
        rag_con.execute(f"""
            CREATE TABLE building_chunks_ruri_embed (
                id        VARCHAR PRIMARY KEY,
                embedding FLOAT[{EMBEDDING_DIM}]
            );
        """)

        insert_df = df[["id"]].copy()
        insert_df["embedding"] = list(embeddings)
        rag_con.register("insert_df", insert_df)
        rag_con.execute(
            "INSERT INTO building_chunks_ruri_embed SELECT id, embedding FROM insert_df;"
        )

        count = rag_con.execute(
            "SELECT COUNT(*) FROM building_chunks_ruri_embed"
        ).fetchone()[0]
        print(f"building_chunks_ruri_embed へ保存完了: {count:,} 件")
    finally:
        rag_con.close()


def main() -> None:
    print("=" * 60)
    print(f"RURI v3 310m 全件埋め込み生成: {MODEL_NAME}")
    print("=" * 60)
    t0 = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"開始時刻: {t0}")
    start = time.perf_counter()

    build_ruri_index()

    elapsed = time.perf_counter() - start
    t1 = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n終了時刻: {t1}")
    print(f"総所要時間: {elapsed / 60:.1f}分")


if __name__ == "__main__":
    main()
