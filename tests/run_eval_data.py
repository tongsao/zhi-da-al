# 自检脚本：命令行独立跑 RAG 生成评估，不依赖 FastAPI / 前端 / 数据库，用于本地快速迭代。
# ⚠️ 这里的生成 prompt 与线上 service/chatService.py 的 GEN_SYSTEM_PROMPT 不是同一份
#   （线上是三步法，这里是早期的 6 条【回答要求】+【示例】），只有裁判 prompt 已对齐。
#   生成侧不同源，所以本脚本的分数只能跟自己的历史轮次比，不代表线上效果；
#   要看线上真实效果请用前端「生成评估」页（/eval/gen/run + chatService.generateAnswer）。
import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# 单独运行本文件时把项目根目录加进搜索路径，否则找不到 agent/service 包
sys.path.insert(0, str(Path(__file__).parent.parent))

# 本地网络到不了 LangSmith，评测时关掉 tracing 免得日志刷告警；
# load_dotenv 不覆盖已有环境变量，所以必须放在 import agent 之前
os.environ["LANGSMITH_TRACING"] = "false"

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent.initChatModel import getModel
from service.chatService import format_docs
from service.ragFileService import hybridRetrieve

model = getModel()

# 你的 RAG 生成链（用之前 LCEL 那套）
gen_prompt = ChatPromptTemplate.from_template("""你是证券公司的合规顾问，回答必须严格依据提供的资料。

【回答要求】
1. 资料中没有的信息，明确回答"资料中未找到相关信息"，不得编造。
2. **如果问题涉及多个情形、条件、程序或人员范围，必须完整列举资料中的全部要点，不得遗漏。**
3. 使用编号列表逐条列出，每条对应资料中的一项。
4. 涉及数字、期限、比例时，引用原文表述，不要改写或概括。
5. 回答前先通读全部资料，确认已覆盖所有相关条款，再开始作答。
6. 列举的条目必须与资料一一对应，不得补充资料外的情形、条件或兜底表述。

【示例】
问题：公司不得录用哪些人员？
回答：根据资料，公司不得录用以下人员：
（一）因贪污、贿赂、侵占财产、挪用财产或者破坏社会主义市场经济秩序被判处刑罚执行期满未逾五年的人员；
（二）因犯罪被剥夺政治权利执行期满未逾五年的人员；
（三）...（资料中列举的全部情形均需列出）

【资料】
{context}

【问题】
{question}

【回答】""")

# DISABLE_THINKING 只管生成链；裁判链任务简单，永远关思考（提速且判分更稳定）
# 评测时两条链都 bind temperature=0，消除 0.5 温度带来的轮间指标漂移（单轮漂移实测 ±0.2）
# 检索与生产链路同源：hybridRetrieve 双路召回(向量25+BM25 5) + RRF 粗排(留30) + bge 重排取 TOP_K，
# 替代裸向量 top_k——八轮数据表明加大裸召回窗口会同时召回干扰块（第21题空答案/编造复发）
# ★ 当前基线（第11轮起）：hybrid + temp=0 + 带检索资料的裁判 + 2并发，改动任何参数前先留基线对照
#   第10轮旧口径（裁判不看资料）基线 c=1.93/p=1.78/f=1.98，与第11轮不可比
DISABLE_THINKING = False
TOP_K = 7
gen_think = {"temperature": 0, "extra_body": {"thinking": {"type": "disabled"}}} if DISABLE_THINKING else {"temperature": 0}

def retrieve_context(question: str) -> str:
    return format_docs(hybridRetrieve(question, TOP_K))

# 检索结果由调用方算好传入：同一份资料既喂生成、也喂裁判，
# 裁判手里有资料才能分清「编造」与「资料里有但 golden 没列」
gen_chain = gen_prompt | model.bind(**gen_think) | StrOutputParser()

judge_prompt = ChatPromptTemplate.from_template("""你是证券合规领域的评审专家，请评估【系统生成答案】的质量。

【问题】{question}
【检索到的资料】（判定 faithfulness 的唯一依据）
{context}
【标准答案】（判定 correctness / completeness 的依据，仅列核心要点）
{golden}
【系统生成答案】
{generated}

【评分规则】
1. faithfulness：生成答案中的每个事实，能否在【检索到的资料】中找到依据？
   2=全部有依据｜1=轻微推断但未脱离资料｜0=存在资料中完全没有的内容
   ⚠️ golden 只列核心要点，不代表资料全集。生成答案包含 golden 未列出、
      但资料中确实存在的内容，属于【完整】而非【不忠实】，不得扣分。

2. correctness：与【标准答案】相比，事实是否正确？
   重点检查数字、期限、比例、量词。
   ⚠️ 不得因"答案比 golden 更详细"扣分。

3. completeness：【问题所问范围】内的要点是否齐全？
   2=要点+配套限定条件齐全｜1=答对主干但遗漏限定条件｜0=遗漏核心要点
   ⚠️ 判定"遗漏"前必须在生成答案中逐字查找该要点，确认不存在才可扣分。

输出 JSON：{{"correctness":<0-2>,"completeness":<0-2>,"faithfulness":<0-2>,"reason":"<一句话>"}}
""")

judge_chain = judge_prompt | model.bind(temperature=0, extra_body={"thinking": {"type": "disabled"}}) | StrOutputParser()

