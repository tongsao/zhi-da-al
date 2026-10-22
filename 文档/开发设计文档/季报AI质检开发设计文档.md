# 季报 AI 质检功能开发设计文档

> 版本：v1.0 ｜ 日期：2026-10-18
> 关联文档：《季报AI质检功能需求文档》v1.0
> 定位：承接 AI 质检需求的技术设计，覆盖数据模型、接口、校验核心流程、比对算法、前端页面与部署要点

---

## 1. 技术栈与工程约束

| 项 | 说明 |
|---|---|
| 后端框架 | FastAPI（现有 `main.py` 注册路由，统一返回 `schema.schemas.Response`） |
| ORM / DB | SQLAlchemy + pymysql + MySQL，统一走 `model.initDataBase.db_session()` |
| PDF 解析 | `langchain_community.document_loaders.PyPDFLoader`（现有链路已用，无需新依赖） |
| 字段抽取 LLM | `agent.initChatModel.getEasyMode()`（glm-5.3-flash，temperature=0.3），抽取任务独立于问答链路 |
| 埋点 | 与现有链路一致，模型带 Langfuse CallbackHandler |
| 异步执行 | 后台线程池 + 前端轮询（复用现有生成评测的异步模式思路，不引入 Celery） |
| 文件保存 | 复用 `ragFileService.uploadFileAndSaveDir` 的校验/分块写盘口径 |

代码分层沿用现有结构：`api/`（Controller）、`service/`（业务）、`model/`（ORM）、`schema/`（入参/出参）、`agent/`（LLM 能力）、前端静态资源目录。

---

## 2. 模块划分

```
api/aiCheckController.py        接口层（已建，本期补触发/明细接口）
service/aiCheckService.py       数据接入层（已建，本期补触发校验/复检关联）
service/aiCheckCoreService.py   校验核心（新增）：抽取编排 + 四规则比对 + 状态落库
agent/agent_tools.py            校验专用工具函数（新增，或独立 aiCheckTools.py）
frontend/static/…               校验列表页 / 明细页 / 规则配置页（新增三个页面）
```

---

## 3. 数据模型设计

### 3.1 zd_project_info（项目信息表，已建）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK AI | 自增主键 |
| project_id | VARCHAR(100) UNIQUE | 上游唯一标识，推送幂等键 |
| project_name | VARCHAR(255) | 项目名称（本期不参与比对，仅展示） |
| year | INT | 年份 |
| month | INT | 月份 1-12 |
| quarter_type | INT | 季度类型 1/2/3/4 |
| amount | DECIMAL(20,2) | 金额（元） |
| discloser | VARCHAR(255) | 披露人 |
| created_at / updated_at | DATETIME | 时间戳 |

> 金额字段评审建议由 Float 改为 **DECIMAL(20,2)**（金融对账精度，规避浮点误差）。已建表需执行 DDL 变更：
> `ALTER TABLE zd_project_info MODIFY amount DECIMAL(20,2) NULL COMMENT '金额（单位:元）';`
> 同步更新 ORM 为 `Numeric(20, 2)`。**该项需业务/技术确认后执行。**

### 3.2 zd_ai_check_result（质检结果状态表，已建，本期补 3 个字段/变更）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK AI | 自增主键 |
| project_id | VARCHAR(100) INDEX | 关联 zd_project_info |
| file_name | VARCHAR(255) INDEX | 文件名（复检同名匹配依据） |
| file_path | VARCHAR(255) | 校验读取的文件路径（记录级，非"最新版本"） |
| file_type | VARCHAR(50) | 文件扩展名 |
| status | VARCHAR(20) INDEX | pending/in_progress/success/failed/error |
| check_detail | JSON | 逐字段校验明细，结构与 5.1 抽取输出对齐，格式见下 |
| **recheck_from** | INT NULL | **（新增）复检来源：被复检的历史记录 id，普通记录为 NULL** |
| **error_msg** | **TEXT** | **（建议变更）异常原因；自 VARCHAR(500) 改为 TEXT，避免中文异常栈截断** |
| create_date / update_date | DATETIME | 时间戳 |

> `check_detail` JSON 结构（每条启用规则一个对象，key 与人工校验规则编号一致）：
> ```json
> {
>   "disclosure_date": {"pdf": {"year":2026,"quarter":3,"raw":"2026年三季度"}, "db": {"year":2026,"quarter":3}, "result": "MATCH", "reason": ""},
>   "amount":         {"pdf": 123000000.00, "db": 123000000.00, "result": "MATCH", "reason": ""},
>   "discloser":      {"pdf": "某某证券", "db": "某某证券股份有限公司", "result": "MISMATCH", "reason": "PDF中未提取到该字段"},
>   "title":          {"pdf": null, "db": "某某证券2026年三季度报告.pdf", "result": "MISMATCH", "reason": "PDF中未提取到该字段"}
> }
> ```
> result 枚举：`MATCH`（一致）/ `MISMATCH`（不一致）/ `SKIP`（规则未启用，不进入比对）。

