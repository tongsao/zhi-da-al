import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

// 网关要求 JWT 鉴权；登录态失效统一由响应拦截器兜底跳转
request.interceptors.request.use((config) => {
  const token = useAuthStore().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 后端统一响应结构：{ code, message, data }
// 中间件拒绝带真实 HTTP 状态（401/403/423/429），业务错误为 HTTP 200 + 非 0 code
request.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (String(body.code) === '0') return body.data
      ElMessage.error(body.message || '业务错误')
      return Promise.reject(body)
    }
    return body
  },
  (err) => {
    // blob 请求（文件下载）出错时，错误体是 JSON 格式的 Blob，先还原再取 message/code
    let data = err?.response?.data
    const parseBlob = data instanceof Blob && data.type?.includes('json')
      ? data.text().then(t => JSON.parse(t)).catch(() => data)
      : Promise.resolve(data)
    return Promise.resolve(parseBlob).then((d) => {
      const status = err?.response?.status
      const code = d?.code
      const auth = useAuthStore()

      if (status === 401) {
        // 凭证缺失/失效/过期：清登录态回登录页（守卫对 /login 不设防，无回跳）
        ElMessage.warning(d?.message || '登录已过期，请重新登录')
        auth.logout()
        router.push('/login')
      } else if (status === 403 && code === '4031') {
        // 凭证有效但被要求先改密
        ElMessage.warning(d?.message || '请先修改初始密码')
        router.push('/force-change-password')
      } else if (status === 403) {
        ElMessage.error(d?.message || '无权限访问')
      } else if (status === 423) {
        ElMessage.error(d?.message || '账号已锁定，请稍后再试')
      } else if (status === 429) {
        ElMessage.error(code === '4291' ? '当日模型用量已用尽，请明天再试' : (d?.message || '请求过于频繁，请稍后重试'))
      } else {
        ElMessage.error(d?.message || err.message || '网络错误')
      }
      return Promise.reject(err)
    })
  }
)

