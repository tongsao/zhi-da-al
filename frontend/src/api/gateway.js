// 网关管理 API 封装：认证 / 用户 / 密钥 / 审计 / 用量。
// 复用 index.js 的 axios 实例（已统一处理错误码与响应解包），这里只做路径与参数映射。
import request from './index'

// ===== 认证 =====
export const gatewayApi = {
  // 登录；成功返回 { token, user:{id,username,role,display_name,must_change_password} }
  login: ({ username, password }) =>
    request.post('/auth/login', { username, password }),

  // 修改密码；成功即需重新登录（会话仅一次调用，改完前端自动登出）
  changePassword: ({ old_password, new_password }) =>
    request.post('/auth/change-password', { old_password, new_password }),

  // 当前用户信息（刷新页面后校验登录态用）
  me: () =>
    request.get('/auth/me'),

  // ===== 用户管理（admin）=====
  listUsers: (params) =>
    request.get('/users', { params }),

  createUser: (body) =>
    request.post('/users', body),

  // body: { is_active?, reset_password? }
  patchUser: (id, body) =>
    request.patch(`/users/${id}`, body),

  // ===== 密钥管理（admin）=====
  listApiKeys: () =>
    request.get('/api-keys'),

  // body: { key_name, ip_whitelist: [], expires_at? }；成功 data.api_key 为明文（仅此一次）
  createApiKey: (body) =>
    request.post('/api-keys', body),

  // body: { is_active?, expires_at? }
  patchApiKey: (id, body) =>
    request.patch(`/api-keys/${id}`, body),

  // 轮换；成功 data.api_key 为新明文（旧明文立即失效）
  rotateApiKey: (id) =>
    request.post(`/api-keys/${id}/rotate`),

  // ===== 审计（admin）=====
  // params: { caller_type?, caller_id?, path?, status?, start?, end?, page, page_size }
  listAudit: (params) =>
    request.get('/audit', { params }),

  // ===== 用量（admin）=====
  usageToday: () =>
    request.get('/usage/today'),

  usageTrend: (days = 90) =>
    request.get('/usage/trend', { params: { days } }),
}

export default gatewayApi