> DDL 变更：
> 1. `ALTER TABLE zd_ai_check_result ADD COLUMN recheck_from INT NULL COMMENT '复检来源记录id' AFTER check_detail;`
> 2. `ALTER TABLE zd_ai_check_result MODIFY error_msg TEXT NULL COMMENT '异常原因';`
> 同步更新 ORM：`recheck_from = Column(Integer, nullable=True)`、`error_msg = Column(Text, nullable=True)`。

### 3.3 zd_ai_check_rule（规则表，已建，本期补 1 个字段）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK AI | 自增主键 |
| field_name | VARCHAR(50) UNIQUE | disclosure_date / amount / discloser / title |
| field_label | VARCHAR(50) | 中文名 |
| compare_type | VARCHAR(20) | quarter_match / amount_diff / name_normalized / string_exact |
| **tolerance** | **DECIMAL(20,2) NULL** | **（新增）容差，仅 amount_diff 使用，默认 0.01** |
| enabled | INT | 1 启用 / 0 停用（全局一套） |
| created_at | DATETIME | 时间戳 |

启动时幂等预置 4 条规则（已实现），amount 规则 tolerance 预置为 0.01，其余为 NULL。

> DDL 变更：
> `ALTER TABLE zd_ai_check_rule ADD COLUMN tolerance DECIMAL(20,2) NULL COMMENT '容差(仅金额比对用)' AFTER compare_type;`
> 同步更新 ORM：`tolerance = Column(Numeric(20, 2), nullable=True)`。
> 规则模型字段若需业务调整超 4 条以上、或需按项目差异化时，属后续迭代，本期不做。

---

## 4. 接口设计

统一返回 `Response(code="0", message="ok", data=…)`，异常 code="5001" + message。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | /api/v1/ai-check/projects | 结构化数据推送（幂等更新） | 已实现 |
| POST | /api/v1/ai-check/files | PDF 推送（multipart，含 project_id） | 已实现 |
| GET | /api/v1/ai-check/projects | 项目分页列表 | 已实现 |
| GET | /api/v1/ai-check/projects/{project_id} | 项目详情 | 已实现 |
| GET | /api/v1/ai-check/results | 校验记录分页列表（可带 status/project_id 过滤） | 已实现 |
| GET | /api/v1/ai-check/results/{result_id} | 单条校验明细（含 check_detail） | **本期新增** |
| POST | /api/v1/ai-check/results/{result_id}/check | 手动触发校验（异步，立即返回） | **本期新增** |
| GET | /api/v1/ai-check/rules | 规则列表 | 已实现 |
| PUT | /api/v1/ai-check/rules/{rule_id}/enabled | 规则开关 | 已实现 |

### 4.1 手动触发校验（POST /results/{result_id}/check）

- 入参：result_id
- 前置校验：
  1. 记录存在，且状态非 `in_progress`（校验中不可重复触发）；
  2. 关联文件存在（按 file_path 检查文件本体）；
  3. 关联 project 数据存在；
  4. **至少一条规则启用**，否则返回提示「请先启用至少一条校验规则」，状态不变。
- 通过后：状态置 `in_progress`，提交后台线程执行校验，接口立即返回 `{result_id, status:"in_progress"}`。

### 4.2 校验明细（GET /results/{result_id}）

返回记录全部字段 + check_detail（含 recheck_from，用于前端标识"复检"）。

---

## 5. 校验核心流程（aiCheckCoreService）

```
POST /results/{id}/check
  └─ 前置校验（见 4.1）通过 → 状态 in_progress → 提交后台线程
       └─ runCheck(result_id)
            ├─ 1. 读取记录 file_path + project 数据
            ├─ 2. PyPDFLoader 解析 PDF 全文
            ├─ 3. LLM 抽取四字段（getEasyMode，结构化 JSON 输出）
            ├─ 4. 逐条启用规则比对（见第 6 节）
            ├─ 5. 汇总整体状态 + 明细，落库 check_detail
            └─ 6. 任一步异常 → status=error + error_msg，不覆盖明细
```

- 线程并发控制：每条记录校验前通过 `update … where status!='in_progress'` 条件更新保证互斥（数据库层防并发触发）。
- 轮询：前端对 `GET /results/{id}` 每 2s 轮询，status 离开 `in_progress` 即结束。

### 5.1 抽取提示词设计（关键）

系统提示词约束（写入 `agent` 抽取函数）：

