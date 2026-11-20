# 季报 AI 质检测试案例文档

> 版本：v1.0 ｜ 日期：2026-11-20
> 配套文档：《季报AI质检功能.md》《季报AI质检开发设计文档.md》《统一网关测试案例文档.md》
> 说明：本案例以两份配套文档约定的行为为准编写，并与当前实现（`api/aiCheckController.py`、`service/aiCheckService.py`、`service/aiCheckCoreService.py`、`frontend/src/views/AiCheckView.vue`）逐项核对。实现与设计的差异集中在第 6 节，涉及差异的用例在备注中标注。

---

## 1. 概述

### 1.1 目的

验证「季报 AI 质检」P0 范围各项能力满足需求文档验收标准：

- 上游结构化数据与披露 PDF 的接入、落库与关联；
- 手动触发校验、异步执行、状态流转与并发互斥；
- PDF 字段抽取与披露日期/金额/披露人/公告标题四条规则的比对准确性；
- 校验结果列表、明细展示与校验规则开关配置；
- 同名重推的复检闭环与历史留痕；
- 与统一网关的权限边界不发生回归。

### 1.2 范围

覆盖需求文档第 4 章全部功能点，以及设计文档第 5~8 章的实现细节；前端为手工 UI 用例；判定算法部分单独提供不依赖模型的单元级用例（模块 H）。

### 1.3 测试入口与响应约定

- 服务地址：`http://127.0.0.1:8000`（本地默认端口）；
- 前端页面：`http://127.0.0.1:5173/ai-check`（`frontend/` 下 `npm run dev`）；
- 鉴权（与统一网关对齐）：
  - 上游推送 `POST /api/v1/ai-check/projects`、`POST /api/v1/ai-check/files` **仅接受 `X-Api-Key`**（带 JWT 返回 403/4030，无凭证返回 401/4010）；
  - 规则开关 `PUT /api/v1/ai-check/rules/{id}/enabled` **仅 admin**（业务员 403/4030）；
  - 查看类 `GET /api/v1/ai-check/**` 允许已登录业务员与密钥访问。
- **响应格式（以当前实现为准）**：
  - 成功：HTTP 200，直接返回业务 JSON，**无 `{code,message,data}` 信封**。例如 `{"project_id":"..."}`、`{"total":N,"items":[...]}`、`{"result_id":N,"status":"in_progress"}`；
  - 业务失败：HTTP 200，返回 `{"code":"5001","message":"<异常文案>"}`；
  - 参数类型错误（如 `enabled=abc`、`result_id=abc`）：FastAPI 返回 HTTP 422，不进入业务方法；
  - 因此断言统一按「HTTP 200 + 是否存在 `code` 字段」区分成功/失败。
- 校验状态枚举（DB 值 → 页面文案）：

| DB 值 | 页面文案 | 含义 |
|---|---|---|
| pending | 待校验 | 文件已入库，未发起校验 |
| in_progress | 校验中 | 后台线程执行中 |
| success | 一致 | 所有启用规则均 MATCH |
| failed | 不一致 | 任一启用规则 MISMATCH（含字段缺失） |
| error | 校验异常 | PDF 解析 / 字段抽取等技术故障 |

### 1.4 用例编号规则与优先级

- 编号：`TC-<模块字母>-<序号>`，模块映射：A=结构化数据接入、B=文件接入与复检、C=列表与明细、D=触发与并发、E=抽取与四规则比对、F=异常与状态机、G=规则配置、H=判定算法单元、I=前端、J=初始化部署与权限。
- 优先级：P0=验收核心（必须全部通过方可发布）；P1=重要（正常发布应通过）；P2=边界/风险观察项。

---

## 2. 测试环境与准备

### 2.1 环境要求

- conda 环境 `langchain1.2`，解释器 `E:\conda\envs\langchain1.2\python.exe`；
- MySQL 可用，`.env` 已配置 `UPLOAD_FILE_PATH=./data/FILE`、`MAX_FILE_SIZE=104857600`、`FILE_CHUNK_SIZE=1048576`、`ALLOWED_FILE_EXTENSIONS=["pdf","txt","json","md"]`；
- 模型：`getEasyMode()` 可用（依赖 `GOAI_API_KEY` 有效）；模型不可用时 E/F 端到端用例标记 Blocked，H 模块与 A~D、G、J 不受影响；
- 服务启动（**必须在仓库根目录启动**，文件路径为相对路径，见 TC-J-04）：`E:\conda\envs\langchain1.2\python.exe main.py`；
- 依赖：`pypdf` 已安装（PyPDFLoader 底层依赖）。

### 2.2 测试数据准备

| 数据 | 准备方式 | 用途 |
|---|---|---|
| 项目 `P2026Q3-001` | 推送：year=2026、month=8、quarter_type=3、amount=120000000.00、discloser=`某某证券股份有限公司` | 主流程比对基准 |
| PDF 一致样本 `某某证券2026年第三季度报告.pdf` | Word 导出文字版 PDF；正文含披露日期 2026-08-28、金额「1.2亿元」、披露人「某某证券」 | E-01/E-03/E-05/E-07 |
| PDF 季度错样本 `某某证券2026年第二季度报告.pdf` | 同上，日期改为 2026-05-20 | E-02 |
| PDF 金额错样本 | 金额写「1.3亿元」 | E-04 |
| PDF 缺字段样本 | 不写披露人 | E-10 |
| 损坏 PDF `损坏样本.pdf` | 将任意 txt 文本改扩展名为 `.pdf` | F-01 |
| 扫描件 PDF | 图片转 PDF，无文字层 | F-02 |
| 同名修正版 | 与一致样本同名，金额修正为一致 | F-08 复检闭环 |
| 密钥 / admin token | 网关密钥管理创建；admin 登录取得 JWT | 接口鉴权 |
| 无文字超长样本 | 正文 4 万字符的 PDF | H-10 截断边界 |

### 2.3 执行顺序建议

1. 模块 J（初始化与部署）→ 确认表结构、依赖、启动约束；
2. 模块 A/B（数据与文件接入）→ 准备项目、文件、复检记录；
3. 模块 C/D（列表、明细、触发与并发）→ 打通状态机；
4. 模块 H（算法单元）→ 先锁定四条规则判定口径，无模型噪声；
5. 模块 E/F（端到端比对与异常）→ 依赖模型，逐条样本执行；
6. 模块 G（规则配置）→ 开关与容差；
7. 模块 I（前端）→ 页面联调。

---

## 3. 用例公共约定