// ===== 文档管理 =====
// 后端把 title/chunk_size/chunk_overlap 定义为 query 参数，文件走 multipart body
export const uploadDocument = (file, params) => {
  const fd = new FormData()
  fd.append('file', file)
  return request.post('/documents', fd, {
    params,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export const listDocuments = (params) =>
  request.get('/documents', { params })

// 详情接口已改为文档下载：返回二进制流
export const downloadDocument = (id) =>
  request.get(`/documents/${id}`, { responseType: 'blob' })

export const deleteDocument = (id) =>
  request.delete(`/documents/${id}`)

// ===== 问答 =====
// 后端把 question/conversation_id/top_k/stream 定义为 query 参数
// 图版链路串行多次模型调用，免费档偶发慢响应，超时给足 120s 避免误报（仅非流式路径生效）
export const chat = (payload) =>
  request.post('/qa/chat', null, { params: payload, timeout: 120000 })

// 流式问答（SSE）：按事件类型分发回调，返回 Promise。
// 事件协议（event 名 → data）：
//   token      {"content":"..."}              模型吐字，打字机追加
//   tool       {"tools":[...],"hint":"..."}   模型决定调工具，显示「正在查询…」
//   progress   {"stage","percent","label"}    工具内部阶段进度
//   interrupt  {"message","detail"}           需要人工审批，停止接收
//   error      {"message":"..."}              出错 / 超时
//   done       {"status":"done"}              结束（保底）
//   data: [DONE]                              流结束标记
// handlers: { onToken, onTool, onProgress, onInterrupt }
// axios 不便消费 SSE 流，这里用 fetch 读 ReadableStream 手动解析
// signal 为 AbortSignal：点「停止」时由调用方传入，abort 后读流被中断、Promise reject
export const chatStream = (payload, handlers, signal) => {
  const { onToken, onTool, onProgress, onInterrupt } = handlers || {}
  const auth = useAuthStore()
  // SSE 走 fetch 不经 axios 拦截器，Authorization 需手动带；否则中间件 401 拒绝
  return fetch(`/api/v1/qa/chat?${new URLSearchParams({ ...payload, stream: true })}`, {
    method: 'POST',
    signal,
    headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {}
  }).then(async (resp) => {
    if (resp.status === 401) {
      // SSE 的 HTTP 状态是快速失败通道：过期立即登出回登录页
      ElMessage.warning('登录已过期，请重新登录')
      auth.logout()
      router.push('/login')
      throw new Error('登录已过期，请重新登录')
    }
    if (!resp.ok || !resp.body) {
      // 非 200 尽量还原 JSON 错误体的 message
      let msg = `请求失败：HTTP ${resp.status}`
      try {
        const body = await resp.json()
        if (body?.message) msg = body.message
      } catch { /* 非 JSON 错误体（如网关 HTML）忽略 */ }
      throw new Error(msg)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    // 返回 true 表示流已终止（done / interrupt / [DONE]），不再继续读
    const parse = () => {
      let sep
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)

        let eventName = 'message'
        const dataLines = []
        for (const line of raw.split('\n')) {
          if (line.startsWith('event: ')) eventName = line.slice(7).trim()
          else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
        }
        const data = dataLines.join('\n').trim()
        if (!data) continue
        if (data === '[DONE]') return true

        let body
        try { body = JSON.parse(data) } catch { continue }

        if (eventName === 'token') { if (body.content) onToken?.(body.content) }
        else if (eventName === 'tool') onTool?.(body)
        else if (eventName === 'progress') onProgress?.(body)
        else if (eventName === 'interrupt') { onInterrupt?.(body); return true }
        else if (eventName === 'error') throw new Error(body.message || '生成失败')
        else if (eventName === 'done') return true
        else {
          // 兼容仅有 data、无 event 名的旧格式
          if (body.error) throw new Error(body.error)
          if (body.content) onToken?.(body.content)
        }
      }
      return false
    }

    const pump = async () => {
      const { done, value } = await reader.read()
      if (done) { parse(); return }
      buffer += decoder.decode(value, { stream: true })
      if (parse()) {
        try { await reader.cancel() } catch { /* 连接已断开，忽略 */ }
        return
      }
      return pump()
    }
    return pump()
  })
}

// 用户操作留痕：action = copy / usable / need_fix / unusable
export const feedback = (payload) =>
  request.post('/qa/feedback', payload)

// 人工测评分析：action 各操作数量统计
export const feedbackStats = () =>
  request.get('/qa/feedback/stats')

// 人工测评分析：留痕明细，params: { page, page_size, question, action }
export const feedbackList = (params) =>
  request.get('/qa/feedback/list', { params })

// 后端实际路径：/qa/chat/gethistory?conversation_id=
export const listMessages = (conversationId) =>
  request.get('/qa/chat/gethistory', { params: { conversation_id: conversationId } })

// 历史会话 ID 列表（后端返回 { conversation_id: [...] }，无 code 包装）
export const listConversationIds = () =>
  request.get('/qa/chat/conversation_id')

// 删除指定会话的全部消息（消息记录 + 对话上下文）
export const deleteConversation = (conversationId) =>
  request.delete('/qa/chat/conversation_id', { params: { conversation_id: conversationId } })

// 用户点「停止生成」：后端置位会话取消令牌，掐断模型上游、停止烧钱
export const stopChat = (conversationId) =>
  request.post('/qa/chat/stop', null, { params: { conversation_id: conversationId } })

// ===== 知识库维护 =====
export const kbStats = () =>
  request.get('/kb/stats')

// ===== 评测 =====
// mode=full 跑 LLM 问答约 1-2 分钟；mode=retrieval 只查向量库秒级返回。超时给足 10 分钟
export const runEval = (params = {}) =>
  request.post('/eval/run', null, { params, timeout: 600000 })

// 评测历史列表（不含每题明细），params: { run_type }
export const listEvalRuns = (params = {}) =>
  request.get('/eval/runs', { params })

// 单次评测详情（含每题明细）
export const getEvalRun = (id) =>
  request.get(`/eval/runs/${id}`)

// 跨评测汇总的逐题排名明细，按评测时间倒序分页，params: { page, page_size }
export const getEvalDetail = (params = {}) =>
  request.get('/eval/detail', { params })

// 测试集条数（评测条数上限动态渲染用）
export const getTestsetSize = () =>
  request.get('/eval/testset/size')

// ===== 生成评估（逐题生产链路问答 + 三维裁判打分，后台跑）=====
// 发起后立即返回 { run_id, total, status }，进度与结果靠 getGenRun 轮询
export const startGenEval = (params = {}) =>
  request.post('/eval/gen/run', null, { params })

// 生成评估历史列表（不含每题明细），params: { page, page_size }
export const listGenRuns = (params = {}) =>
  request.get('/eval/gen/runs', { params })

// 单次生成评估详情；status=running 时用它轮询进度（done/total）
// rerun 字段非空表示该批次正在重跑，进度看它（重跑不落库，批次行状态一直是 success）
export const getGenRun = (id) =>
  request.get(`/eval/gen/runs/${id}`)

// 重跑当前批次的指定题（indexes 为题号数组），结果覆盖回原批次，不新建批次
// 后端按 query 收逗号串：axios 会把数组参数序列化成 indexes[]=1&indexes[]=2，对不上
export const rerunGenEval = (runId, indexes) =>
  request.post(`/eval/gen/runs/${runId}/rerun`, null, { params: { indexes: indexes.join(',') } })

// ===== 健康检查 =====
export const checkHealth = () =>
  request.get('/health')

// ===== AI 质检（季报披露文件校验）=====
// 校验列表：默认每项目最新一条；latest_only=false 查历史
export const listCheckResults = (params = {}) =>
  request.get('/ai-check/results', { params })

// 单条校验明细（含逐字段比对结果）
export const getCheckResult = (id) =>
  request.get(`/ai-check/results/${id}`)

// 手动触发校验：异步执行，触发后靠 getCheckResult 轮询状态
export const triggerCheck = (id) =>
  request.post(`/ai-check/results/${id}/check`)

// 重置卡在「校验中」的记录（进程中断遗留）
export const resetCheck = (id) =>
  request.post(`/ai-check/results/${id}/reset`)

// 校验规则列表（全局一套，业务可开关）
export const listCheckRules = () =>
  request.get('/ai-check/rules')

// 规则开关；金额规则可同时提交容差 tolerance
export const updateCheckRule = (id, enabled, tolerance) =>
  request.put(`/ai-check/rules/${id}/enabled`, null, { params: { enabled, tolerance } })

// gateway.js 等模块以 request 为唯一入口复用实例
export default request