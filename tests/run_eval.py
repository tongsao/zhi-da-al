# RAG 问答质量评测：跑 rag_testset.json，逐条调用 /qa/chat 问答接口，用关键词判断回答对不对
# 用法: E:\conda\envs\langchain1.2\python.exe tests/run_eval.py [--top-k 6] [--limit N] [--keep]
#   --top-k  检索多少个分块喂给大模型，默认 6（与问答接口一致）
#   --limit  只跑前 N 条，0 表示全部（冒烟测试用 --limit 3 很快）
#   --keep   保留评测产生的会话记录（默认评测完即删，不污染聊天历史）
#
# 判分规则：模型的回答只要包含 answer_contains 里任意一个关键词就算 PASS
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000/api/v1/qa"
CONV_ID_BASE = 990001  # 评测专用会话号段，避免与真实会话冲突


def ask(question: str, conversation_id: int, top_k: int) -> str:
    """调 /qa/chat 接口问一个问题，返回模型的回答文本。"""
    resp = requests.post(
        f"{BASE_URL}/chat",
        params={"question": question, "conversation_id": conversation_id, "top_k": top_k},
        timeout=180,
    ).json()
    # 接口约定 code="0" 才算成功，其他值都是失败
    if resp.get("code") != "0":
        raise RuntimeError(resp.get("message", "unknown error"))
    return resp["data"]["content"]


def judge(answer: str, keywords: list) -> tuple:
    """判断模型回答命中了哪些答案关键词。

    命中任意一个就算通过，同时把命中词拼成字符串返回，方便人工核对。
    """
    hits = []
    for keyword in keywords:
        if keyword in answer:
            hits.append(keyword)

    if hits:
        return True, "/".join(hits)
    else:
        return False, "miss"


def cleanup(conversation_id: int):
    """删除评测产生的会话记录，避免污染真实聊天历史。"""
    requests.delete(f"{BASE_URL}/chat/conversation_id", params={"conversation_id": str(conversation_id)}, timeout=30)


def bucket_stats(results: list, group_key: str) -> dict:
    """按某个字段（difficulty 或 category）给题目分组，统计每组的通过数。"""
    bucket = {}
    for r in results:
        group_name = r[group_key]
        if group_name not in bucket:
            bucket[group_name] = {"total": 0, "passed": 0}

        stat = bucket[group_name]
        stat["total"] += 1
        if r["passed"]:
            stat["passed"] += 1
    return bucket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    parser.add_argument("--keep", action="store_true", help="保留评测会话，便于事后排查")
    args = parser.parse_args()

    # 读测试集，每条有 q 问题 / answer_contains 关键词 / difficulty 难度 / category 类别
    testset_path = Path(__file__).parent / "rag_testset.json"
    items = json.loads(testset_path.read_text(encoding="utf-8"))
    if args.limit > 0:
        items = items[:args.limit]

    # 逐题调接口问答并打分
    results = []
    for i, item in enumerate(items):
        # 每道题用独立的会话号，互不串上下文
        conv_id = CONV_ID_BASE + i

        # 调接口问答并计时
        t0 = time.time()
        try:
            answer = ask(item["q"], conv_id, args.top_k)
            error = None
        except Exception as e:
            answer, error = "", str(e)
        latency = round(time.time() - t0, 1)

        passed, hit_kw = judge(answer, item["answer_contains"])

        # PASS = 回答有关键词；ERR = 接口调用失败；MISS = 调用成功但没命中
        if passed:
            status = "PASS"
        elif error:
            status = "ERR "
        else:
            status = "MISS"
        print(f"[{i + 1}/{len(items)}] {status} {latency:>5.1f}s hit={hit_kw} | {item['q']}")

        results.append({
            "q": item["q"],
            "answer_contains": item["answer_contains"],
            "difficulty": item["difficulty"],
            "category": item["category"],
            "model_answer": answer,
            "hit_keywords": hit_kw,
            "passed": passed,
            "latency_s": latency,
            "error": error,
        })

        # 默认评测完就删会话；--keep 时保留方便排查
        if not args.keep:
            cleanup(conv_id)

    # 汇总：总通过数和平均耗时
    total = len(results)
    passed = 0
    latency_sum = 0.0
    for r in results:
        if r["passed"]:
            passed += 1
        latency_sum += r["latency_s"]

    by_difficulty = bucket_stats(results, "difficulty")
    by_category = bucket_stats(results, "category")

    # 打印报告
    print("\n========== 评测结果 ==========")
    print(f"总命中率: {passed}/{total} ({passed / total:.0%})")
    print(f"平均耗时: {latency_sum / total:.1f}s")

    print("\n按难度:")
    for difficulty, stat in sorted(by_difficulty.items()):
        print(f"  {difficulty:<8} {stat['passed']}/{stat['total']}")

    print("\n按类别:")
    # 类别按题目数从多到少排，题目多的排前面
    sorted_categories = sorted(by_category.items(), key=lambda kv: kv[1]["total"], reverse=True)
    for category, stat in sorted_categories:
        print(f"  {category:<12} {stat['passed']}/{stat['total']}")

    # 保存详细报告
    now_text = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(__file__).parent / f"eval_report_{now_text}.json"
    report = {
        "top_k": args.top_k,
        "summary": {"passed": passed, "total": total, "by_difficulty": by_difficulty, "by_category": by_category},
        "results": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细报告: {report_path}")


if __name__ == "__main__":
    main()
