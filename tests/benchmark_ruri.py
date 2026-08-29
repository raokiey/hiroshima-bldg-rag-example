"""
Phase 21: RURI v3 310m 埋め込みモデルのベンチマーク検証

目的: GPU非搭載ノートPC（メモリ16GB）で RURI v3 310m がどの程度の速度・
メモリで動くかを実測する。本番の埋め込み切り替え（再埋め込み・DuckDB スキーマ
変更・vector_search() 改修）は一切行わない。

位置づけ: 既存パイプライン（src/phase3_enrichment.py 等）には一切変更を
加えず、read-only で `build_text_card()` を呼び出すのみ。本ファイルは
単体で完結しており、不要になれば本ファイルを削除するだけで元に戻せる。

実行方法:
    pixi run python tests/benchmark_ruri.py            # サンプル100件
    pixi run python tests/benchmark_ruri.py --full      # 全2,958件
    pixi run python tests/benchmark_ruri.py --n 500     # 件数指定
"""

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.pipeline.codelist_loader import CodelistLoader  # noqa: E402
from src.pipeline.enrichment import build_text_card       # noqa: E402

CACHE_PATH = ROOT / "output" / "building_attrs_cache.parquet"
MODEL_NAME = "cl-nagoya/ruri-v3-310m"

# RURI v3 の「1+3プレフィックス方式」（モデルカード仕様）
DOC_PREFIX = "検索文書: "
QUERY_PREFIX = "検索クエリ: "


def load_sample_text_cards(n: int | None) -> list[str]:
    """キャッシュ済み属性 DataFrame から text_card を n 件生成する。"""
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            f"{CACHE_PATH} が見つかりません。先に `pixi run enrich` を"
            "一度実行してキャッシュを作成してください。"
        )
    df = pd.read_parquet(CACHE_PATH)
    if n is not None:
        df = df.head(n)

    cl = CodelistLoader()
    cards = [build_text_card(row.to_dict(), cl) for _, row in df.iterrows()]
    return cards


def run_benchmark(texts: list[str], batch_size: int) -> dict:
    """RURI v3 で texts を埋め込み、時間・メモリ・次元数を計測する。"""
    import psutil
    from sentence_transformers import SentenceTransformer

    proc = psutil.Process()
    mem_before_mb = proc.memory_info().rss / (1024 * 1024)

    t0 = time.perf_counter()
    model = SentenceTransformer(MODEL_NAME)
    load_elapsed = time.perf_counter() - t0

    prefixed = [DOC_PREFIX + t for t in texts]

    t1 = time.perf_counter()
    embeddings = model.encode(
        prefixed, batch_size=batch_size, show_progress_bar=False
    )
    encode_elapsed = time.perf_counter() - t1

    mem_after_mb = proc.memory_info().rss / (1024 * 1024)

    n = len(texts)
    return {
        "n_texts": n,
        "batch_size": batch_size,
        "model_load_sec": round(load_elapsed, 3),
        "encode_total_sec": round(encode_elapsed, 3),
        "encode_per_item_sec": round(encode_elapsed / n, 4) if n else None,
        "mem_before_mb": round(mem_before_mb, 1),
        "mem_after_mb": round(mem_after_mb, 1),
        "mem_delta_mb": round(mem_after_mb - mem_before_mb, 1),
        "embedding_dim": int(embeddings.shape[1]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="全2,958件で実行")
    parser.add_argument("--n", type=int, default=100, help="サンプル件数（デフォルト100）")
    args = parser.parse_args()

    n = None if args.full else args.n

    print("=" * 60)
    print(f"Phase 21 ベンチマーク: {MODEL_NAME}")
    print(f"サンプル件数: {'全件' if n is None else n}")
    print("=" * 60)

    texts = load_sample_text_cards(n)
    print(f"text_card 生成完了: {len(texts)} 件")

    results = []
    for batch_size in (8, 32):
        print(f"\n--- batch_size={batch_size} ---")
        result = run_benchmark(texts, batch_size)
        for k, v in result.items():
            print(f"  {k}: {v}")
        results.append(result)

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"benchmark_ruri_{time.strftime('%Y%m%d_%H%M')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"model": MODEL_NAME, "doc_prefix": DOC_PREFIX, "results": results},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n結果を保存しました: {out_path}")


if __name__ == "__main__":
    main()
