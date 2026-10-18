# 智答 · 企业知识库 RAG 智能问答平台

面向证券合规/内控制度的企业内部知识库问答系统。基于 **LangGraph Agent + 混合检索（向量 + BM25）+ bge 精排** 构建，内置双口径检索评测、LLM-as-Judge 生成评测与规则化合规风险拦截，配套 Vue3 管理端。

## 核心链路

```
用户提问
  │
  ▼
┌─────────────┐   改写(glm-flash)    ┌──────────────────┐
│ create_agent │ ───────────────────→ │ 查询改写节点        │
└──────┬──────┘                      └────────┬─────────┘
       │ 工具路由：graphAnswer / 评测指标查询    │
       ▼                                       ▼
┌──────────────────────────────┐   ┌─────────────────────┐
│ 双路召回                       │   │                     │
│  · 向量：改写后问题 top25      │   │  RRF 融合(K=60)      │
│  · BM25：原问题 top5          │──→│  正文去重 → 保留30条   │
└──────────────────────────────┘   └─────────┬───────────┘
                                             ▼
                              ┌──────────────────────────┐
                              │ bge-reranker-v2-m3 精排    │
                              │ (阈值0.2过滤 + batch=8)    │
                              └────────────┬─────────────┘
                                           ▼
                              ┌──────────────────────────┐
                              │ LLM 生成 (glm-5.3, temp=0) │
                              └────────────┬─────────────┘
                                           ▼
                              ┌──────────────────────────┐
                              │ RiskGuard 规则拦截         │  ← 落库前，审计一致
                              └────────────┬─────────────┘
                                           ▼
                                      答案返回 + SSE 流式
```

## 主要特性

- **LangGraph Agent 编排**：`create_agent` 挂载 3 个工具（知识库问答 / 检索指标查询 / 生成评估查询），StateGraph 五节点流水线（改写 → 双路召回 → 融合去重 → 精排 → 生成），SqliteSaver 会话级记忆
- **混合检索**：向量（改写后问题）与 BM25（原问题）双路召回，手写 RRF（K=60）融合，按正文去重，CrossEncoder 精排后取 top_k
- **规则化风控 RiskGuard**：硬拦「伪造资料出处 / 条号被书名号包裹 / 引用条号不存在 / 张冠李戴 / 条号歧义 / 数字期限待核对」6 类问题，high 级直接拦截替换为合规话术，发生在答案落库前
- **流式输出**：后台线程 + `queue.Queue` 桥接同步链与异步 SSE，支持取消、超时、断流后后台 drain 缓存续读
- **评测体系**：检索评估（recall@k / MRR，rank_any / rank_all 双口径落库）+ 生成评估（LLM-as-Judge 三维裁判：correctness / completeness / faithfulness）+ 前端可视化分页
- **可观测**：Langfuse 全链路埋点（生成/改写/评测统一挂 CallbackHandler）

## 技术栈

| 分层 | 技术 |
|---|---|
| 后端框架 | Python 3.13 · FastAPI · uvicorn |
| LLM 编排 | LangChain 1.x · LangGraph 1.x（create_agent + StateGraph） |
| 存储 | MySQL 8（业务元数据）· ChromaDB（向量）· SQLite（checkpoint/会话记忆） |
| 检索/模型 | rank-bm25 + jieba · DashScope text-embedding-v1 · bge-reranker-v2-m3（本地 CrossEncoder） |
| 生成模型 | glm-5.3（主）· glm-5.3-flash（改写/轻任务），走 GOAI OpenAI 兼容端点 |
| 可观测 | Langfuse（CallbackHandler） |
| 前端 | Vue3 · Element Plus · Vite · Pinia · ECharts |

## 快速开始

### 1. 环境准备

- Python 3.13 + 依赖（LangChain 1.x、LangGraph、FastAPI、SQLAlchemy 2、chromadb、langchain-chroma、rank-bm25、jieba、sentence-transformers 等）
- MySQL 8（需先建库）
- 本地 bge-reranker-v2-m3 模型目录（路径见 `agent/rag/initRag.py`）

### 2. 配置 `.env`

复制一份本地 `.env`（**git 已忽略，勿提交**），至少包含：

```ini
# 模型端点（GOAI OpenAI 兼容）
GOAI_API_KEY=...
GOAI_BASE_URL=...
# 向量模型
QWEN_API_KEY=...
# MySQL
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=...
MYSQL_PASSWORD=...
MYSQL_DB=...
# 可选：Langfuse 埋点
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=...
```

### 3. 启动后端

```bash
# 正常模式（reload）
python main.py
# 单进程调试模式（配合 PyCharm/VS Code 调试器）
python main.py --debug
```

监听 `127.0.0.1:8000`。启动时自动建缺失的表（失败降级为告警不阻断）。

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`，`/api` 代理到 8000。

## 评测

自建 45 题评测集（`tests/rag_testset.json`，easy/medium/hard 分布），双轨：

| 口径 | 指标 | 数值 |
|---|---|---|
| 检索（top-5） | recall@5 | **0.9778** |
| 检索（top-5） | MRR | **0.9556** |
| 生成（68 题，8 并发） | correctness / completeness / faithfulness 均分 | 2.0 / 1.97 / 2.0 |

命令行脚本：

```bash
python tests/run_eval_data.py --limit N --workers N   # 生成评测
python tests/run_retrieval_eval.py                     # 检索评测
```

也可在管理端「评估」页发起评测，结果落库可复现；基线纪律：temperature=0、改动前留对照轮。

## 目录结构

```
agent/          模型初始化 · LangGraph 节点 · 流式处理
  handle/       llm_stream_handle.py（流式状态机）
  rag/          RiskGuard · 向量/重排初始化
api/            FastAPI 路由（问答 / 文件管理）
model/          ORM 模型 · 数据库初始化
schema/         统一响应契约 {code, message, data}
service/        检索服务 · 对话服务 · 评测服务 · Agent 图
tools/          Agent 工具定义
frontend/       Vue3 管理端
tests/          评测集 + 离线评测脚本
```

## 已知边界

- 单机单进程部署，无容器化/集群；无登录鉴权（内网使用）
- 生成层同步 invoke（模型适配层不支持异步路径），流式经线程桥接
- 评测基线数值受测试集/模型版本影响，改动前请留对照轮
