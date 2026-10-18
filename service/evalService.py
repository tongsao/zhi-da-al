import asyncio
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import func, select, update

from agent.initChatModel import getModel
from model.initDataBase import db_session
from model.models import evalGenRun, evalRun
from service.chatService import deleteHistoryMessage, format_docs, generateAnswer
from service.ragFileService import hybridRetrieve

TESTSET_PATH = Path(__file__).resolve().parent.parent / "tests" / "rag_testset.json"
# 评测专用会话号段，避免污染真实聊天记录；每条跑完即删
CONV_ID_BASE = 990001
# 检索评估线程数：检索只有一次改写是模型调用，轻量，15 路实测无 429
RETRIEVAL_WORKERS = 15
# 生成评估线程数：重型生成请求，qwen 端点实测 15 路会把请求排队挂死到超时，8 为用户指定值
GEN_WORKERS = 8
# 门闸取两者较大值，不主动压并发；留着只防意外叠加（线上问答不打门闸，不占这个额度）
MAX_INFLIGHT = 15


def judgeAnswer(answer: str, keywords: list):
    hits = [k for k in keywords if k in answer]
    return bool(hits), hits


def loadTestset(limit: int) -> list:
    items = json.loads(TESTSET_PATH.read_text(encoding="utf-8"))
    if limit and limit < len(items):
        items = items[:limit]
    return items


def getTestsetSize() -> int:
    """测试集当前条数，前端评测条数上限据此动态渲染，避免写死。"""
    return len(json.loads(TESTSET_PATH.read_text(encoding="utf-8")))


def rankChunks(chunks: list, keywords: list) -> dict:
    """[rerank] 在已检索到的块里找首个相关块的排名（0=未召回）。

    相关块两种口径都算：rank_any=块命中任一关键词，rank_all=块包含全部关键词。
    """
    if not keywords:
        # 「无答案」题没有可命中的目标块，两口径都记未召回（指标统计时按 judgeable 剔除）
        # 不能走下面的循环：hit_count==len(keywords) 恒为真，rank_all 会被误判成第 1 名
        return {"ranks": {"rank_any": 0, "rank_all": 0}, "chunk_previews": [doc.page_content[:60] for doc in chunks]}

    rank_any, rank_all = 0, 0
    for rank, doc in enumerate(chunks, start=1):
        hit_count = sum(1 for k in keywords if k in doc.page_content)
        if rank_any == 0 and hit_count > 0:
            rank_any = rank
        if rank_all == 0 and hit_count == len(keywords):
            rank_all = rank

    return {
        "ranks": {"rank_any": rank_any, "rank_all": rank_all},
        "chunk_previews": [doc.page_content[:60] for doc in chunks],
    }


def retrieveRanks(question: str, keywords: list, top_k: int) -> dict:
    """[rerank] 检索 top_k 块再排名，链路与 chatService 相同：hybridRetrieve 双路召回 + bge 重排。"""
    return rankChunks(hybridRetrieve(question, top_k), keywords)


def saveEvalRun(run_type: str, top_k: int, results: list, extra: dict) -> tuple:
    """从每题 ranks 汇总 recall@k / MRR（两种口径），连同 full 指标一起存库。

    「无答案」题（judgeable=False）没有可命中的目标块，不进指标分母；
    total 字段仍记批次全量，供前端显示评测条数。
    返回 (run_id, recall/mrr 指标字典)。
    """
    judgeable = [r for r in results if r.get("judgeable", True)]
    total = len(judgeable)
    metrics = {}
    for mode in ("any", "all"):
        ranks = [r["ranks"][f"rank_{mode}"] for r in judgeable]
        hits = sum(1 for rank in ranks if rank > 0)
        metrics[f"recall_{mode}"] = round(hits / total, 4) if total else 0
        metrics[f"mrr_{mode}"] = round(sum(1 / rank for rank in ranks if rank > 0) / total, 4) if total else 0

    row = evalRun(run_type=run_type, top_k=top_k, total=total, **metrics)
    for key, value in extra.items():
        setattr(row, key, value)

    with db_session() as db:
        db.add(row)
        db.commit()
        run_id = row.id

    return run_id, metrics


