"""
Phase 10 > Step 10-1: recall@k / precision@k 計測スクリプト

tests/gold_set.py で生成した output/gold_set.json を読み、
各クエリで hybrid_search() を実行して検索精度を計測する。
LLM 回答生成は skip_answer=True でスキップし、検索段のみを評価する。

実行:
    pixi run python tests/gold_set.py       # ゴールドセット生成（初回・DB更新時のみ）
    pixi run python tests/eval_retrieval.py # 評価実行
"""

import sys
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.app.retrieval import hybrid_search  # noqa: E402
from src.app.query_parser import parse_query  # noqa: E402

GOLD_PATH = ROOT / "output" / "gold_set.json"
OUT_DIR = ROOT / "output"


def _recall_precision(retrieved_ids: list[str], gold_ids: list[str]) -> tuple[float, float]:
    """retrieved_ids（top_k件）と gold_ids から recall・precision を算出する。"""
    if not gold_ids:
        return (float("nan"), float("nan"))
    gold_set = set(gold_ids)
    retrieved_set = set(retrieved_ids)
    hit = len(retrieved_set & gold_set)
    recall = hit / len(gold_set)
    precision = hit / len(retrieved_set) if retrieved_set else 0.0
    return (recall, precision)


def evaluate(
    top_k: int = 10,
    use_query_parser: bool = True,
    use_fts: bool = False,
    use_hyde: bool = False,
    ids: list[str] | None = None,
    embedding_source: str = "gemini",
) -> pd.DataFrame:
    """
    TODO 10-1-3 / 11-2-4 / 11-2-6 / 17-5-1 / 22-2-3: gold_set.json のクエリで hybrid_search() を実行し、
    recall@k・precision@k・hit@1 を算出した DataFrame を返す。
    use_fts / use_hyde は Phase 11 の A/B 比較用（hybrid_search() にそのまま伝播する）。
    ids: 指定時はこの id 集合（例: ["G21","G23"]）のみを評価する
    （Phase17: API クォータ節約・回帰確認の高速化のための部分実行）。
    embedding_source: "gemini"（デフォルト）または "ruri"（Phase 22 精度比較用）。
    """
    if not GOLD_PATH.exists():
        raise FileNotFoundError(
            f"{GOLD_PATH} が見つかりません。先に `pixi run python tests/gold_set.py` を実行してください。"
        )

    with open(GOLD_PATH, "r", encoding="utf-8") as f:
        gold_queries = json.load(f)

    if ids is not None:
        id_set = set(ids)
        gold_queries = [gq for gq in gold_queries if gq["id"] in id_set]
        missing = id_set - {gq["id"] for gq in gold_queries}
        if missing:
            print(f"  [WARN] gold_set.json に見つからない id: {sorted(missing)}")

    rows = []
    for gq in gold_queries:
        print(f"\n評価中: {gq['id']} [{gq['category']}] 「{gq['query']}」")
        t0 = time.time()
        try:
            result = hybrid_search(
                query=gq["query"],
                top_k=top_k,
                use_query_parser=use_query_parser,
                skip_answer=True,
                use_fts=use_fts,
                use_hyde=use_hyde,
                embedding_source=embedding_source,
            )
        except Exception as exc:
            print(f"  [ERROR] hybrid_search 失敗: {exc}")
            rows.append({
                "id": gq["id"], "category": gq["category"], "query": gq["query"],
                "recall": float("nan"), "precision": float("nan"), "hit1": float("nan"),
                "n_retrieved": 0, "n_gold": len(gq["gold_ids"]), "elapsed_sec": time.time() - t0,
                "retrieved_ids": "", "error": str(exc),
            })
            continue

        candidates = result["candidates"]
        retrieved_ids = candidates["id"].tolist() if not candidates.empty else []

        if gq["category"] == "semantic":
            # semantic カテゴリ: recall 計測対象外（定性確認のみ）
            recall, precision, hit1 = float("nan"), float("nan"), float("nan")
        elif not gq["gold_ids"]:
            # TODO 14-1-4: 正解0件が意図されたクエリ（例: G33「高潮リスクがなく
            # 駅から100m以内の宿泊施設」）。候補も0件なら正解(1.0)、
            # 1件以上あれば誤検出(0.0)として扱う（0除算を回避しつつ定量評価する）
            is_correct = 1.0 if not retrieved_ids else 0.0
            recall, precision, hit1 = is_correct, is_correct, is_correct
        else:
            recall, precision = _recall_precision(retrieved_ids, gq["gold_ids"])
            hit1 = 1.0 if retrieved_ids and retrieved_ids[0] in set(gq["gold_ids"]) else 0.0

        rows.append({
            "id": gq["id"],
            "category": gq["category"],
            "query": gq["query"],
            "recall": recall,
            "precision": precision,
            "hit1": hit1,
            "n_retrieved": len(retrieved_ids),
            "n_gold": len(gq["gold_ids"]),
            "elapsed_sec": round(time.time() - t0, 2),
            "retrieved_ids": ";".join(retrieved_ids),  # semantic カテゴリの定性比較用
            "error": None,
        })
        print(f"  recall={recall}, precision={precision}, hit1={hit1}, "
              f"取得={len(retrieved_ids)}件 / 正解={len(gq['gold_ids'])}件")

    df = pd.DataFrame(rows)

    print("\n" + "=" * 60)
    print("category 別マクロ平均（semantic は recall/precision/hit1 集計から除外）")
    print("=" * 60)
    scored = df[df["category"] != "semantic"]
    if len(scored) > 0:
        summary = scored.groupby("category")[["recall", "precision", "hit1"]].mean()
        print(summary.to_string())
    else:
        print("（structured/hybrid のクエリなし）")

    return df