- 文中 `X-Api-Key` 指网关创建密钥时返回的明文；`admin token` 指 `POST /api/v1/auth/login` 返回的 `data.token`。
- 触发校验为**异步**：接口立即返回 `in_progress`，用例需以 1~2s 间隔轮询 `GET /api/v1/ai-check/results/{id}`，直到 `status != in_progress`；默认超时 180s，模型排队时放宽至 300s。
- 状态断言以 **DB `zd_ai_check_result`** 为准，接口仅作观察；`update_date` 变化表示校验动作已落库。
- 模块 E 每条用例执行前先复位规则：四条全部 `enabled=1`、金额 `tolerance=0.01`，避免相互干扰。
- 端到端抽取结果受模型能力影响：若 PDF 文本可读但抽取值与预期不符，先核对样本正文，再判定是模型问题而非判定逻辑问题；判定逻辑一律以模块 H 的结论为准。
- 复检与标题比对依赖**文件名严格不变**（合规披露文件约定），测试中不得随意改文件名。

---

## 4. 测试用例

### 4.1 模块 A：结构化数据接入

#### TC-A-01 新增项目成功
- 优先级：P0
- 前置：持有有效 `X-Api-Key`。
- 步骤：
  1. `POST /api/v1/ai-check/projects`，Header `X-Api-Key`，body：
     ```json
     {"project_id":"P2026Q3-001","project_name":"某某集合资产管理计划","year":2026,"month":8,
      "quarter_type":3,"amount":120000000.00,"discloser":"某某证券股份有限公司"}
     ```
- 预期：
  1. HTTP 200，返回 `{"project_id":"P2026Q3-001"}`（无 `code` 字段）；
  2. 新建 `zd_project_info` 一行，`amount` 以 DECIMAL(20,2) 存 120000000.00；
  3. `GET /api/v1/ai-check/projects/P2026Q3-001` 返回全字段，`created_at` 为 `YYYY-MM-DD HH:MM:SS`。
- 备注：成功响应仅回 `project_id`，其余字段以详情接口/DB 断言。

#### TC-A-02 同一 project_id 重复推送为幂等更新
- 优先级：P0
- 前置：TC-A-01 已完成。
- 步骤：
  1. 再次推送同一 `project_id`，仅将 `amount` 改为 `121000000.00`、`project_name` 改为「某某集合资产管理计划（二期）」；
  2. `GET /api/v1/ai-check/projects/P2026Q3-001`；
  3. `SELECT COUNT(*) FROM zd_project_info WHERE project_id='P2026Q3-001'`。
- 预期：
  1. 返回 `{"project_id":"P2026Q3-001"}`；
  2. 详情为最新内容，`updated_at` 更新、`created_at` 不变；
  3. 计数恒为 1，不产生重复行。

#### TC-A-03 project_id 缺失被拒
- 优先级：P0
- 步骤：
  1. `POST /projects`，body `{"project_name":"无ID项目"}`。
- 预期：
  1. 返回 `{"code":"5001","message":"project_id 必填"}`；
  2. 不写入任何记录。

#### TC-A-04 month 非法被拒
- 优先级：P1
- 步骤：
  1. 分别以 `month=0`、`month=13` 推送合法 project_id。
- 预期：
  1. 均返回 `code="5001"`，`message="month 必须在 1-12 之间"`；
  2. 记录不落库（若 project_id 已存在，原值不被改写）。

#### TC-A-05 quarter_type 非法被拒
- 优先级：P1
- 步骤：
  1. 以 `quarter_type=5`（或 0）推送。
- 预期：
  1. `code="5001"`，`message="quarter_type 必须是 1/2/3/4"`。

#### TC-A-06 amount 为负被拒
- 优先级：P1
- 步骤：
  1. 以 `amount=-0.01` 推送。
- 预期：
  1. `code="5001"`，`message="amount 必须为非负数值"`。

#### TC-A-07 项目分页列表
- 优先级：P1
- 前置：库中至少 3 个项目。
- 步骤：
  1. `GET /api/v1/ai-check/projects?page=1&page_size=2`。
- 预期：
  1. 返回 `{"total":N,"items":[...]}`，`items` 长度 2；
  2. 按 `created_at` 倒序；
  3. 每项字段：project_id、project_name、year、month、quarter_type、amount、discloser、created_at。

#### TC-A-08 项目详情与不存在
- 优先级：P1
- 步骤：
  1. `GET /api/v1/ai-check/projects/P2026Q3-001`；
  2. `GET /api/v1/ai-check/projects/NOT_EXIST`。
- 预期：
  1. 步骤 1 返回项目对象；
  2. 步骤 2 返回 `code="5001"`，`message="项目不存在"`。

#### TC-A-09 允许半结构化数据入库（字段可为空）
- 优先级：P2
- 步骤：
  1. 仅推送 `{"project_id":"P-PARTIAL-001","year":2026}`。
- 预期：
  1. 入库成功，其余字段为 NULL；
  2. 该类项目触发校验时，缺失字段按「业务数据中该字段为空」判不一致（见 TC-E-11）。

---

### 4.2 模块 B：披露文件接入与复检关联

#### TC-B-01 推送 PDF 成功生成待校验记录
- 优先级：P0
- 前置：项目 `P2026Q3-001` 已存在；`X-Api-Key` 有效。
- 步骤：
  1. `POST /api/v1/ai-check/files?project_id=P2026Q3-001`，multipart 上传 `某某证券2026年第三季度报告.pdf`；
  2. 查询 `zd_ai_check_result` 最新一条。
- 预期：
  1. 返回 `{"result_id":N,"file_name":"某某证券2026年第三季度报告.pdf","status":"pending"}`；
  2. 文件落盘至 `./data/FILE/某某证券2026年第三季度报告.pdf`；
  3. DB 新记录 `status='pending'`、`file_type='pdf'`、`recheck_from IS NULL`。

#### TC-B-02 不支持的扩展名被拒
- 优先级：P0
- 步骤：
  1. 上传 `test.exe`。
- 预期：
  1. 返回 `code="5001"`，`message="不支持的文件类型：exe"`；
  2. 不落盘、不产生校验记录。

#### TC-B-03 超过文件大小上限被拒
- 优先级：P2
- 步骤：
  1. 上传大于 104857600 字节（100MB）的文件。
- 预期：
  1. 返回 `code="5001"`，`message="文件大小超过最大限制"`；
  2. 不产生记录。
- 备注：断言依赖 `UploadFile.size` 有值；若当前 Starlette 版本返回 `None`，实际会以 TypeError 落入 5001，需同步核对依赖版本。

#### TC-B-04 同名文件重推生成新记录并标记复检来源
- 优先级：P0
- 前置：TC-B-01 已生成记录 id=X。
- 步骤：
  1. 再次上传**同名** PDF（内容为修正版）；
  2. 查询新记录与旧记录。
- 预期：
  1. 返回**新的** `result_id`=Y（Y>X），`status="pending"`；
  2. 新记录 `recheck_from = X`；
  3. 旧记录 X 仍存在，`status` 不变、`recheck_from` 不变；
  4. 列表页（默认 latest_only）只显示新记录，并带「复检」标识。