1. 只允许输出 JSON：`{"disclosure_date":"2026-08-28","year":2026,"quarter":3,"amount":123000000.00,"discloser":"某某证券股份有限公司","title":"某某证券2026年三季度报告"}`；
2. 金额统一输出为**元**（中文单位"万元/亿元"换算后数值），去除千分位/货币符号；
3. `disclosure_date` 允许中文/阿拉伯两种书写，统一转 `YYYY-MM-DD`，并推导 `year` 与 `quarter`（1-3月→1，4-6月→2，7-9月→3，10-12月→4）；
4. 未提取到某字段时输出 `null`，**禁止猜测**；
5. 模型输出非法 JSON 或非 JSON 时，解析失败计入校验异常；
6. 输出 JSON 但**字段级缺失**（如只输出 title 缺其余三个）时，缺失字段按「未提取到」处理（判不一致，原因「PDF 中未提取到该字段」），**不计入校验异常**——校验异常仅限整体解析失败（PDF 无法解析、输出非 JSON）。

---

## 6. 比对算法（四规则）

| compare_type | 算法 | 判定一致 |
|---|---|---|
| quarter_match | LLM 输出 year+quarter 与 project.year+project.quarter_type 精确比较 | 均相等 |
| amount_diff | 双方换算元后 `abs(pdf - db) <= tolerance`，tolerance 取自规则表 3.3 的 tolerance 字段（默认 0.01，业务可调） | 差值在容差内 |
| name_normalized | 双方去除首尾空白、去除「股份有限公司/有限公司」等后缀后比较 | 归一化后相等 |
| string_exact | PDF 抽取 title 与 file_name 精确比较（含标点） | 相等 |

字段缺失判定（先于比对执行）：

- PDF 抽取值 null → 该字段不一致，原因「PDF 中未提取到该字段」；
- 业务数据字段为空 → 该字段不一致，原因「业务数据中该字段为空」；
- 以上缺失不改变整体状态类型（整体仍为 failed/不一致），只有解析/抽取技术异常才置 error。

整体状态：所有启用规则一致 → `success`；任一不一致 → `failed`；无启用规则不会进入本流程（4.1 已拦截）。

---

## 7. 复检关联（4.7 的实现）

在 `saveCheckFile` 中补充（当前为每次推送插新记录）：

```
推送文件 → 插入新记录（status=pending）
  └─ 查询是否已有 file_name 相同的历史记录
       ├─ 有 → 新记录.recheck_from = 最近一条同名记录的 id
       └─ 无 → recheck_from = NULL（普通记录）
```

- 不自动执行校验；业务对带 recheck_from 的最新记录点击「开始校验」即完成复检。
- 列表页按 project_id 聚合展示时取 create_date 最新的记录。

---

## 8. 前端页面设计

沿用现有页面技术（静态资源 + 原生 JS/现有风格），新增三个页面：

### 8.1 校验列表页

- 表格列：项目名称、文件名、最新校验状态（含复检标识）、校验时间、字段摘要
- 操作：未校验/需复检记录提供「开始校验」
- 支持按状态筛选、按时间排序；状态徽标四色（pending/in_progress/success/failed/error）

### 8.2 校验明细页

- 顶部：文件信息 + 整体状态 + error_msg（异常时展示）
- 明细区：每字段一行「PDF 抽取值 / 业务数据值 / 结果 / 原因」，缺失显示「未提取到」
- 提供返回列表

### 8.3 规则配置页

- 四行开关（披露日期/金额/披露人/公告标题），切换调用 PUT 接口，即时生效
- 金额规则额外暴露「容差（元）」输入框，保存到规则表 tolerance 字段（PUT /rules/{id}/enabled 扩展为可同时提交 enabled 与 tolerance）

---

## 9. 部署与配置

- 无新增环境变量；复用 `UPLOAD_FILE_PATH`、`MAX_FILE_SIZE`、`ALLOWED_FILE_EXTENSIONS`
- PDF 依赖 `pypdf`（PyPDFLoader 的底层，现有环境已具备）
- 数据库变更执行 `DB/ddl/create_ai_check_tables.sql`（更新版）后再部署

---

## 10. 风险与待确认项

| 编号 | 事项 | 说明 |
|---|---|---|
| 1 | amount 改 DECIMAL | 需确认后执行 DDL + ORM 变更（涉及现有数据） |
| 2 | 一文件多项目 | 若上游单 PDF 含多项目内容，抽取与关联模型需重构；开发前需确认 |
| 3 | 抽取准确率 | 首版以规则+提示词约束保证，上线后用 error/failed 原因分布评估是否需要补充抽取校验 |
| 4 | 容差配置 | tolerance 已落库到规则表（3.3），业务可通过规则配置页调整金额容差（本期 UI 暴露该输入框，纳入 8.3） |
| 5 | 校验中崩溃恢复 | 进程中断时 in_progress 记录需提供人工重置入口（列表页"重置为待校验"），本期含基础版本 |