def evaluate_paired(
    top_k: int = 10,
    ids: list[str] | None = None,
) -> pd.DataFrame:
    """
    TODO 22-5-1: gold_set.json の各クエリで parse_query() を1回だけ呼び、
    同じ ParsedQuery を embedding_source="gemini"/"ruri" 両方の hybrid_search() に
    渡してペア比較する。Step 22-3で判明した「別々の実行で parse_query() を
    呼び直すと非決定性により route がブレ、embedding の違いを検証できない」
    問題を、評価方法側で解消する（parse_query() 自体は変更しない）。
    """
    if not GOLD_PATH.exists():
        raise FileNotFoundError(
            f"{GOLD_PATH} が見つかりません。先に `pixi run python tests/gold_set.py` を実行してください。"
        )

    with open(GOLD_PATH, "r", encoding="utf-8") as f:
        gold_queries = json.load(f)

    if ids is not None:
        id_set = set(ids)
        gold_queries = [gq for gq in gold_queries if gq["id"] in id_set]
        missing = id_set - {gq["id"] for gq in gold_queries}
        if missing:
            print(f"  [WARN] gold_set.json に見つからない id: {sorted(missing)}")

    rows = []
    for gq in gold_queries:
        print(f"\n評価中: {gq['id']} [{gq['category']}] 「{gq['query']}」")
        pq = parse_query(gq["query"])
        print(f"  route確定用ParsedQuery: semantic_residual={pq.semantic_residual!r}")

        row = {"id": gq["id"], "category": gq["category"], "query": gq["query"], "route": None}
        for source in ("gemini", "ruri"):
            t0 = time.time()
            try:
                result = hybrid_search(
                    query=gq["query"],
                    top_k=top_k,
                    skip_answer=True,
                    parsed_query_override=pq,
                    embedding_source=source,
                )
            except Exception as exc:
                print(f"  [ERROR] hybrid_search({source}) 失敗: {exc}")
                row[f"recall_{source}"] = float("nan")
                row[f"precision_{source}"] = float("nan")
                row[f"hit1_{source}"] = float("nan")
                row[f"retrieved_ids_{source}"] = ""
                continue

            row["route"] = result["route"]
            candidates = result["candidates"]
            retrieved_ids = candidates["id"].tolist() if not candidates.empty else []

            if gq["category"] == "semantic":
                recall, precision, hit1 = float("nan"), float("nan"), float("nan")
            elif not gq["gold_ids"]:
                is_correct = 1.0 if not retrieved_ids else 0.0
                recall, precision, hit1 = is_correct, is_correct, is_correct
            else:
                recall, precision = _recall_precision(retrieved_ids, gq["gold_ids"])
                hit1 = 1.0 if retrieved_ids and retrieved_ids[0] in set(gq["gold_ids"]) else 0.0

            row[f"recall_{source}"] = recall
            row[f"precision_{source}"] = precision
            row[f"hit1_{source}"] = hit1
            row[f"retrieved_ids_{source}"] = ";".join(retrieved_ids)
            print(f"  [{source}] recall={recall}, precision={precision}, hit1={hit1}, "
                  f"取得={len(retrieved_ids)}件（{time.time() - t0:.1f}秒）")

        row["n_gold"] = len(gq["gold_ids"])
        rows.append(row)

    df = pd.DataFrame(rows)

    print("\n" + "=" * 60)
    print("category 別マクロ平均（Gemini vs RURI, semantic は集計から除外）")
    print("=" * 60)
    scored = df[df["category"] != "semantic"]
    if len(scored) > 0:
        cols = ["recall_gemini", "recall_ruri", "precision_gemini", "precision_ruri",
                "hit1_gemini", "hit1_ruri"]
        summary = scored.groupby("category")[cols].mean()
        print(summary.to_string())
        route_dist = df.groupby(["category", "route"]).size()
        print("\nroute分布（category別）:")
        print(route_dist.to_string())
    else:
        print("（structured/hybrid のクエリなし）")

    return df


def main() -> None:
    use_fts = "--fts" in sys.argv
    use_hyde = "--hyde" in sys.argv
    use_ruri = "--ruri" in sys.argv
    use_paired = "--paired" in sys.argv
    embedding_source = "ruri" if use_ruri else "gemini"
    ids = None
    for arg in sys.argv[1:]:
        if arg.startswith("--ids="):
            ids = arg.split("=", 1)[1].split(",")

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    if use_paired:
        df = evaluate_paired(ids=ids)
        suffix = "_paired" + ("_partial" if ids else "")
    else:
        df = evaluate(use_fts=use_fts, use_hyde=use_hyde, ids=ids, embedding_source=embedding_source)
        suffix = (
            ("_fts" if use_fts else "")
            + ("_hyde" if use_hyde else "")
            + ("_ruri" if use_ruri else "")
            + ("_partial" if ids else "")
        )

    out_path = OUT_DIR / f"eval_result_{ts}{suffix}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n結果を保存: {out_path}")


if __name__ == "__main__":
    main()
