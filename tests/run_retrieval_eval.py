# RAG 检索质量评测：绕过 /qa/chat 问答接口，直接连 Chroma 向量库做检索，算 Recall@k 和 MRR
# 用法: E:\conda\envs\langchain1.2\python.exe tests/run_retrieval_eval.py [--top-k 6] [--limit N]
#
# 两个指标是什么意思（写给第一次接触的同学）：
#   Recall@k  每个问题检索 k 个分块（k 默认 6），只要其中有 1 块包含答案关键词就算"召回"。
#             召回题数 / 总题数 = Recall@k，回答的是"答案有没有被找回来"。
#   MRR       找到每个问题"第一个相关块"的排名 rank，取 1/rank 再对所有题求平均。
#             rank=1 得 1 分，rank=2 得 0.5 分，越靠前分越高，回答的是"答案排得靠不靠前"。
#
# 相关性判定基于测试集的 answer_contains 关键词，分两种口径：
#   all = 分块必须包含全部关键词（严格，接近"该块真的含答案"，但答案被切碎时会漏判）
#   any = 分块包含任一关键词就算（宽松，"七"这类单字关键词容易误报）
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 把项目根目录加进搜索路径，这样单独运行本文件也能 import 到 agent 包
sys.path.insert(0, str(Path(__file__).parent.parent))

# 复用项目里现成的向量库连接，和 service/chatService.py 用的是同一个 Chroma
from agent.rag.initRag import getVector


def chunk_hits(chunk_text: str, keywords: list, mode: str) -> bool:
    """判断一个分块算不算"相关块"。

    mode="all" 时要求全部关键词都出现在分块里；mode="any" 时命中一个就算。
    """
    # 数一数有几个关键词出现在了这个分块里
    hit_count = 0
    for keyword in keywords:
        if keyword in chunk_text:
            hit_count += 1

    if mode == "all":
        return hit_count == len(keywords)
    else:
        return hit_count > 0


def first_rank(chunks: list, keywords: list, mode: str) -> int:
    """在检索结果里找第一个相关分块，返回它的排名（1 起数）。

    top-k 里没有任何相关块时返回 0，表示"没召回"。这个排名是算 MRR 的依据。
    """
    # enumerate(x, start=1) 同时给出序号和内容，序号从 1 开始
    for rank, doc in enumerate(chunks, start=1):
        if chunk_hits(doc.page_content, keywords, mode):
            return rank
    return 0


def bucket_stats(results: list, mode: str, group_key: str) -> dict:
    """按某个字段（difficulty 或 category）给题目分组，每组算召回率和 MRR。"""
    # 计数器长这样: {"easy": {"total": 14, "hits": 14, "rr_sum": 13.5}, ...}
    bucket = {}
    for r in results:
        group_name = r[group_key]
        if group_name not in bucket:
            bucket[group_name] = {"total": 0, "hits": 0, "rr_sum": 0.0}

        stat = bucket[group_name]
        stat["total"] += 1
        rank = r["ranks"][mode]
        if rank > 0:  # rank>0 说明召回了
            stat["hits"] += 1
            stat["rr_sum"] += 1 / rank

    # 把计数器换算成最终指标
    for stat in bucket.values():
        stat["recall"] = f"{stat['hits']}/{stat['total']}"
        stat["mrr"] = round(stat["rr_sum"] / stat["total"], 4)
    return bucket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=6, help="每个问题检索多少个分块")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    args = parser.parse_args()

    # 读测试集，每条有 q 问题 / answer_contains 关键词 / difficulty 难度 / category 类别
    testset_path = Path(__file__).parent / "rag_testset.json"
    items = json.loads(testset_path.read_text(encoding="utf-8"))
    if args.limit > 0:
        items = items[:args.limit]

    vector = getVector()

    # 逐题检索
    results = []
    for i, item in enumerate(items):
        # 去向量库做相似度检索，拿回 top-k 个最相近的分块
        chunks = vector.similarity_search(item["q"], k=args.top_k)
        rank_all = first_rank(chunks, item["answer_contains"], "all")
        rank_any = first_rank(chunks, item["answer_contains"], "any")

        results.append({
            "q": item["q"],
            "answer_contains": item["answer_contains"],
            "difficulty": item["difficulty"],
            "category": item["category"],
            "ranks": {"all": rank_all, "any": rank_any},
            # 每个块只留前 60 个字，写进报告方便人工核对检索结果
            "chunk_previews": [doc.page_content[:60] for doc in chunks],
        })

        # 没召回（rank=0）时打印 "-"，好看一些
        rank_all_text = rank_all if rank_all > 0 else "-"
        rank_any_text = rank_any if rank_any > 0 else "-"
        print(f"[{i + 1}/{len(items)}] rank_all={rank_all_text} rank_any={rank_any_text} | {item['q']}")

    # 汇总整体指标
    total = len(results)
    summary = {}
    for mode in ("all", "any"):
        hits = 0      # 召回了多少题
        rr_sum = 0.0  # 所有题的倒数排名之和
        for r in results:
            rank = r["ranks"][mode]
            if rank > 0:
                hits += 1
                rr_sum += 1 / rank
        summary[mode] = {"recall": f"{hits}/{total}", "mrr": round(rr_sum / total, 4)}

    by_difficulty = bucket_stats(results, "all", "difficulty")
    by_category = bucket_stats(results, "all", "category")

    # 打印报告
    print(f"\n========== 检索评测结果 (k={args.top_k}) ==========")
    print(f"{'口径':<6}{'Recall@' + str(args.top_k):<14}{'MRR'}")
    print(f"{'all':<8}{summary['all']['recall']:<14}{summary['all']['mrr']}")
    print(f"{'any':<8}{summary['any']['recall']:<14}{summary['any']['mrr']}")

    print("\n按难度 (口径=all):")
    for difficulty, stat in sorted(by_difficulty.items()):
        print(f"  {difficulty:<12} recall={stat['recall']:<8} mrr={stat['mrr']}")

    print("\n按类别 (口径=all):")
    # 类别按题目数从多到少排，题目多的排前面
    sorted_categories = sorted(by_category.items(), key=lambda kv: kv[1]["total"], reverse=True)
    for category, stat in sorted_categories:
        print(f"  {category:<12} recall={stat['recall']:<8} mrr={stat['mrr']}")

    # 保存详细报告
    now_text = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(__file__).parent / f"retrieval_eval_{now_text}.json"
    report = {
        "top_k": args.top_k,
        "summary": summary,
        "by_difficulty": by_difficulty,
        "by_category": by_category,
        "results": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细报告: {report_path}")


if __name__ == "__main__":
    main()