# 非重试类偶发错误按 10s/30s 退避重试；429 单独走 RATE_LIMIT_WAIT
RETRY_WAIT = (10, 30)
# 429 可能是账户在途超限（由门闸压住），也可能是服务端过载（通常几十秒自愈）。
# 短退避三次全落在同一个过载窗口里必然整题判死，所以 429 单独用更长的退避
RATE_LIMIT_WAIT = (20, 60)
# 与 --workers 默认值一致，门闸不主动压并发；只防意外叠加
MAX_INFLIGHT = 4
_GATE = threading.Semaphore(MAX_INFLIGHT)
_COOLDOWN_UNTIL = 0.0

def isRateLimited(exc) -> bool:
    return getattr(exc, "status_code", None) == 429 or "429" in str(exc)

def backoffSeconds(attempt: int, limited: bool) -> float:
    schedule = RATE_LIMIT_WAIT if limited else RETRY_WAIT
    # 抖动：避免几个线程同一秒一起醒来重试，再次撞上同一个限流窗口
    return schedule[min(attempt, len(schedule) - 1)] * random.uniform(0.8, 1.2)

def callModel(call, retries=3):
    """所有模型调用都走这里：先过门闸，429 时全局冷却后再重试。"""
    global _COOLDOWN_UNTIL
    for attempt in range(retries + 1):
        with _GATE:
            wait = _COOLDOWN_UNTIL - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                return call()
            except Exception as e:
                if attempt == retries:
                    raise
                limited = isRateLimited(e)
                delay = backoffSeconds(attempt, limited)
                if limited:
                    _COOLDOWN_UNTIL = time.time() + delay
        time.sleep(delay)

def eval_one(item):
    # 检索里的改写也是一次模型调用，必须过门闸，否则 4 线程全堵在检索就超额度了
    context = callModel(lambda: retrieve_context(item["q"]))
    generated = callModel(lambda: gen_chain.invoke({"question": item["q"], "context": context}))
    raw = callModel(lambda: judge_chain.invoke({
        "question": item["q"],
        "golden": item["answer"],
        "generated": generated,
        "context": context,
    }))
    try:
        verdict = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except Exception:
        raise ValueError(f"裁判输出解析失败: {raw[:200]}")
    return generated, verdict

def eval_generation(test_questions, max_workers=4):
    scores = {"correctness": [], "completeness": [], "faithfulness": []}
    failures = []
    records = []
    total = len(test_questions)
    start = time.time()

    def task(item):
        try:
            return item, *eval_one(item), None
        except Exception as e:
            return item, None, None, str(e)

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for item, generated, verdict, error in pool.map(task, test_questions):
            done += 1
            if error:
                records.append({"q": item["q"], "difficulty": item.get("difficulty"), "error": error})
                print(f"[{done}/{total}] 错误: {error[:80]} | {item['q'][:30]}")
                continue

            for k in scores:
                scores[k].append(verdict[k])

            records.append({
                "q": item["q"],
                "difficulty": item.get("difficulty"),
                "category": item.get("category"),
                "golden": item["answer"],
                "generated": generated,
                "correctness": verdict["correctness"],
                "completeness": verdict["completeness"],
                "faithfulness": verdict["faithfulness"],
                "reason": verdict["reason"],
            })

            # ③ 收集不合格项
            if min(verdict["correctness"], verdict["completeness"], verdict["faithfulness"]) < 2:
                failures.append({
                    "q": item["q"],
                    "difficulty": item.get("difficulty"),
                    "generated": generated[:200],
                    "golden": item["answer"][:200],
                    "reason": verdict["reason"],
                })

            marks = f"c={verdict['correctness']} p={verdict['completeness']} f={verdict['faithfulness']}"
            print(f"[{done}/{total}] {marks} | {item['q'][:30]}")

    n = len(scores["correctness"])
    elapsed = round(time.time() - start)
    print(f"\n样本数: {n}   总耗时: {elapsed}s ({elapsed / total:.1f}s/题, 并发{max_workers})")
    # 整批被限流打死时 n=0，指标全记 0：否则除零崩在这里，连失败明细都看不到
    if n:
        for k, v in scores.items():
            print(f"{k}: 平均 {sum(v)/n:.2f} / 2.0   满分率 {v.count(2)/n:.0%}")
    else:
        print("全部题目失败，指标记 0（原因见上方逐题错误）")

    print("\n=== 不合格明细 ===")
    for f in failures:
        print(f"[{f['difficulty']}] {f['q']}")
        print(f"  生成: {f['generated']}")
        print(f"  标准: {f['golden']}")
        print(f"  原因: {f['reason']}\n")

    # 逐题全量明细落盘（含通过项），控制台只打印汇总和不合格项
    report_path = Path(__file__).parent / f"eval_gen_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps({
        "sample_count": n,
        "elapsed_seconds": elapsed,
        "max_workers": max_workers,
        "disable_thinking": DISABLE_THINKING,
        "averages": {k: round(sum(v) / n, 2) for k, v in scores.items()} if n else {},
        "full_rates": {k: round(v.count(2) / n, 4) for k, v in scores.items()} if n else {},
        "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n逐题明细已保存: {report_path}")

    return scores, failures

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    parser.add_argument("--workers", type=int, default=4,
                        help="线程数；真正的模型在途请求由 MAX_INFLIGHT=4 门闸卡住，调大此项不会放大并发")
    args = parser.parse_args()

    # test_questions.json 尚未准备，回退到同目录的 rag_testset.json（q/answer/difficulty 字段兼容）
    testset_path = Path(__file__).parent / "test_questions.json"
    if not testset_path.exists():
        testset_path = Path(__file__).parent / "rag_testset.json"
    with open(testset_path, encoding="utf-8") as f:
        test_questions = json.load(f)
    if args.limit > 0:
        test_questions = test_questions[:args.limit]

    eval_generation(test_questions, args.workers)