- 备注：匹配条件仅按 `file_name`，未限定 `project_id`（见第 6 节差异 4）。

#### TC-B-05 不同文件名推送不标记复检
- 优先级：P1
- 步骤：
  1. 上传另一个不同名的 PDF。
- 预期：
  1. 新记录 `recheck_from IS NULL`；
  2. 列表页不显示「复检」标签。

#### TC-B-06 未登记项目也可收文件，触发校验时被拒
- 优先级：P1
- 步骤：
  1. 以 `project_id=NOT_EXIST` 上传合法 PDF；
  2. 对该记录 `POST /api/v1/ai-check/results/{id}/check`。
- 预期：
  1. 步骤 1 入库成功，`status="pending"`（接入层不校验项目存在性）；列表 `project_name` 为 `null`，前端显示 `—`；
  2. 步骤 2 返回 `code="5001"`，`message="关联的项目数据不存在，无法校验"`，记录仍为 `pending`。

#### TC-B-07 非 PDF 但扩展名在白名单内的文件可入库
- 优先级：P1
- 步骤：
  1. 上传 `说明.txt`（`ALLOWED_FILE_EXTENSIONS` 含 txt）；
  2. 触发校验。
- 预期：
  1. 步骤 1 入库成功，`file_type="txt"`、`status="pending"`；
  2. 步骤 2 校验失败，`status="error"`，`error_msg` 非空（PyPDFLoader 解析异常）。
- 备注：需求 §4.2 定位为「PDF 文字版」，实现沿用现有上传白名单放行，非 PDF 在解析阶段才暴露，属第 6 节差异 2。

#### TC-B-08 同名重推会覆盖物理文件（历史记录读取新内容）
- 优先级：P1
- 前置：记录 X 已校验为 `success`（文件 v1）。
- 步骤：
  1. 同名重推修正版 v2（金额/日期与 v1 不同）；
  2. 对**旧记录 X** 再次触发校验；
  3. 查看 X 的 `check_detail` 中金额/日期取值。
- 预期：
  1. 旧记录 X 读取到的是**v2 的内容**（`file_path` 指向同一路径，被写入覆盖）；
  2. X 的 `check_detail` 随 v2 结果变化。
- 备注：**已知风险**，见第 6 节差异 3。当前设计未按版本落盘，复检留痕以 new 记录为准；若业务要求历史可复现，需按版本号命名文件，属待确认项。

---

### 4.3 模块 C：校验列表与明细

#### TC-C-01 列表默认每项目只取最新一条
- 优先级：P0
- 前置：项目甲有 2 条记录（id 1、4），项目乙有 2 条（id 2、3）。
- 步骤：
  1. `GET /api/v1/ai-check/results`（默认 `page=1&page_size=10&latest_only=true`）。
- 预期：
  1. `total=2`，`items` 为 id=4 与 id=3 两条；
  2. 每条含 `project_name`（左连接 `zd_project_info`）、`file_name`、`status`、`recheck_from`、`create_date`、`update_date`。

#### TC-C-02 latest_only=false 返回全部历史
- 优先级：P0
- 步骤：
  1. `GET /api/v1/ai-check/results?latest_only=false`。
- 预期：
  1. `total=4`，按 `create_date` 倒序返回全部记录；
  2. 不改变任何记录状态。

#### TC-C-03 状态筛选在「每项目最新」之后生效
- 优先级：P1
- 前置：项目甲最新记录为 `success`，历史记录为 `failed`。
- 步骤：
  1. `GET /api/v1/ai-check/results?status=failed`（默认 latest_only=true）。
- 预期：
  1. 返回结果中**不含**项目甲（其最新记录是 success）；
  2. 仅当某项目最新记录本身为 failed 时才命中。
- 备注：实现为先按 `max(id) group by project_id` 取最新，再对结果过滤 `status`；若业务期望「按项目维度看历史失败」，需显式传 `latest_only=false`，属第 6 节差异 8。

#### TC-C-04 按项目筛选与分页
- 优先级：P1
- 前置：项目甲有 3 条历史。
- 步骤：
  1. `GET /api/v1/ai-check/results?project_id=P2026Q3-001&latest_only=false&page=2&page_size=2`。
- 预期：
  1. `total=3`，`items` 长度 1（第 3 条）；
  2. 所有项 `project_id` 均为 `P2026Q3-001`。

#### TC-C-05 明细接口返回完整结构与比对明细
- 优先级：P0
- 前置：存在一条已完成的校验记录 id=N。
- 步骤：
  1. `GET /api/v1/ai-check/results/N`。
- 预期：
  1. 返回字段：`result_id`、`project_id`、`file_name`、`file_path`、`file_type`、`status`、`check_detail`、`recheck_from`、`error_msg`、`create_date`、`update_date`、`project_name`、`project`；
  2. `check_detail` 含四个键：`disclosure_date`、`amount`、`discloser`、`title`；
  3. 每个键的结构为 `{"pdf":…,"db":…,"result":"MATCH|MISMATCH|SKIP","reason":"…"}`；
  4. `project` 为比对基准数据（year/month/quarter_type/amount/discloser）。

#### TC-C-06 明细记录不存在
- 优先级：P1
- 步骤：
  1. `GET /api/v1/ai-check/results/99999999`。
- 预期：
  1. `code="5001"`，`message="校验记录不存在"`。

#### TC-C-07 翻页越界返回空列表
- 优先级：P2
- 步骤：
  1. `GET /api/v1/ai-check/results?page=99&page_size=10`。
- 预期：
  1. `items=[]`，`total` 仍为真实总数（不报错）。

---

### 4.4 模块 D：手动触发校验与并发控制

#### TC-D-01 正常触发：立即返回、异步完成
- 优先级：P0
- 前置：记录 id=N 为 `pending`，文件与项目均存在，至少一条规则启用。
- 步骤：
  1. `POST /api/v1/ai-check/results/N/check`；
  2. 轮询 `GET /results/N`。
- 预期：
  1. 步骤 1 立即返回 `{"result_id":N,"status":"in_progress"}`；
  2. 轮询期间可见 `in_progress`，最终变为 `success` / `failed` / `error` 之一；
  3. `update_date` 更新，`check_detail` 落库（error 除外）。

#### TC-D-02 校验中重复触发被拒
- 优先级：P0
- 前置：记录处于 `in_progress`（用 30 页以上 PDF 或模型限速拉长执行时间）。
- 步骤：
  1. 再次 `POST /results/N/check`。
- 预期：
  1. 返回 `code="5001"`，`message="校验进行中，请勿重复触发"`；
  2. 已在进行中的任务不受影响，最终正常落库。
