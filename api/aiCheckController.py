from fastapi import APIRouter, UploadFile
from fastapi.params import File

from schema.schemas import Response
from service.aiCheckService import (
    getCheckResult,
    getProjectInfo,
    getRules,
    listCheckResults,
    listProjectInfo,
    resetCheckResult,
    saveCheckFile,
    saveProjectInfo,
    updateRuleEnabled,
)
from service.aiCheckCoreService import startCheck

router = APIRouter(prefix="/api/v1/ai-check", tags=["AI质检"])


# 上游推送项目结构化数据（project_id 为唯一键，重复推送更新）
@router.post("/projects")
async def push_project_info(payload: dict):
    try:
        return saveProjectInfo(payload)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


@router.get("/projects")
def get_projects(page: int = 1, page_size: int = 10):
    try:
        return listProjectInfo(page, page_size)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    try:
        return getProjectInfo(project_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 上游推送披露 PDF：保存文件并写入质检结果状态表（默认未质检）
@router.post("/files")
async def push_check_file(project_id: str, file: UploadFile = File(...)):
    try:
        return await saveCheckFile(project_id, file)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 质检结果状态列表（默认每项目最新一条；latest_only=false 查历史）
@router.get("/results")
def get_check_results(page: int = 1, page_size: int = 10, status: str = None,
                      project_id: str = None, latest_only: bool = True):
    try:
        return listCheckResults(page, page_size, status, project_id, latest_only)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 单条校验记录明细（含逐字段比对结果）
@router.get("/results/{result_id}")
def get_check_result(result_id: int):
    try:
        return getCheckResult(result_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 手动触发校验：异步执行，前端轮询明细接口取进度
@router.post("/results/{result_id}/check")
def trigger_check(result_id: int):
    try:
        return startCheck(result_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 重置卡在「校验中」的记录（进程中断遗留）
@router.post("/results/{result_id}/reset")
def reset_check_result(result_id: int):
    try:
        return resetCheckResult(result_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 校验规则列表（全局一套，业务可开关）
@router.get("/rules")
def get_check_rules():
    try:
        return getRules()
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 更新规则启用状态（金额规则可同时提交容差 tolerance）
@router.put("/rules/{rule_id}/enabled")
def set_rule_enabled(rule_id: int, enabled: int, tolerance: float = None):
    try:
        return updateRuleEnabled(rule_id, enabled, tolerance)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response