def bucketRanks(results: list, key: str) -> dict:
    """检索类指标按难度/类别分组（口径=all：块含全部关键词才算召回）。"""
    bucket = {}
    for r in results:
        if not r.get("judgeable", True):
            continue
        stat = bucket.setdefault(r[key], {"total": 0, "passed": 0})
        stat["total"] += 1
        if r["ranks"]["rank_all"] > 0:
            stat["passed"] += 1
    return bucket


def runRetrievalEval(limit: int, top_k: int) -> dict:
    """仅检索评测：逐题双路召回+重排，算 recall@k 和 MRR。

    全程只有查询改写一次模型调用（命中改写缓存后就是纯本地计算），
    但串行跑只占用一半在途额度，所以按 RETRIEVAL_WORKERS 并行——每题结果与串行完全一致。
    """
    items = loadTestset(limit)

    def task(indexed):
        i, item = indexed
        # 走 callModel：冷缓存时改写是每题一次的模型调用，并行不过门闸就会撞 429 把整批判死
        ret = callModel(lambda: retrieveRanks(item["q"], item["answer_contains"], top_k))
        return i, item, ret

    results = []
    with ThreadPoolExecutor(max_workers=RETRIEVAL_WORKERS) as pool:
        for i, item, ret in pool.map(task, enumerate(items)):
            results.append({
                "index": i + 1,
                "q": item["q"],
                "category": item["category"],
                "difficulty": item["difficulty"],
                "judgeable": bool(item.get("answer_contains")),
                **ret,
            })
            print(f"[eval-retrieval {i + 1}/{len(items)}] rank_any={ret['ranks']['rank_any'] or '-'} rank_all={ret['ranks']['rank_all'] or '-'} | {item['q']}")

    run_id, metrics = saveEvalRun("retrieval", top_k, results, {
        "by_difficulty": bucketRanks(results, "difficulty"),
        "by_category": bucketRanks(results, "category"),
        "detail": results,
    })

    return {"run_id": run_id, "total": len(results), "top_k": top_k, **metrics, "results": results}


async def runEvaluation(limit: int, top_k: int):
    """完整评测：每题调 LLM 问答算 hit_rate，同时算检索类指标，结果一起存库。

    在途额度远大于 1，逐题 await 只占用一个名额，所以在途按 GEN_WORKERS 并行；
    每题一个独立会话（conv_id 互不相同、跑完即删），并行不改动任何一题的生成结果。
    """
    items = loadTestset(limit)
    gate = asyncio.Semaphore(GEN_WORKERS)

    def evalOne(i, item):
        conv_id = CONV_ID_BASE + i
        start = time.time()
        answer, error = "", None
        try:
            # 过 callModel：单次生成可达百秒，429 必须重试，否则整题记 0 分把分数拉低
            answer, chunks = callModel(lambda: generateAnswer(item["q"], conv_id, top_k))
        except Exception as e:
            # 生成失败也要算检索指标，补一次检索（只走失败题），保证 recall/MRR 分母不缺
            chunks = hybridRetrieve(item["q"], top_k)
            error = str(e)
        latency_ms = round((time.time() - start) * 1000)
        passed, hits = judgeAnswer(answer, item["answer_contains"])

        # 检索块复用生成链路刚取到的那一份，不再检索第二遍（同样参数，结果一致）
        ret = rankChunks(chunks, item["answer_contains"])
        deleteHistoryMessage(str(conv_id))

        return {
            "index": i + 1,
            "q": item["q"],
            "answer": item["answer"],
            "category": item["category"],
            "difficulty": item["difficulty"],
            "judgeable": bool(item.get("answer_contains")),
            "model_answer": answer,
            "hit_keywords": hits,
            "passed": passed,
            "latency_ms": latency_ms,
            "error": error,
            **ret,
        }

    async def runOne(i, item):
        async with gate:
            return await asyncio.to_thread(evalOne, i, item)

    # gather 保序，results 顺序与串行版逐条一致
    results = list(await asyncio.gather(*(runOne(i, item) for i, item in enumerate(items))))

    total = len(results)
    # hit_rate 分母只算可判题：「无答案」题没有关键词可比对，passed 恒为 False，计入会永久拉低
    judgeable = [r for r in results if r["judgeable"]]
    passed_count = sum(1 for r in judgeable if r["passed"])
    hit_rate = passed_count / len(judgeable) if judgeable else 0
    avg_latency_ms = round(sum(r["latency_ms"] for r in results) / total) if total else 0

    by_difficulty = {}
    by_category = {}
    for r in judgeable:
        for bucket, key in ((by_difficulty, "difficulty"), (by_category, "category")):
            stat = bucket.setdefault(r[key], {"total": 0, "passed": 0})
            stat["total"] += 1
            stat["passed"] += r["passed"]

    run_id, metrics = saveEvalRun("full", top_k, results, {
        "passed": passed_count,
        "hit_rate": hit_rate,
        "avg_latency_ms": avg_latency_ms,
        "by_difficulty": by_difficulty,
        "by_category": by_category,
        "detail": results,
    })

    return {
        "run_id": run_id,
        "total": total,
        "passed": passed_count,
        "hit_rate": hit_rate,
        "avg_latency_ms": avg_latency_ms,
        "top_k": top_k,
        **metrics,
        "by_difficulty": by_difficulty,
        "by_category": by_category,
        "results": results,
    }