- 备注：若首个任务已完成，第二次请求会合法地重新校验，属时序问题；执行时需确认状态仍为 `in_progress`。

#### TC-D-03 关联文件不存在被拒
- 优先级：P0
- 前置：记录 id=N 为 `pending`；手动删除 `./data/FILE/` 下对应文件。
- 步骤：
  1. `POST /results/N/check`。
- 预期：
  1. `code="5001"`，`message="关联的披露文件不存在"`；
  2. 记录状态保持 `pending`，不进入 `in_progress`。

#### TC-D-04 项目数据缺失被拒
- 优先级：P0
- 前置：记录 id=N 的文件存在；删除 `zd_project_info` 中对应 project_id 的记录。
- 步骤：
  1. `POST /results/N/check`。
- 预期：
  1. `code="5001"`，`message="关联的项目数据不存在，无法校验"`；
  2. 状态保持 `pending`。

#### TC-D-05 无启用规则时拒绝触发
- 优先级：P0
- 前置：四条规则全部 `enabled=0`；记录 id=N 为 `pending`。
- 步骤：
  1. `POST /results/N/check`；
  2. 查询记录状态与 `update_date`。
- 预期：
  1. `code="5001"`，`message="请先启用至少一条校验规则"`；
  2. 状态仍 `pending`，`update_date` 不变（未被抢占）。
