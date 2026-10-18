

import asyncio

from fastapi import APIRouter, UploadFile
from fastapi.params import File
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agent.rag.initRag import getVector
from model.initDataBase import SessionLocal
from schema.schemas import Response
from service.evalService import (
    getEvalDetailPage,
    getEvalRun,
    getEvalRuns,
    getGenRun,
    getGenRuns,
    getTestsetSize,
    runEvaluation,
    runRetrievalEval,
    startGenerationEval,
    startGenerationRerun,
)
from service.ragFileService import (
    FileToVector,
    countDocuments,
    deleteDocument,
    downloadDocument,
    getDocuments,
    uploadFileAndSaveDir,
)

router = APIRouter(prefix="/api/v1", tags=["rag文件"])   # 统一前缀 + 文档分组


@router.get("/health")
def health():
    vector = getVector()

    response = Response()
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.code = "5000"
        response.message = "数据库连接失败"
        return response

    if not vector:
        response.code = "5000"
        response.message = "链接超时"
    return response


# 上传文档
@router.post("/documents")
async def upload_document(title:str,chunk_size:int,chunk_overlap:int,file: UploadFile = File(...)):
    try:
        rep = await uploadFileAndSaveDir(title,file)
        chunk_count = await FileToVector(chunk_size,chunk_overlap,rep.ID,rep.FILE_PATH,rep.FILE_TYPE)
    except Exception as e:
        # service抛的业务错误（类型不支持/超限/重复上传）转成统一响应，不能走500
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response

    response = Response()

    data = {"document_id": rep.ID,"title": rep.FILE_NAME,"chunk_count":chunk_count,"status":"success"}
    response.data = data
    return response


# 获取文档列表
@router.get("/documents")
async def get_documents(page:int = 1,page_size:int = 10,keyword:str = ""):
    return getDocuments(page,page_size,keyword)

#  下载文档
@router.get("/documents/{document_id}")
async def get_document(document_id: str):
    try:
        return downloadDocument(document_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response



@router.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    try:
        return deleteDocument(document_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response

@router.get("/kb/stats")
def getKdStats():
    return countDocuments()


# 运行 RAG 评测（评测集见 tests/rag_testset.json，条数以 /eval/testset/size 为准）
# mode=full 跑 LLM 问答 + 检索指标（每题一次生成，全量 68 题需几十分钟，阻塞本接口）；
# mode=retrieval 只查向量库算 recall@k/MRR（改写命中缓存后秒级），用 to_thread 避免阻塞事件循环
@router.post("/eval/run")
async def run_eval(limit: int = 0, top_k: int = 6, mode: str = "full"):
    try:
        if mode == "retrieval":
            return await asyncio.to_thread(runRetrievalEval, limit, top_k)
        return await runEvaluation(limit, top_k)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 测试集条数（前端"评测条数上限"据此动态渲染，limit=0 表示全量）
@router.get("/eval/testset/size")
def testset_size():
    try:
        return {"count": getTestsetSize()}
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 评测历史列表（不含每题明细），run_type 可选 full / retrieval，为空返回全部
# 分页默认 30 条（可选 50/100）；page_size<=0 时返回全部，供折线图拉取趋势数据
@router.get("/eval/runs")
def list_eval_runs(run_type: str = "", page: int = 1, page_size: int = 30):
    try:
        return getEvalRuns(run_type, page, page_size)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 单次评测详情（含每题明细）
@router.get("/eval/runs/{run_id}")
def get_run(run_id: int):
    try:
        return getEvalRun(run_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 跨评测汇总的逐题排名明细：所有评测的记录展平，按评测时间倒序分页（默认10条，可选20/30）
@router.get("/eval/detail")
def list_eval_detail(page: int = 1, page_size: int = 10):
    try:
        return getEvalDetailPage(page, page_size)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 发起生成评估：逐题走生产问答链路生成答案 + 三维裁判打分。
# 全量约 30 分钟，故只建记录后立即返回 run_id，评测在后台线程里跑；
# 进度与结果都通过 /eval/gen/runs/{id} 轮询（status=running/success/failed）
@router.post("/eval/gen/run")
def run_gen_eval(limit: int = 0, top_k: int = 6):
    try:
        return startGenerationEval(limit, top_k)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 重跑当前批次的指定题（indexes 为逗号分隔的题号）：结果覆盖回原批次，不新建批次
# 与 /eval/gen/run 一样后台跑，进度随 /eval/gen/runs/{id} 的 rerun 字段轮询
@router.post("/eval/gen/runs/{run_id}/rerun")
def rerun_gen_eval(run_id: int, indexes: str = ""):
    try:
        return startGenerationRerun(run_id, indexes)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 生成评估历史列表（不含每题明细），分页默认 30 条（可选 50/100）
@router.get("/eval/gen/runs")
def list_gen_runs(page: int = 1, page_size: int = 30):
    try:
        return getGenRuns(page, page_size)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 单次生成评估详情（含每题明细）；status=running 时同时用于轮询进度
@router.get("/eval/gen/runs/{run_id}")
def get_gen_run(run_id: int):
    try:
        return getGenRun(run_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response
