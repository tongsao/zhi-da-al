import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import UploadFile
from sqlalchemy import func, select

from model.initDataBase import db_session
from model.models import zd_ai_check_result, zd_ai_check_rule, zd_project_info

load_dotenv()

UPLOAD_FILE_PATH = os.getenv("UPLOAD_FILE_PATH")
FILE_CHUNK_SIZE = int(os.getenv("FILE_CHUNK_SIZE"))
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE"))
ALLOWED_FILE_EXTENSIONS = json.loads(os.getenv("ALLOWED_FILE_EXTENSIONS"))

uploadDir = Path(UPLOAD_FILE_PATH)

# 开发预置的校验规则：字段名 -> (中文名, 比对方式, 默认容差)。比对逻辑后续校验功能实现时使用
DEFAULT_RULES = {
    "disclosure_date": ("披露日期", "quarter_match", None),
    "amount": ("金额", "amount_diff", 0.01),
    "discloser": ("披露人", "name_normalized", None),
    "title": ("公告标题", "string_exact", None),
}


# ---------- 项目信息 ----------
def saveProjectInfo(payload: dict):
    """上游推送结构化数据：以 project_id 为唯一键，存在则更新，不存在则插入。"""
    project_id = payload.get("project_id")
    if not project_id:
        raise Exception("project_id 必填")

    month = payload.get("month")
    quarter_type = payload.get("quarter_type")
    amount = payload.get("amount")
    # 上游接口是信任边界，非法的年/月/季度/金额在写入前拦截，避免脏数据进比对基准
    if month is not None and month not in range(1, 13):
        raise Exception("month 必须在 1-12 之间")
    if quarter_type is not None and quarter_type not in (1, 2, 3, 4):
        raise Exception("quarter_type 必须是 1/2/3/4")
    if amount is not None and amount < 0:
        raise Exception("amount 必须为非负数值")

    with db_session() as db:
        project = db.execute(
            select(zd_project_info).where(zd_project_info.project_id == project_id)
        ).scalars().first()

        if project:
            for field in ("project_name", "year", "month", "quarter_type", "amount", "discloser"):
                if payload.get(field) is not None:
                    setattr(project, field, payload[field])
        else:
            project = zd_project_info(project_id=project_id, **{k: v for k, v in payload.items() if k != "project_id"})
            db.add(project)
        db.commit()
        db.refresh(project)
    return {"project_id": project_id}


def getProjectInfo(project_id: str):
    with db_session() as db:
        project = db.execute(
            select(zd_project_info).where(zd_project_info.project_id == project_id)
        ).scalars().first()
    if not project:
        raise Exception("项目不存在")
    return _project_to_dict(project)


