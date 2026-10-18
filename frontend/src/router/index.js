import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/qa' },
  { path: '/qa', component: () => import('@/views/QaView.vue'), meta: { title: '智能问答' } },
  { path: '/documents', component: () => import('@/views/DocumentsView.vue'), meta: { title: '知识库管理' } },
  { path: '/kb', component: () => import('@/views/KbView.vue'), meta: { title: '知识库维护' } },
  { path: '/eval', redirect: '/eval/hit-rate' },
  { path: '/eval/hit-rate', component: () => import('@/views/EvalView.vue'), meta: { title: '回答命中率 hit_rate' } },
  // 召回率与 MRR 同属检索质量，合并为一页
  { path: '/eval/retrieval', component: () => import('@/views/EvalRetrievalView.vue'), meta: { title: '检索评估' } },
  { path: '/eval/gen', component: () => import('@/views/EvalGenView.vue'), meta: { title: '生成评估' } },
  { path: '/eval/manual', component: () => import('@/views/ManualEvalView.vue'), meta: { title: '人工测评分析' } }
]

export default createRouter({
  history: createWebHistory(),
  routes
})