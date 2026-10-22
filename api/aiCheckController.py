from fastapi import APIRouter, UploadFile
from fastapi.params import File

from schema.schemas import Response
from service.aiCheckService import (
    getProjectInfo,
    getRules,
    listCheckResults,
    listProjectInfo,
    saveCheckFile,
    saveProjectInfo,
    updateRuleEnabled,
)

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


# 质检结果状态列表（含文件信息与校验状态）
@router.get("/results")
def get_check_results(page: int = 1, page_size: int = 10):
    try:
        return listCheckResults(page, page_size)
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