def listProjectInfo(page: int, page_size: int):
    with db_session() as db:
        total = db.execute(select(func.count()).select_from(zd_project_info)).scalar()
        query = (
            select(zd_project_info)
            .order_by(zd_project_info.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        projects = db.execute(query).scalars().all()
    return {"total": total, "items": [_project_to_dict(p) for p in projects]}


def _project_to_dict(project):
    return {
        "project_id": project.project_id,
        "project_name": project.project_name,
        "year": project.year,
        "month": project.month,
        "quarter_type": project.quarter_type,
        "amount": project.amount,
        "discloser": project.discloser,
        "created_at": project.created_at.strftime("%Y-%m-%d %H:%M:%S") if project.created_at else None,
    }


# ---------- 文件推送 ----------
async def saveCheckFile(project_id: str, file: UploadFile):
    """上游推送披露 PDF：保存文件本体，并写入一条质检记录（默认未质检）。

    与 ragFileService.uploadFileAndSaveDir 保持同一套保存逻辑：按扩展名校验、
    按大小校验、分块写盘。同名重复推送视为修正重推，始终生成新记录，
    历史记录全部保留（自动复检在校验功能实现时接入）。
    """
    uploadDir.mkdir(parents=True, exist_ok=True)
    fileName = file.filename
    filePath = uploadDir / fileName
    ext = Path(fileName).suffix.lower().lstrip(".")
    if ext not in ALLOWED_FILE_EXTENSIONS:
        raise Exception(f"不支持的文件类型：{ext}")
    if file.size > MAX_FILE_SIZE:
        raise Exception("文件大小超过最大限制")

    with open(filePath, "wb") as f:
        while chunk := await file.read(FILE_CHUNK_SIZE):
            f.write(chunk)

    with db_session() as db:
        result = zd_ai_check_result(
            project_id=project_id,
            file_name=fileName,
            file_path=str(filePath),
            file_type=ext,
            status="pending",
        )
        # 同名文件视为修正重推：标记复检来源为最近一条同名记录，历史保留（校验由业务手动触发）
        latest_same_name = db.execute(
            select(zd_ai_check_result)
            .where(zd_ai_check_result.file_name == fileName)
            .order_by(zd_ai_check_result.id.desc())
            .limit(1)
        ).scalars().first()
        if latest_same_name:
            result.recheck_from = latest_same_name.id
        db.add(result)
        db.commit()
        db.refresh(result)
    return {"result_id": result.id, "file_name": fileName, "status": result.status}


def listCheckResults(page: int, page_size: int):
    with db_session() as db:
        total = db.execute(select(func.count()).select_from(zd_ai_check_result)).scalar()
        query = (
            select(zd_ai_check_result)
            .order_by(zd_ai_check_result.create_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        results = db.execute(query).scalars().all()
    return {"total": total, "items": [_result_to_dict(r) for r in results]}


def _result_to_dict(result):
    return {
        "result_id": result.id,
        "project_id": result.project_id,
        "file_name": result.file_name,
        "file_path": result.file_path,
        "file_type": result.file_type,
        "status": result.status,
        "check_detail": result.check_detail,
        "recheck_from": result.recheck_from,
        "error_msg": result.error_msg,
        "create_date": result.create_date.strftime("%Y-%m-%d %H:%M:%S") if result.create_date else None,
        "update_date": result.update_date.strftime("%Y-%m-%d %H:%M:%S") if result.update_date else None,
    }


# ---------- 校验规则 ----------
def initRules():
    """开发预置规则入库（幂等）：已有记录不重复插入，仅补缺失字段。"""
    with db_session() as db:
        existing = db.execute(select(zd_ai_check_rule.field_name)).scalars().all()
        for field_name, (label, compare_type, tolerance) in DEFAULT_RULES.items():
            if field_name not in existing:
                db.add(zd_ai_check_rule(
                    field_name=field_name,
                    field_label=label,
                    compare_type=compare_type,
                    tolerance=tolerance,
                    enabled=1,
                ))
        db.commit()


def getRules():
    with db_session() as db:
        rules = db.execute(select(zd_ai_check_rule).order_by(zd_ai_check_rule.id)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "field_name": r.field_name,
                "field_label": r.field_label,
                "compare_type": r.compare_type,
                "tolerance": float(r.tolerance) if r.tolerance is not None else None,
                "enabled": r.enabled,
            }
            for r in rules
        ]
    }


def updateRuleEnabled(rule_id: int, enabled: int, tolerance: float = None):
    if enabled not in (0, 1):
        raise Exception("enabled 仅支持 0 或 1")
    with db_session() as db:
        rule = db.execute(select(zd_ai_check_rule).where(zd_ai_check_rule.id == rule_id)).scalars().first()
        if not rule:
            raise Exception("规则不存在")
        rule.enabled = enabled
        # 仅金额规则可调容差；传 None 时不改动原值
        if rule.compare_type == "amount_diff" and tolerance is not None:
            if tolerance < 0:
                raise Exception("tolerance 必须为非负数值")
            rule.tolerance = tolerance
        db.commit()
    return {"id": rule_id, "enabled": enabled, "tolerance": float(rule.tolerance) if rule.tolerance is not None else None}
