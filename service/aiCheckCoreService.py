import json
import threading
from decimal import Decimal
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import select, update

from agent.initChatModel import getEasyMode
from model.initDataBase import db_session
from model.models import zd_ai_check_result, zd_ai_check_rule, zd_project_info
from observability import trace_config
from prompts import get_prompt

# 季报 PDF 通常十几页，全文喂给模型既慢又贵；关键字段集中在首页与财务摘要，
# 截断到前 3 万字符（约 1.5 万 token）足够覆盖，超出部分不参与抽取
MAX_PDF_CHARS = 30000
# 长后缀必须排在短后缀前面：先去「股份有限公司」，否则「有限公司」先命中会留下「某某股份」
NAME_SUFFIXES = ("股份有限公司", "有限责任公司", "有限公司")
DEFAULT_AMOUNT_TOLERANCE = Decimal("0.01")

EXTRACT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", get_prompt("extract")),
    ("human", "【PDF 文本】\n{text}"),
])

# 抽取是简单任务，关掉思考省时且输出更稳定（与生成评估裁判口径一致）
extract_chain = EXTRACT_PROMPT | getEasyMode().bind(
    temperature=0, extra_body={"thinking": {"type": "disabled"}}
) | StrOutputParser()


def startCheck(result_id: int):
    """触发校验：前置检查 → 抢占状态 → 后台线程执行，立即返回。"""
    with db_session() as db:
        row = db.execute(
            select(zd_ai_check_result).where(zd_ai_check_result.id == result_id)
        ).scalars().first()
        if not row:
            raise ValueError("校验记录不存在")
        if row.status == "in_progress":
            raise ValueError("校验进行中，请勿重复触发")
        if not row.file_path or not Path(row.file_path).is_file():
            raise ValueError("关联的披露文件不存在")
        project = db.execute(
            select(zd_project_info).where(zd_project_info.project_id == row.project_id)
        ).scalars().first()
        if not project:
            raise ValueError("关联的项目数据不存在，无法校验")
        enabled = db.execute(
            select(zd_ai_check_rule).where(zd_ai_check_rule.enabled == 1)
        ).scalars().all()
        if not enabled:
            raise ValueError("请先启用至少一条校验规则")

        # 条件更新抢占：并发的第二个请求在这里更新 0 行，直接拒掉
        claimed = db.execute(
            update(zd_ai_check_result)
            .where(zd_ai_check_result.id == result_id, zd_ai_check_result.status != "in_progress")
            .values(status="in_progress", error_msg=None)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()

    if not claimed:
        raise ValueError("校验进行中，请勿重复触发")

    threading.Thread(target=runCheck, args=(result_id,), daemon=True).start()
    return {"result_id": result_id, "status": "in_progress"}


def runCheck(result_id: int):
    """后台校验主流程：解析 PDF → 抽取字段 → 逐规则比对 → 落库。"""
    try:
        with db_session() as db:
            row = db.execute(
                select(zd_ai_check_result).where(zd_ai_check_result.id == result_id)
            ).scalars().first()
            project = db.execute(
                select(zd_project_info).where(zd_project_info.project_id == row.project_id)
            ).scalars().first()
            rules = db.execute(select(zd_ai_check_rule).order_by(zd_ai_check_rule.id)).scalars().all()
            project_values = {
                "year": project.year,
                "quarter": project.quarter_type,
                "amount": project.amount,
                "discloser": project.discloser,
            }
            file_name = row.file_name
            file_path = row.file_path

        text = readPdfText(file_path)
        extracted = extractFields(text)
        detail, status = compareAll(rules, extracted, project_values, file_name)

        with db_session() as db:
            db.execute(
                update(zd_ai_check_result)
                .where(zd_ai_check_result.id == result_id)
                .values(status=status, check_detail=detail, error_msg=None)
                .execution_options(synchronize_session=False)
            )
            db.commit()
    except Exception as e:
        # 技术故障单独标记：与业务「不一致」区分开，前端展示 error_msg 便于定位
        with db_session() as db:
            db.execute(
                update(zd_ai_check_result)
                .where(zd_ai_check_result.id == result_id)
                .values(status="error", error_msg=str(e))
                .execution_options(synchronize_session=False)
            )
            db.commit()


def readPdfText(file_path: str) -> str:
    pages = PyPDFLoader(file_path).load()
    text = "\n".join(page.page_content for page in pages)
    if not text.strip():
        raise ValueError("PDF 内容为空或无法提取文字")
    return text[:MAX_PDF_CHARS]


def extractFields(text: str) -> dict:
    raw = extract_chain.invoke(
        {"text": text},
        config=trace_config(tags=["ai-check"], trace_name="ai-check-extract"),
    )
    payload = parseJson(raw)
    return {
        "year": _asInt(payload.get("year")),
        "quarter": _asInt(payload.get("quarter")),
        "amount": _asNumber(payload.get("amount")),
        "discloser": _asText(payload.get("discloser")),
        "title": _asText(payload.get("title")),
    }


def parseJson(raw: str) -> dict:
    """模型可能把 JSON 包在 ```json 代码块里，剥掉围栏后取最外层花括号。"""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("字段抽取失败：模型未返回 JSON")
    try:
        payload = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"字段抽取失败：JSON 解析错误（{e}）")
    if not isinstance(payload, dict):
        raise ValueError("字段抽取失败：模型返回的不是 JSON 对象")
    return payload