# ===== 生成评估：逐题走生产链路问答 + 三维裁判打分 =====

# 裁判口径与 tests/run_eval_data.py 第10轮基线逐字一致，两处必须同步改，否则分数不可比
JUDGE_PROMPT = ChatPromptTemplate.from_template("""你是证券合规领域的评审专家，请评估【系统生成答案】的质量。

【问题】{question}
【检索到的资料】（判定 faithfulness 的唯一依据）
{context}
【标准答案】（判定 correctness / completeness 的依据，仅列核心要点）
{golden}
【系统生成答案】
{generated}
【引用一致性检查】（并入 faithfulness）
检查生成答案中出现的资料名称、条号格式是否与【检索到的资料】一致：
- 出现资料中不存在的规范/制度名称 → faithfulness 判 0
- 条号被加书名号（如《第五十三条》）→ faithfulness 最多 1 分
- 引用了未检索到的条号 → faithfulness 最多 1 分

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

# 裁判任务简单，固定关思考：判分更稳定，也省掉每题数十秒的思考开销
judge_chain = JUDGE_PROMPT | getModel().bind(temperature=0, extra_body={"thinking": {"type": "disabled"}}) | StrOutputParser()

RETRY_WAIT = (10, 30)
# 429 可能是账户在途超限（由门闸压住），也可能是服务端过载（通常几十秒自愈）。
# 短退避三次全落在同一个过载窗口里必然整题判死，所以 429 单独用更长的退避
RATE_LIMIT_WAIT = (20, 60)
_GATE = threading.Semaphore(MAX_INFLIGHT)
# 吃到 429 说明额度已被占满（或平台在过载），其他线程继续发只会继续吃；
# 所以退避是全局的：命中后所有线程一起等到冷却结束
_COOLDOWN_UNTIL = 0.0


def isRateLimited(exc) -> bool:
    return getattr(exc, "status_code", None) == 429 or "429" in str(exc)


def backoffSeconds(attempt: int, limited: bool) -> float:
    schedule = RATE_LIMIT_WAIT if limited else RETRY_WAIT
    # 抖动：避免几个线程同一秒一起醒来重试，再次撞上同一个限流窗口
    return schedule[min(attempt, len(schedule) - 1)] * random.uniform(0.8, 1.2)


def callModel(call, retries=3):
    """模型调用统一入口：先过门闸，429 全局冷却后重试。生成与裁判两条调用都要走，只包一条照样整题失败。"""
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
        # 出闸后再等：攥着并发名额睡觉会把其他线程一起卡死
        time.sleep(delay)


# 重跑进度只存内存：批次行要一直保持 success（它就是这一批的成果），
# 不能拿它的 done/total 记重跑进度，所以另开一份状态随详情接口返回给前端轮询
RERUN_STATE = {}


def ensureIdle():
    """同一时间只允许一个评测在跑：单次评测已把在途额度（MAX_INFLIGHT）用满，两批叠加必然触发 429。"""
    with db_session() as db:
        running = db.execute(select(evalGenRun).where(evalGenRun.status == "running")).scalars().first()
    if running:
        raise ValueError(f"已有评测进行中（#{running.id}，进度 {running.done}/{running.total}），请等它结束后再发起")
    if RERUN_STATE:
        raise ValueError(f"批次 #{next(iter(RERUN_STATE))} 正在重跑，请等它结束后再发起")


def updateGenRun(run_id: int, **values):
    with db_session() as db:
        db.execute(update(evalGenRun).where(evalGenRun.id == run_id).values(**values))
        db.commit()


def buildGenRecord(index: int, item: dict, generated, verdict, error) -> dict:
    """单题明细；失败题只留问题与错误原因，没有分数（统计时不计入分母）。"""
    record = {
        "index": index,
        "q": item["q"],
        "difficulty": item.get("difficulty"),
        "category": item.get("category"),
    }
    if error:
        return {**record, "error": error}
    return {
        **record,
        "golden": item["answer"],
        "generated": generated,
        "correctness": verdict["correctness"],
        "completeness": verdict["completeness"],
        "faithfulness": verdict["faithfulness"],
        "reason": verdict["reason"],
    }


def computeGenStats(records: list) -> dict:
    """从明细算三维均分与满分率，分母固定是明细条数（=批次题数）。

    失败题（限流/超时）没有分数，按 0 分计入分母，不能把它们剔出去：
    剔出去等于失败反而把满分率抬上去，45 题里挂掉 2 题会算出 43/43=100%。
    """
    if not records:
        return {}
    stats = {}
    for key in ("correctness", "completeness", "faithfulness"):
        values = [r.get(key) or 0 for r in records]
        stats[f"{key}_avg"] = round(sum(values) / len(values), 2)
        stats[f"{key}_full_rate"] = round(values.count(2) / len(values), 4)
    return stats


def evalGenerationOne(index: int, question: str, golden: str, top_k: int) -> tuple:
    """单题：生产链路生成答案 → 裁判打分。跑完即清会话，不污染真实聊天记录。"""
    conv_id = CONV_ID_BASE + index
    try:
        generated, chunks = callModel(lambda: generateAnswer(question, conv_id, top_k))
        raw = callModel(lambda: judge_chain.invoke({
            "question": question,
            "golden": golden,
            "generated": generated,
            "context": format_docs(chunks),  # 键名与 JUDGE_PROMPT 里的 {context} 对齐
        }))
        return generated, json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    finally:
        deleteHistoryMessage(str(conv_id))


def runGenerationEval(run_id: int, limit: int, top_k: int):
    """后台线程体：逐题生成+打分，每跑完一题把进度写回库（前端轮询它）。

    生成链与 /qa 页面同源（chatService.generateAnswer），所以这里的分数就是线上效果。
    """
    items = loadTestset(limit)
    records = []
    start = time.time()

    def task(indexed):
        index, item = indexed
        try:
            generated, verdict = evalGenerationOne(index, item["q"], item["answer"], top_k)
            return index, item, generated, verdict, None
        except Exception as e:
            return index, item, None, None, str(e)

    try:
        done = 0
        with ThreadPoolExecutor(max_workers=GEN_WORKERS) as pool:
            for index, item, generated, verdict, error in pool.map(task, list(enumerate(items))):
                done += 1
                records.append(buildGenRecord(index + 1, item, generated, verdict, error))
                print(f"[eval-gen {done}/{len(items)}] {item['q'][:30]} {error or ''}")
                updateGenRun(run_id, done=done)
    except Exception as e:
        # 整批级失败（如测试集读取失败）；单题失败已在上面按条记录，不中断整轮
        updateGenRun(run_id, status="failed", error_msg=str(e))
        return

    if not any(r.get("correctness") is not None for r in records):
        updateGenRun(run_id, status="failed", error_msg="全部题目评测失败，无有效样本")
        return

    updateGenRun(run_id, status="success", elapsed_seconds=round(time.time() - start), detail=records, **computeGenStats(records))


def startGenerationEval(limit: int, top_k: int) -> dict:
    """建 running 记录后立即返回，评测本身在后台线程里跑。

    全量几十题逐题开思考要跑好几分钟，占着 HTTP 请求必然超时，所以进度写库、前端轮询。
    """
    ensureIdle()

    total = len(loadTestset(limit))
    row = evalGenRun(top_k=top_k, total=total, done=0, status="running", workers=GEN_WORKERS)
    with db_session() as db:
        db.add(row)
        db.commit()
        run_id = row.id

    threading.Thread(target=runGenerationEval, args=(run_id, limit, top_k), daemon=True).start()
    return {"run_id": run_id, "total": total, "top_k": top_k, "status": "running"}


def parseIndexes(indexes: str) -> list:
    """前端传逗号分隔的题号串（axios 对数组参数会补 [] 后缀，与 FastAPI 的 list 参数对不上）。

    去重后按题号排序，重跑结果覆盖回原明细时顺序稳定。
    """
    try:
        parsed = sorted({int(x) for x in indexes.split(",") if x.strip()})
    except ValueError:
        raise ValueError("题号格式不对，应为逗号分隔的数字")
    if not parsed:
        raise ValueError("请先勾选要重跑的问题")
    return parsed


def rerunSource(record: dict) -> dict:
    """重跑要用的题面与标准答案。

    优先用批次里存下的，保证重跑和同批其余题是同一把尺子（测试集后来被改也不影响可比性）；
    这题在批次里本来就失败过（没存下 golden）时才回测试集按题号补，并用题面文本核对。
    """
    if record.get("golden") is not None:
        return {
            "q": record["q"], "answer": record["golden"],
            "difficulty": record.get("difficulty"), "category": record.get("category"),
        }

    item = loadTestset(0)[record["index"] - 1]
    if item["q"] != record["q"]:
        raise ValueError(f"第 {record['index']} 题在批次里失败过，且测试集题面已改动，无法重跑")
    return item


def runGenerationRerun(run_id: int, records: list, top_k: int, targets: list):
    """后台线程体：只跑指定题，按题号覆盖回原明细，再重算统计写回同一批次。"""
    by_index = {r["index"]: r for r in records}
    state = RERUN_STATE[run_id]

    def task(index):
        old = by_index[index]
        try:
            item = rerunSource(old)
            generated, verdict = evalGenerationOne(index, item["q"], item["answer"], top_k)
            return index, old, item, generated, verdict, None
        except Exception as e:
            return index, old, None, None, None, str(e)

    try:
        with ThreadPoolExecutor(max_workers=GEN_WORKERS) as pool:
            for index, old, item, generated, verdict, error in pool.map(task, targets):
                # 重跑失败就覆盖成失败记录：与整批口径一致，也避免旧分数被误当成这次重跑的结果
                by_index[index] = buildGenRecord(index, item or old, generated, verdict, error)
                state["done"] += 1
                if error:
                    state["failed"].append(index)
                print(f"[eval-rerun {state['done']}/{state['total']}] #{index} {old['q'][:30]} {error or ''}")

        merged = [by_index[r["index"]] for r in records]  # 保持原明细顺序
        updateGenRun(run_id, detail=merged, **computeGenStats(merged))
    finally:
        RERUN_STATE.pop(run_id, None)


def startGenerationRerun(run_id: int, indexes: str) -> dict:
    """只重跑指定题，结果覆盖回原批次，不新建批次（新批次只能由「开始评测」产生）。"""
    ensureIdle()

    with db_session() as db:
        row = db.execute(select(evalGenRun).where(evalGenRun.id == run_id)).scalars().first()
    if not row:
        raise ValueError("生成评估记录不存在")
    if row.status != "success":
        raise ValueError("该批次还没跑成功，不能重跑")

    targets = parseIndexes(indexes)
    known = {r["index"] for r in (row.detail or [])}
    missing = [i for i in targets if i not in known]
    if missing:
        raise ValueError(f"批次 #{run_id} 的明细里没有第 {missing} 题")

    RERUN_STATE[run_id] = {"done": 0, "total": len(targets), "status": "running", "failed": []}
    threading.Thread(
        target=runGenerationRerun, args=(run_id, row.detail, row.top_k, targets), daemon=True
    ).start()
    return {"run_id": run_id, "total": len(targets), "indexes": targets, "top_k": row.top_k}


def getGenRuns(page: int = 1, page_size: int = 30) -> dict:
    with db_session() as db:
        query = select(evalGenRun).order_by(evalGenRun.id.desc())
        total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        rows = db.execute(query.limit(page_size).offset((page - 1) * page_size)).scalars().all()

    return {"total": total, "page": page, "page_size": page_size, "items": [runToDict(row) for row in rows]}


def getGenRun(run_id: int) -> dict:
    with db_session() as db:
        row = db.execute(select(evalGenRun).where(evalGenRun.id == run_id)).scalars().first()
    if not row:
        raise ValueError("生成评估记录不存在")
    data = runToDict(row, with_detail=True)
    # 重跑不落库，进度随详情一起返回，前端刷新页面也能接着显示
    data["rerun"] = RERUN_STATE.get(run_id)
    return data


def failStaleGenRuns():
    """后台线程随进程消失，启动时把上次残留的 running 记录标失败，否则它会一直占着「进行中」挡新评测。"""
    with db_session() as db:
        result = db.execute(
            update(evalGenRun).where(evalGenRun.status == "running")
            .values(status="failed", error_msg="服务重启导致中断")
        )
        db.commit()
        return result.rowcount


def runToDict(row, with_detail: bool = False) -> dict:
    # 从行本身取表结构，evalRun 与 evalGenRun 共用这一个转换
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    if not with_detail:
        data.pop("detail")
    return data


def getEvalRuns(run_type: str = "", page: int = 1, page_size: int = 30) -> dict:
    """评测历史列表（不含每题明细），run_type 为空返回全部类型。

    page_size<=0 表示不分页返回全部，供折线图拉取全量趋势数据（图表不随表格翻页变化）。
    """
    with db_session() as db:
        query = select(evalRun).order_by(evalRun.id.desc())
        if run_type:
            query = query.where(evalRun.run_type == run_type)

        total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        if page_size > 0:
            query = query.limit(page_size).offset((page - 1) * page_size)
        rows = db.execute(query).scalars().all()

    return {"total": total, "page": page, "page_size": page_size, "items": [runToDict(row) for row in rows]}


def getEvalRun(run_id: int) -> dict:
    with db_session() as db:
        row = db.execute(select(evalRun).where(evalRun.id == run_id)).scalars().first()
    if not row:
        raise ValueError("评测记录不存在")
    return runToDict(row, with_detail=True)


def getEvalDetailPage(page: int, page_size: int) -> dict:
    """跨评测汇总的逐题排名明细：所有评测的 detail 展平，按评测时间倒序分页。"""
    with db_session() as db:
        rows = db.execute(
            select(evalRun).order_by(evalRun.created_at.desc(), evalRun.id.desc())
        ).scalars().all()

    flat = []
    for row in rows:
        for d in (row.detail or []):
            flat.append({
                "run_id": row.id,
                "run_type": row.run_type,
                "top_k": row.top_k,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "index": d.get("index"),
                "q": d.get("q"),
                "category": d.get("category"),
                "difficulty": d.get("difficulty"),
                "ranks": d.get("ranks", {}),
                "chunk_previews": d.get("chunk_previews", []),
            })

    start = (page - 1) * page_size
    return {"total": len(flat), "page": page, "page_size": page_size, "items": flat[start:start + page_size]}
