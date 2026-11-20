"""Langfuse Trace 审计元数据：Prompt / 工具 / 测试集版本 + 代码分支。

版本在进程启动时计算一次，通过 Runnable config 的 metadata 传给 Langfuse；
根链路上同时挂载 Langfuse 回调，trace 的 session/tags/name 与 metadata 才会写入。
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from llm_gateway.providers import langfuse_handler
from model_versions import CHAT_MODEL, EMBEDDING_MODEL, RERANKER_MODEL, REWRITE_MODEL
from prompts import CURRENT

ROOT = Path(__file__).resolve().parent
TESTSET_PATH = ROOT / "tests" / "rag_testset.json"


def _git(*args: str) -> str:
    """读取 git 信息；非 git 目录或命令不可用时返回空串。"""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _testset_version() -> tuple[str, int]:
    """测试集内容哈希：内容一改版本即变，不依赖人工维护。"""
    if not TESTSET_PATH.exists():
        return "", 0
    raw = TESTSET_PATH.read_bytes()
    try:
        count = len(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        count = 0
    return hashlib.sha256(raw).hexdigest()[:12], count


_testsets_version, _testset_count = _testset_version()

# 所有 Trace 共用的审计元数据
BASE_TRACE_METADATA = {
    "app_env": os.getenv("APP_ENV", ""),
    "code_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
    "code_commit": _git("rev-parse", "--short", "HEAD"),
    "code_dirty": "true" if _git("status", "--porcelain", "--untracked-files=no") else "false",
    "testset_version": _testsets_version,
    "testset_count": str(_testset_count),
    "model_chat": CHAT_MODEL,
    "model_rewrite": REWRITE_MODEL,
    "model_embedding": EMBEDDING_MODEL,
    "model_reranker": RERANKER_MODEL,
    **{f"prompt_{name}": version for name, version in CURRENT.items()},
}
BASE_TRACE_METADATA = {key: value for key, value in BASE_TRACE_METADATA.items() if value != ""}


def trace_config(config=None, *, tags=None, trace_name=None, session_id=None, **extra):
    """给 Runnable config 注入 Langfuse 回调与审计元数据。

    LangChain 按实例去重回调，模型层已挂的 handler 不会重复触发。
    """
    cfg = dict(config or {})
    callbacks = list(cfg.get("callbacks") or [])
    if langfuse_handler not in callbacks:
        callbacks.append(langfuse_handler)
    cfg["callbacks"] = callbacks

    metadata = dict(cfg.get("metadata") or {})
    metadata.update(BASE_TRACE_METADATA)
    if tags:
        metadata["langfuse_tags"] = [str(tag) for tag in tags]
    if trace_name:
        metadata["langfuse_trace_name"] = trace_name
    if session_id is not None:
        metadata["langfuse_session_id"] = str(session_id)
    metadata.update({key: str(value) for key, value in extra.items()})
    cfg["metadata"] = metadata
    return cfg