def compareAll(rules, extracted: dict, project_values: dict, file_name: str):
    """返回 (明细字典, 整体状态)。停用规则记 SKIP，不参与整体状态判定。"""
    detail = {}
    for rule in rules:
        if rule.enabled != 1:
            detail[rule.field_name] = {"result": "SKIP", "reason": "规则未启用"}
            continue
        detail[rule.field_name] = compareOne(rule, extracted, project_values, file_name)

    judged = [item["result"] for item in detail.values() if item["result"] != "SKIP"]
    status = "success" if all(r == "MATCH" for r in judged) else "failed"
    return detail, status


def compareOne(rule, extracted: dict, project_values: dict, file_name: str) -> dict:
    field = rule.field_name
    if field == "disclosure_date":
        return compareQuarter(extracted, project_values)
    if field == "amount":
        return compareAmount(extracted, project_values, rule)
    if field == "discloser":
        return compareDiscloser(extracted, project_values)
    if field == "title":
        return compareTitle(extracted, file_name)
    return {"result": "SKIP", "reason": f"未知规则字段：{field}"}


def compareQuarter(extracted: dict, project_values: dict) -> dict:
    pdf_value = {"year": extracted["year"], "quarter": extracted["quarter"]}
    db_value = {"year": project_values["year"], "quarter": project_values["quarter"]}
    if pdf_value["year"] is None or pdf_value["quarter"] is None:
        return _mismatch(pdf_value, db_value, "PDF 中未提取到该字段")
    if db_value["year"] is None or db_value["quarter"] is None:
        return _mismatch(pdf_value, db_value, "业务数据中该字段为空")
    match = pdf_value == db_value
    return _result(pdf_value, db_value, match, "" if match else "披露年月季度与业务数据不一致")


def compareAmount(extracted: dict, project_values: dict, rule) -> dict:
    pdf_value = extracted["amount"]
    db_value = project_values["amount"]
    if pdf_value is None:
        return _mismatch(pdf_value, _floatOrNone(db_value), "PDF 中未提取到该字段")
    if db_value is None:
        return _mismatch(pdf_value, None, "业务数据中该字段为空")

    tolerance = Decimal(str(rule.tolerance)) if rule.tolerance is not None else DEFAULT_AMOUNT_TOLERANCE
    diff = abs(Decimal(str(pdf_value)) - Decimal(str(db_value)))
    match = diff <= tolerance
    reason = "" if match else f"金额相差 {diff.quantize(Decimal('0.01'))} 元，超出容差 {tolerance} 元"
    return _result(pdf_value, float(db_value), match, reason)


def compareDiscloser(extracted: dict, project_values: dict) -> dict:
    pdf_value = extracted["discloser"]
    db_value = project_values["discloser"]
    if pdf_value is None:
        return _mismatch(pdf_value, db_value, "PDF 中未提取到该字段")
    if not db_value:
        return _mismatch(pdf_value, db_value, "业务数据中该字段为空")
    match = normalizeName(pdf_value) == normalizeName(db_value)
    return _result(pdf_value, db_value, match, "" if match else "披露人归一化后仍不一致")


def compareTitle(extracted: dict, file_name: str) -> dict:
    pdf_value = extracted["title"]
    # 文件名带扩展名而公告标题不带，直接比必然失配，只比主文件名
    db_value = Path(file_name).stem
    if pdf_value is None:
        return _mismatch(pdf_value, db_value, "PDF 中未提取到该字段")
    match = pdf_value.strip() == db_value.strip()
    return _result(pdf_value, db_value, match, "" if match else "公告标题与文件名不一致")


def normalizeName(name: str) -> str:
    cleaned = str(name).strip().replace(" ", "").replace("\u3000", "")
    for suffix in NAME_SUFFIXES:
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)]
    return cleaned


def _result(pdf_value, db_value, match: bool, reason: str) -> dict:
    return {
        "pdf": pdf_value,
        "db": db_value,
        "result": "MATCH" if match else "MISMATCH",
        "reason": reason,
    }


def _mismatch(pdf_value, db_value, reason: str) -> dict:
    return {"pdf": pdf_value, "db": db_value, "result": "MISMATCH", "reason": reason}


def _asInt(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _asNumber(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _asText(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _floatOrNone(value):
    return float(value) if value is not None else None
