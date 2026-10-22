import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/', redirect: '/qa', meta: { requiresAuth: true } },
  // 公开页：未登录可访问
  { path: '/login', component: () => import('@/views/LoginView.vue') },
  // 半公开：需登录但无角色限制；未改密时所有请求都会到这里（守卫强制）
  { path: '/force-change-password', component: () => import('@/views/ForceChangePasswordView.vue'), meta: { requiresAuth: true } },
  { path: '/qa', component: () => import('@/views/QaView.vue'), meta: { requiresAuth: true, title: '智能问答' } },
  { path: '/documents', component: () => import('@/views/DocumentsView.vue'), meta: { requiresAuth: true, title: '知识库管理' } },
  { path: '/kb', component: () => import('@/views/KbView.vue'), meta: { requiresAuth: true, title: '知识库维护' } },
  { path: '/eval', redirect: '/eval/hit-rate', meta: { requiresAuth: true } },
  { path: '/eval/hit-rate', component: () => import('@/views/EvalView.vue'), meta: { requiresAuth: true, title: '回答命中率 hit_rate' } },
  // 召回率与 MRR 同属检索质量，合并为一页
  { path: '/eval/retrieval', component: () => import('@/views/EvalRetrievalView.vue'), meta: { requiresAuth: true, title: '检索评估' } },
  { path: '/eval/gen', component: () => import('@/views/EvalGenView.vue'), meta: { requiresAuth: true, title: '生成评估' } },
  { path: '/eval/manual', component: () => import('@/views/ManualEvalView.vue'), meta: { requiresAuth: true, title: '人工测评分析' } },
  // 系统管理（仅 admin）
  { path: '/users', component: () => import('@/views/UserManageView.vue'), meta: { requiresAuth: true, roles: ['admin'], title: '用户管理' } },
  { path: '/api-keys', component: () => import('@/views/ApiKeyView.vue'), meta: { requiresAuth: true, roles: ['admin'], title: '密钥管理' } },
  { path: '/audit', component: () => import('@/views/AuditView.vue'), meta: { requiresAuth: true, roles: ['admin'], title: '审计查询' } },
  { path: '/usage', component: () => import('@/views/UsageView.vue'), meta: { requiresAuth: true, roles: ['admin'], title: '用量看板' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 登录态守卫：未登录 → /login；未改密强制改密；管理页校验角色
router.beforeEach((to) => {
  const auth = useAuthStore()

  if (!to.meta.requiresAuth) return true

  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.path === '/login') return { path: '/qa' }
  // 凭证有效但需先改密：除改密页外一律拦截
  if (auth.mustChangePassword && to.path !== '/force-change-password') {
    return { path: '/force-change-password' }
  }
  // 已改密用户访问改密页无意义，回默认页
  if (to.path === '/force-change-password' && !auth.mustChangePassword) {
    return { path: '/qa' }
  }
  // 按钮级显隐靠前端，路由级仍做角色兜底（后端权限才是安全边界）
  if (to.meta.roles && !to.meta.roles.includes(auth.user?.role)) {
    ElMessage.warning('无权限访问')
    return { path: '/qa' }
  }
  return true
})

export default router