- 备注：前置检查发生在条件 UPDATE 之前，[startCheck](file:///e:/PythonProject/PythonProject/ZhiDaAl/service/aiCheckCoreService.py#L44-L80)。

#### TC-D-06 校验记录不存在
- 优先级：P1
- 步骤：
  1. `POST /api/v1/ai-check/results/99999999/check`。
- 预期：
  1. `code="5001"`，`message="校验记录不存在"`。

#### TC-D-07 并发触发只有一个成功（条件更新抢占）
- 优先级：P0
- 前置：记录 id=N 为 `pending`，文件为大样本以保证执行期足够长。
- 步骤：
  1. 用脚本并发发起 10 个 `POST /results/N/check`（同一时刻）。
- 预期：
  1. **恰好 1 个**返回 `{"result_id":N,"status":"in_progress"}`；
  2. 其余 9 个返回 `code="5001"`、`message="校验进行中，请勿重复触发"`；
  3. 最终只有一次校验结果落库，`check_detail` 不为多次拼接。
- 备注：互斥由 `UPDATE … WHERE status!='in_progress'` 的 rowcount 保证，多进程部署同样有效。

#### TC-D-08 已完成记录可再次校验（重新校验）
- 优先级：P1
- 前置：记录 id=N 为 `success`。
- 步骤：
  1. `POST /results/N/check`；
  2. 轮询至结束。
- 预期：
  1. 允许触发，状态重新走 `in_progress → success/failed/error`；
  2. 新结果**覆盖**旧 `check_detail`，`update_date` 更新；
  3. 不生成新记录（区别于同名重推）。

---

### 4.5 模块 E：PDF 抽取与四规则比对（端到端）

> 每条用例：推送样本 PDF → 触发校验 → 轮询至结束 → 断言 `status` 与 `check_detail` 各字段。执行前复位规则（全启用、容差 0.01）。

#### TC-E-01 四字段全部一致
- 优先级：P0
- 前置：项目 `P2026Q3-001`（2026/Q3、120000000.00、某某证券股份有限公司）；一致样本 PDF（标题与文件名主干相同、披露日期 2026-08-28、金额 1.2 亿元、披露人 某某证券）。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `status="success"`；
  2. `disclosure_date.result="MATCH"`，`pdf={"year":2026,"quarter":3}`；
  3. `amount.result="MATCH"`，`pdf=120000000.0`；
  4. `discloser.result="MATCH"`（归一化后一致）；
  5. `title.result="MATCH"`，`db` 为去掉 `.pdf` 的文件名；
  6. `error_msg` 为 NULL。

#### TC-E-02 披露季度不一致
- 优先级：P0
- 前置：PDF 正文写「2026年第二季度」。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `status="failed"`；
  2. `disclosure_date.result="MISMATCH"`，`reason="披露年月季度与业务数据不一致"`，`pdf={"year":2026,"quarter":2}`、`db={"year":2026,"quarter":3}`；
  3. 其余启用规则按样本实际结果判定。

#### TC-E-03 金额单位换算后一致
- 优先级：P0
- 前置：PDF 金额写「1.2亿元」，项目金额 120000000.00。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `amount.result="MATCH"`，`pdf=120000000`（统一换算为元）；
  2. `status="success"`（其余规则均一致时）。
- 备注：抽取精度依赖模型；若 `pdf` 出现 1.2e8 或带单位字符串，说明提示词约束失效，记缺陷。

#### TC-E-04 金额超出容差
- 优先级：P0
- 前置：PDF 金额「1.3亿元」，项目 120000000.00，容差 0.01。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `amount.result="MISMATCH"`；
  2. `reason` 形如「金额相差 10000000.00 元，超出容差 0.01 元」；
  3. `status="failed"`。

#### TC-E-05 披露人归一化后一致
- 优先级：P0
- 前置：PDF 披露人写「某某证券（带首尾空格/全角空格）」，项目为`某某证券股份有限公司`。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `discloser.result="MATCH"`；
  2. `pdf` 保留原文，`db` 为「某某证券股份有限公司」。

#### TC-E-06 披露人不做别名/模糊匹配
- 优先级：P1
- 前置：PDF 披露人写「某某证券公司」。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `discloser.result="MISMATCH"`，`reason="披露人归一化后仍不一致"`；
  2. `status="failed"`。

#### TC-E-07 公告标题与文件名主干一致
- 优先级：P0
- 前置：文件名为 `某某证券2026年第三季度报告.pdf`，PDF 标题原文为「某某证券2026年第三季度报告」。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `title.result="MATCH"`；
  2. `db="某某证券2026年第三季度报告"`（已去扩展名）。

#### TC-E-08 标题存在字符/标点差异判不一致
- 优先级：P1
- 前置：文件名 `某某证券2026年第三季度报告.pdf`，PDF 标题写「某某证券2026年第3季度报告」（阿拉伯数字）。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `title.result="MISMATCH"`，`reason="公告标题与文件名不一致"`；
  2. `status="failed"`。

#### TC-E-09 停用规则记 SKIP 且不影响整体结论
- 优先级：P0
- 前置：停用「金额」规则；项目金额与 PDF 金额**故意不一致**；其余字段一致。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `check_detail.amount= {"result":"SKIP","reason":"规则未启用"}`；
  2. `status="success"`（SKIP 不参与整体判定）；
  3. 前端明细抽屉金额行显示「未比对」，结果标签为「未启用」。

#### TC-E-10 PDF 中未提取到字段
- 优先级：P0
- 前置：样本 PDF 正文完全不出现披露人。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `discloser.pdf=null`、`result="MISMATCH"`、`reason="PDF 中未提取到该字段"`；
  2. `status="failed"`，**不是** `error`。

#### TC-E-11 业务数据字段为空
- 优先级：P1
- 前置：项目 `discloser` 为 NULL（或空串），PDF 有披露人。
- 步骤：
  1. 推送并触发校验。
- 预期：
  1. `discloser.result="MISMATCH"`，`reason="业务数据中该字段为空"`；
  2. `disclosure_date` 的 db 为 NULL 时同理，reason 为「业务数据中该字段为空」。

#### TC-E-12 金额中文大写与千分位解析
- 优先级：P1
- 前置：PDF 金额写「壹亿贰仟万元」或「120,000,000.00 元」。
- 步骤：
  1. 分别用两个样本各执行一次。
- 预期：
  1. 两次 `amount.pdf` 均为 120000000，`result="MATCH"`；
  2. 若失败，先确认模型抽取值，再判定是抽取问题而非比对问题。

---

### 4.6 模块 F：异常、状态机与重置

#### TC-F-01 损坏 PDF 标记校验异常
- 优先级：P0
- 前置：`损坏样本.pdf`（txt 改扩展名）已入库。
- 步骤：
  1. 触发校验，等待结束。
- 预期：
  1. `status="error"`，`error_msg` 非空（含 PDF 解析错误信息）；
  2. `check_detail` 为 NULL（首次校验）；
  3. 其他记录不受影响。

#### TC-F-02 无文字层 PDF 标记校验异常
- 优先级：P1
- 前置：扫描件 PDF（无文字层）。
- 步骤：
  1. 触发校验。
- 预期：
  1. `status="error"`，`error_msg="PDF 内容为空或无法提取文字"`。

#### TC-F-03 模型返回非 JSON 标记校验异常
- 优先级：P1
- 前置：可执行临时测试脚本（不改动生产代码）。
- 步骤：
  1. 在 `langchain1.2` 环境执行临时脚本：`from unittest.mock import patch`，patch `service.aiCheckCoreService.extractFields` 使其返回前抛 `ValueError("字段抽取失败：模型未返回 JSON")`，或直接 patch `extract_chain.invoke` 返回「抱歉，无法提取」；
  2. 调用 `runCheck(result_id)`；
  3. 查询记录。
- 预期：
  1. `status="error"`，`error_msg` 含「字段抽取失败」；
  2. 该用例验证异常兜底，不经过 HTTP 接口。

#### TC-F-04 JSON 字段级缺失应判不一致而非异常
- 优先级：P0
- 前置：同上，临时脚本。
- 步骤：
  1. patch `extractFields` 仅返回 `{"title":"<文件名主干>","year":2026,"quarter":3,"amount":120000000.0,"discloser":null}`；
  2. 调用 `runCheck(result_id)` 后查询。
- 预期：
  1. `status="failed"`（不是 `error`）；
  2. `discloser.result="MISMATCH"`，`reason="PDF 中未提取到该字段"`；
  3. 缺失字段不触发 `error_msg`。

#### TC-F-05 异常原因落库与恢复后清空
- 优先级：P0
- 前置：TC-F-01 产生的 `error` 记录 X。
- 步骤：
  1. 同名重推一份正常 PDF 生成新记录 Y；
  2. 对 Y 触发校验并等待完成。
- 预期：
  1. X 的 `error_msg` 保留（历史留痕）；
  2. Y 校验成功后 `status="success"`、`error_msg IS NULL`。

#### TC-F-06 重置仅对「校验中」生效
- 优先级：P0
- 步骤：
  1. 分别对 `pending`、`success`、`failed`、`error` 记录调用 `POST /api/v1/ai-check/results/{id}/reset`。
- 预期：
  1. 均返回 `code="5001"`，`message="仅校验中的记录可重置"`；
  2. 记录状态不变。

#### TC-F-07 卡死的校验中记录可重置恢复
- 优先级：P0
- 前置：模拟进程中断——触发校验后立即杀进程（或 DB 手工把某记录置 `in_progress` 并写入 `error_msg`）。
- 步骤：
  1. 重启服务；
  2. `POST /results/{id}/reset`；
  3. 再次触发校验。
- 预期：
  1. 重置返回 `{"result_id":N,"status":"pending"}`；
  2. `error_msg` 被清空；
  3. 记录可再次触发并正常完成。

#### TC-F-08 复检闭环：修正重推 → 新记录 → 校验成功
- 优先级：P0
- 前置：记录 X 为 `failed`（如金额不一致）。
- 步骤：
  1. 上游修正 PDF 后**同名**重推，生成记录 Y；
  2. 查询 Y：`recheck_from == X`、`status="pending"`；
  3. 触发 Y 校验并等待完成；
  4. 查看列表（默认 latest_only）与明细历史。
- 预期：
  1. Y 校验为 `success`；
  2. 列表该项目只展示 Y，并带「复检」标识；
  3. 明细抽屉「该项目校验历史」含 X 与 Y 两条，状态分别为不一致/一致；
  4. X 的状态与 `check_detail` 不被修改。

#### TC-F-09 异常重跑保留上一次比对明细（待确认）
- 优先级：P2
- 前置：记录 X 为 `success` 且已有 `check_detail`。
- 步骤：
  1. 破坏关联文件（或 patch 抽取抛错）；
  2. 对 X 再次触发校验，等待结束。
- 预期：
  1. `status="error"`，`error_msg` 有值；
  2. `check_detail` 仍为上一次成功明细（异常分支只更新状态与错误信息）。
- 备注：是否符合预期需产品确认；若要求异常时清空明细，需调整 [runCheck](file:///e:/PythonProject/PythonProject/ZhiDaAl/service/aiCheckCoreService.py#L83-L124)，属第 6 节差异 7。

---

### 4.7 模块 G：校验规则配置

#### TC-G-01 启动预置四条规则
- 优先级：P0
- 前置：服务首次启动（`initRules()` 执行）。
- 步骤：
  1. `GET /api/v1/ai-check/rules`。
- 预期：
  1. 返回 4 条，按 id 升序；
  2. `field_name` 分别为 `disclosure_date / amount / discloser / title`；
  3. `compare_type` 分别为 `quarter_match / amount_diff / name_normalized / string_exact`；
  4. `enabled=1`；`amount.tolerance=0.01`，其余为 `null`。

#### TC-G-02 规则开关即时生效
- 优先级：P0
- 前置：admin token；记录 id=N 为 `pending`。
- 步骤：
  1. `PUT /api/v1/ai-check/rules/{amount_rule_id}/enabled?enabled=0`；
  2. `GET /rules` 确认；
  3. 触发 N 的校验。
- 预期：
  1. 返回 `{"id":…,"enabled":0,"tolerance":0.01}`；
  2. 规则列表 `enabled=0`；
  3. 本次校验 `amount` 为 `SKIP`，不参与整体结论。

#### TC-G-03 enabled 非法值被拒
- 优先级：P1
- 步骤：
  1. `PUT /rules/{id}/enabled?enabled=2`。
- 预期：
  1. 返回 `code="5001"`，`message="enabled 仅支持 0 或 1"`；
  2. 参数为非数字（如 `enabled=abc`）时返回 HTTP 422（FastAPI 校验），不进入业务。

#### TC-G-04 规则不存在
- 优先级：P1
- 步骤：
  1. `PUT /rules/999999/enabled?enabled=1`。
- 预期：
  1. `code="5001"`，`message="规则不存在"`。

#### TC-G-05 金额容差修改后参与判定
- 优先级：P0
- 前置：构造 PDF 与业务金额差 0.30 元的样本（或直接用 H-06 验证算法边界）。
- 步骤：
  1. `PUT /rules/{amount_id}/enabled?enabled=1&tolerance=0.5`；
  2. 触发校验。
- 预期：
  1. 返回 `tolerance=0.5`；
  2. `amount.result="MATCH"`；
  3. 将容差改回 0.01 后再校验，同一数据为 `MISMATCH`。
- 备注：端到端受抽取精度限制，金额精确到分建议以 H-06 为准；本用例主要验证配置链路生效。

#### TC-G-06 非金额规则传 tolerance 被忽略
- 优先级：P2
- 步骤：
  1. `PUT /rules/{disclosure_date_id}/enabled?enabled=1&tolerance=5`。
- 预期：
  1. 返回 `tolerance=null`；
  2. DB 该规则 `tolerance` 仍为 NULL。

#### TC-G-07 容差为负被拒
- 优先级：P1
- 步骤：
  1. `PUT /rules/{amount_id}/enabled?enabled=1&tolerance=-1`。
- 预期：
  1. `code="5001"`，`message="tolerance 必须为非负数值"`；
  2. 原容差不变。

#### TC-G-08 规则开关不改变已完成记录
- 优先级：P1
- 前置：记录 X 已完成 `success`。
- 步骤：
  1. 停用「金额」规则；
  2. 查看 X 的 `check_detail` 与 `status`。
- 预期：
  1. X 的明细与状态不变（`amount.result` 仍为原值）；
  2. 仅后续触发的校验使用新开关。

---

### 4.8 模块 H：判定算法单元用例（不依赖模型）

> 直接调用 `service.aiCheckCoreService` 中的纯函数，规避 LLM 噪声。执行方式：在 `langchain1.2` 环境进入仓库根目录，运行临时脚本或 `python -c`：

```python
from decimal import Decimal
from types import SimpleNamespace
from service.aiCheckCoreService import (
    parseJson, normalizeName, compareAll, compareQuarter,
    compareAmount, compareDiscloser, compareTitle,
)
```

#### TC-H-01 parseJson 剥离代码块围栏
- 优先级：P0
- 步骤：
  1. `parseJson('```json\n{"year":2026}\n```')`；
  2. `parseJson('抽取结果：{"year":2026} 完毕')`。
- 预期：
  1. 两次均返回 `{"year":2026}`。

#### TC-H-02 parseJson 非法输入抛错
- 优先级：P0
- 步骤：
  1. `parseJson('无法提取')`；
  2. `parseJson('{"a": 1,}')`。
- 预期：
  1. 步骤 1 ValueError，文案「字段抽取失败：模型未返回 JSON」；
  2. 步骤 2 ValueError，文案以「字段抽取失败：JSON 解析错误」开头。

#### TC-H-03 normalizeName 长后缀优先剥离
- 优先级：P0
- 步骤：依次调用 `normalizeName`：
  1. `某某证券股份有限公司`
  2. `某某证券有限责任公司`
  3. `某某证券有限公司`
  4. `某某证券股份公司`
- 预期：
  1. 前三者均返回 `某某证券`；
  2. 第 4 个因不是受支持后缀，返回原串（不做模糊处理）。

#### TC-H-04 normalizeName 去除空格与首尾空白
- 优先级：P1
- 步骤：
  1. `normalizeName(' 某某 证券\u3000股份有限公司 ')`。
- 预期：
  1. 返回 `某某证券`（半角空格、全角空格、首尾空白均被清理）。

#### TC-H-05 compareQuarter 缺失分支
- 优先级：P1
- 步骤：
  1. `compareQuarter({"year":None,"quarter":None},{"year":2026,"quarter":3})`；
  2. `compareQuarter({"year":2026,"quarter":3},{"year":2026,"quarter":None})`。
- 预期：
  1. 步骤 1 `result="MISMATCH"`，`reason="PDF 中未提取到该字段"`；
  2. 步骤 2 `reason="业务数据中该字段为空"`。

#### TC-H-06 compareAmount 容差边界
- 优先级：P0
- 前置：`rule = SimpleNamespace(field_name="amount", compare_type="amount_diff", tolerance=Decimal("0.01"), enabled=1)`。
- 步骤：
  1. `compareAmount({"amount":100.01},{"amount":Decimal("100.00")},rule)`；
  2. `compareAmount({"amount":100.02},{"amount":Decimal("100.00")},rule)`；
  3. `compareAmount({"amount":100.00},{"amount":Decimal("100.00")},SimpleNamespace(tolerance=None))`。
- 预期：
  1. 步骤 1 `MATCH`（差值等于容差，判定为一致）；
  2. 步骤 2 `MISMATCH`，`reason` 含「金额相差 0.02 元，超出容差 0.01 元」；
  3. 步骤 3 使用默认容差 0.01，返回 `MATCH`。

#### TC-H-07 compareDiscloser 归一化与大小写
- 优先级：P1
- 步骤：
  1. `compareDiscloser({"discloser":"某某证券"},{"discloser":"某某证券股份有限公司"})`；
  2. `compareDiscloser({"discloser":"ABC"},{"discloser":"abc"})`。
- 预期：
  1. 步骤 1 `MATCH`；
  2. 步骤 2 `MISMATCH`（不做大小写归一）。

#### TC-H-08 compareTitle 扩展名与空白处理
- 优先级：P1
- 步骤：
  1. `compareTitle({"title":"某某证券2026年第三季度报告"}, "某某证券2026年第三季度报告.pdf")`；
  2. `compareTitle({"title":" 某某证券2026年第三季度报告 "}, "某某证券2026年第三季度报告.pdf")`；
  3. `compareTitle({"title":"某某证券2026年第三季度报告（修订版）"}, "某某证券2026年第三季度报告.pdf")`。
- 预期：
  1. 步骤 1、2 为 `MATCH`；
  2. 步骤 3 为 `MISMATCH`，`db` 为不带扩展名的主干。

#### TC-H-09 compareAll 整体状态聚合
- 优先级：P0
- 前置：两条规则：金额启用且一致、标题停用。
- 步骤：
  1. 调用 `compareAll([amount_rule, title_rule_disabled], extracted, project_values, file_name)`；
  2. 将 amount 规则改为启用且数据不一致，再次调用。
- 预期：
  1. 步骤 1：`detail.title={"result":"SKIP","reason":"规则未启用"}`，整体 `status="success"`；
  2. 步骤 2：整体 `status="failed"`。

#### TC-H-10 readPdfText 空内容与截断
- 优先级：P1
- 前置：准备无文字层 PDF 与正文 4 万字符 PDF。
- 步骤：
  1. 对无文字 PDF 调用 `readPdfText`；
  2. 对超长 PDF 调用 `readPdfText`。
- 预期：
  1. 步骤 1 抛 `ValueError("PDF 内容为空或无法提取文字")`；
  2. 步骤 2 返回字符串长度恰为 30000（截断上限）。

---

### 4.9 模块 I：前端（手工 UI）

> 前置：后端已启动、前端 dev server 已启动，账号已登录；页面路由 `/ai-check`。

#### TC-I-01 列表展示与状态标识
- 优先级：P0
- 步骤：
  1. 进入 `/ai-check`，默认停留在「校验列表」Tab。
- 预期：
  1. 表格列：项目名称、项目ID、披露文件、状态、推送时间、校验时间、操作；
  2. 五类状态分别显示「待校验/校验中/一致/不一致/校验异常」标签；
  3. `recheck_from` 非空的记录在状态旁显示「复检」标签；
  4. 项目名称为空显示 `—`。

#### TC-I-02 状态筛选与刷新
- 优先级：P1
- 步骤：
  1. 状态下拉选择「不一致」；
  2. 点击「刷新」；
  3. 清空筛选。
- 预期：
  1. 请求携带 `status=failed`，列表仅剩不一致记录（遵循 TC-C-03 口径）；
  2. 清空后恢复全部，分页回到第 1 页。

#### TC-I-03 校验按钮文案与禁用态
- 优先级：P0
- 步骤：
  1. 观察 `pending`、`success/failed/error`、`in_progress` 三类记录的操作列。
- 预期：
  1. `pending` 显示「开始校验」；
  2. 已完成记录显示「重新校验」；
  3. `in_progress` 记录按钮禁用，并额外出现「重置」按钮。

#### TC-I-04 校验中自动轮询并自动停止
- 优先级：P0
- 步骤：
  1. 点击某条记录的「开始校验」；
  2. 打开 DevTools Network 观察请求。
- 预期：
  1. 立即提示「校验已在后台开始」，行状态变为「校验中」；
  2. 每 3s 自动刷新列表（有抽屉打开时同时刷新明细）；
  3. 所有记录离开 `in_progress` 后停止轮询，无多余请求。

#### TC-I-05 明细抽屉字段渲染
- 优先级：P0
- 步骤：
  1. 打开一条 `failed` 记录的「明细」。
- 预期：
  1. 顶部展示项目名称、项目ID、披露文件、整体状态、校验时间；
  2. 逐字段表固定四行（披露日期/金额/披露人/公告标题）；
  3. PDF 侧为 null 显示「未提取到」，业务侧为空显示「为空」，规则停用显示「未比对」；
  4. 金额格式为 `¥ 120,000,000.00`，披露日期格式为 `2026 年 Q3`；
  5. 不一致行结果标签为红色「不一致」，原因列展示文案。

#### TC-I-06 明细抽屉历史记录切换
- 优先级：P1
- 步骤：
  1. 在抽屉底部「该项目校验历史」点击另一条记录。
- 预期：
  1. 请求 `latest_only=false&project_id=…`，历史按时间倒序；
  2. 点击后抽屉内容切换为该记录明细，不重新打开抽屉。

#### TC-I-07 异常记录展示异常原因
- 优先级：P0
- 步骤：
  1. 打开一条 `error` 记录的明细。
- 预期：
  1. 显示红色「异常原因」与后端 `error_msg` 全文；
  2. `check_detail` 为空时四行显示「未参与本次校验」，不报前端异常。

#### TC-I-08 重置操作
- 优先级：P0
- 步骤：
  1. 对 `in_progress` 记录点击「重置」；
  2. 取消一次，再确认一次。
- 预期：
  1. 弹出二次确认「将记录重置为『待校验』？…」；
  2. 取消不发请求；确认后调用 reset，提示「已重置为待校验」，列表刷新且状态回「待校验」。

#### TC-I-09 规则配置开关与容差
- 优先级：P0
- 步骤：
  1. 切到「规则配置」Tab；
  2. 切换「披露人」开关；
  3. 修改金额容差为 0.50 后失焦。
- 预期：
  1. 四行规则：校验字段、比对方式（中文描述）、金额容差、启用；
  2. 开关调用 PUT 后提示「披露人规则已停用/启用」，行状态即时变更；
  3. 容差仅金额行可编辑（步长 0.01、精度 2、最小 0），保存提示「金额容差已保存」。

#### TC-I-10 分页
- 优先级：P1
- 步骤：
  1. 列表总数超过 10 条时切换第 2 页。
- 预期：
  1. 分页组件 total 与后端 `total` 一致；
  2. 请求携带 `page=2&page_size=10`，表格内容更新。

#### TC-I-11 离开页面停止轮询
- 优先级：P2
- 步骤：
  1. 校验中停留在页面，随后切换到其他路由。
- 预期：
  1. 定时器被清理（`onBeforeUnmount`），离开后不再发起轮询请求。

---

### 4.10 模块 J：初始化、部署与权限

#### TC-J-01 规则预置幂等
- 优先级：P0
- 步骤：
  1. 连续重启服务两次；
  2. `SELECT COUNT(*) FROM zd_ai_check_rule`。
- 预期：
  1. 计数恒为 4；
  2. 已有规则的 id、开关、容差均不被重置。

#### TC-J-02 表结构字段齐全
- 优先级：P0
- 步骤：
  1. `DESC zd_ai_check_result`、`DESC zd_ai_check_rule`、`DESC zd_project_info`。
- 预期：
  1. `zd_ai_check_result` 含 `check_detail JSON`、`recheck_from INT NULL`、`error_msg TEXT`；
  2. `zd_ai_check_rule` 含 `tolerance DECIMAL(20,2) NULL`；
  3. `zd_project_info.amount` 为 `DECIMAL(20,2)`，非 Float。

#### TC-J-03 PDF 解析依赖可用
- 优先级：P0
- 步骤：
  1. `E:\conda\envs\langchain1.2\python.exe -c "import pypdf; from langchain_community.document_loaders import PyPDFLoader; print(pypdf.__version__)"`。
- 预期：
  1. 无导入错误，输出版本号（当前环境 7.1.1）。

#### TC-J-04 相对路径与启动目录约束
- 优先级：P1
- 步骤：
  1. 从仓库根目录启动服务，推送 PDF，查看 `file_path`；
  2. 从其他目录启动服务并触发校验。
- 预期：
  1. `file_path` 形如 `./data/FILE/xxx.pdf`（相对路径）；
  2. 换目录启动后，旧记录触发校验报「关联的披露文件不存在」。
- 备注：部署脚本必须固定工作目录为项目根目录。

#### TC-J-05 推送与规则开关的权限边界
- 优先级：P0
- 步骤：
  1. 带 admin JWT（无 `X-Api-Key`）调用 `POST /projects`；
  2. 无凭证调用同一接口；
  3. 业务员调用 `PUT /rules/{id}/enabled`。
- 预期：
  1. 步骤 1 返回 403/4030（key_only 分组）；
  2. 步骤 2 返回 401/4010；
  3. 步骤 3 返回 403/4030（仅 admin）。
- 备注：详细准入口径见《统一网关测试案例文档》TC-E-05、TC-D-07。

#### TC-J-06 查看类接口两类角色均可用
- 优先级：P1
- 步骤：
  1. 业务员分别调用 `GET /results`、`GET /results/{id}`、`GET /rules`、`GET /projects`。
- 预期：
  1. 均正常返回业务数据，不出现 401/403；
  2. 密钥访问同一组接口同样放行。

#### TC-J-07 前端构建通过
- 优先级：P2
- 步骤：
  1. `frontend/` 下执行 `npm run build`。
- 预期：
  1. 构建成功，无 lint/类型错误导致的中断。

---

## 5. 通过标准与缺陷处理

### 5.1 发布通过标准

- P0 用例 100% 通过；P1 用例通过率 ≥ 95%（未通过项需有明确风险说明）；
- 模块 H（判定算法）全部通过——该模块不依赖模型，是四条规则口径的判定基准；
- 状态机闭环完整：`pending → in_progress → success/failed/error`，且「校验中」互斥、可重置；
- 复检闭环（TC-F-08）与历史留痕可用；
- 权限边界（TC-J-05）与统一网关一致，无回归。

### 5.2 缺陷处理建议

- 按「模块 + 场景 + 期望行为」命名缺陷，如「E-比对-金额差值等于容差被判不一致」；
- 区分三类问题：**判定错误**（比对逻辑，最高优先级）、**状态机错误**（并发/流转）、**抽取质量问题**（模型能力，记录命中率与样本）；
- 第 6 节列出的实现差异需在发布前由业务/技术确认口径，确认后同步更新对应用例预期。

---

## 6. 实现差异与待确认项

| 编号 | 事项 | 当前实现 | 影响与建议 |
|---|---|---|---|
| 1 | 成功响应无统一信封 | 接口直接返回业务 JSON，仅异常返回 `{code:"5001"}`；HTTP 恒 200 | 与设计 §4「统一返回 Response」不一致；前端已按裸 JSON 解析，用例按现状断言 |
| 2 | 非 PDF 扩展名放行 | 沿用 `ALLOWED_FILE_EXTENSIONS`（含 txt/json/md），非 PDF 可入库，校验时才报错 | 需求 §4.2 定位为 PDF 文字版；建议接入层增加 PDF 类型校验或明确「按现有上传链路约定」 |
| 3 | 同名重推覆盖物理文件 | 文件按文件名落盘，历史记录 `file_path` 指向同一路径 | 历史记录无法复现被校验时的文件内容（TC-B-08）；建议按版本命名或留存快照 |
| 4 | `recheck_from` 全局按文件名匹配 | 查询条件仅 `file_name`，不含 `project_id` | 跨项目同名文件可能误关联；若文件名全局唯一（合规约定）可接受，需确认 |
| 5 | 前端轮询周期 | 3s（`AiCheckView.vue` `ensurePoll`） | 设计文档写 2s，属实现与文档偏差，不影响功能 |
| 6 | 异常时保留旧明细 | `runCheck` 异常分支只更新 `status/error_msg`，不覆盖 `check_detail` | 重跑异常后前端仍展示上一次明细（TC-F-09），需确认是否清空 |
| 7 | 状态筛选顺序 | 先取每项目最新记录，再按 `status` 过滤 | 项目历史中的失败记录在默认视图不可见（TC-C-03），业务需知悉 |
| 8 | 文件推送不校验项目存在性 | `saveCheckFile` 直接入库，不校验 `zd_project_info` | 产生「有文件无项目」记录（TC-B-06），触发时以明确文案拦截，可接受但建议接入层提示 |

待确认项（沿用需求 §6 并补充）：

1. 历史校验是否要求可复现被校验的文件版本（决定差异 3 的处理方式）；
2. 非 PDF 扩展名是否允许入库（差异 2）；
3. 异常重跑是否清空旧明细（差异 6）；
4. 金额容差默认 ±0.01 元是否符合业务实际。

---

## 7. 附录：用例编号索引

| 模块 | 编号范围 | 用例数 | 覆盖需求/设计章节 |
|---|---|---|---|
| A 结构化数据接入 | TC-A-01 ~ TC-A-09 | 9 | 需求 §4.1、设计 §3.1/§4 |
| B 文件接入与复检 | TC-B-01 ~ TC-B-08 | 8 | 需求 §4.2/§4.7、设计 §7 |
| C 列表与明细 | TC-C-01 ~ TC-C-07 | 7 | 需求 §4.8、设计 §4 |
| D 触发与并发 | TC-D-01 ~ TC-D-08 | 8 | 需求 §4.3、设计 §4.1/§5 |
| E 抽取与四规则比对 | TC-E-01 ~ TC-E-12 | 12 | 需求 §4.4/§4.5/§5.1、设计 §5.1/§6 |
| F 异常与状态机 | TC-F-01 ~ TC-F-09 | 9 | 需求 §3.3/§5.2/§5.4、设计 §5 |
| G 规则配置 | TC-G-01 ~ TC-G-08 | 8 | 需求 §4.6、设计 §3.3/§8.3 |
| H 判定算法单元 | TC-H-01 ~ TC-H-10 | 10 | 设计 §6 |
| I 前端 | TC-I-01 ~ TC-I-11 | 11 | 需求 §4.8、设计 §8 |
| J 初始化部署与权限 | TC-J-01 ~ TC-J-07 | 7 | 设计 §3/§9、网关权限矩阵 |

合计 **89 条用例**（P0 为主干，H 模块为无模型依赖的判定基准）。
