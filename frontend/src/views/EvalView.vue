<template>
  <div class="page-container">

    <div class="page-header">
      <div>
        <h2 class="page-title">效果评测</h2>
        <p class="page-desc">用预置评测集验证 RAG 检索与生成效果，量化召回命中率。</p>
      </div>
    </div>

    <!-- 控制栏 -->
    <div class="control-bar card" style="padding: 16px 20px; margin-bottom: 16px;">
      <div class="control-left">
        <span class="control-label">评测条数上限</span>
        <el-input-number v-model="limit" :min="1" :max="testsetSize || undefined" :step="5" size="large" style="width:120px" />
        <span class="control-label" style="margin-left: 12px;">TopK</span>
        <el-input-number v-model="topK" :min="1" :max="10" size="large" style="width:140px" />
        <span class="control-hint">评测集共 {{ testsetSize || '…' }} 条，全量（含 LLM 问答）约需 1-2 分钟</span>
      </div>
      <div class="control-right">
        <el-button v-if="auth.isAdmin" type="primary" size="large" :loading="running" :disabled="running" @click="onRun">
          <el-icon v-if="!running"><VideoPlay /></el-icon>
          {{ running ? '评测中...' : '开始评测' }}
        </el-button>
      </div>
    </div>

    <!-- 结果展示 -->
    <transition name="fade">
      <div v-if="result" class="result-area">

        <!-- 核心指标卡片 -->
        <div class="metrics-row">
          <div v-for="m in metricCards" :key="m.label" class="metric-card card animate-in">
            <div class="metric-top">
              <span class="metric-icon" :style="{ color: m.color }">
                <el-icon :size="20"><component :is="m.icon" /></el-icon>
              </span>
              <span class="metric-change" :class="m.changeClass">
                {{ m.change }}
              </span>
            </div>
            <div class="metric-value" :style="{ color: m.color }">{{ m.value }}</div>
            <div class="metric-label">{{ m.label }}</div>
            <div class="metric-desc">{{ m.desc }}</div>
          </div>
        </div>

        <!-- 评分进度条 -->
        <div class="score-section card" style="padding: 24px; margin-bottom: 16px;">
          <h3 class="section-title">综合评分</h3>
          <div class="score-display">
            <div class="score-ring-wrap">
              <svg width="120" height="120" viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="50" fill="none" stroke="var(--color-border)" stroke-width="10"/>
                <circle
                  cx="60" cy="60" r="50" fill="none"
                  :stroke="scoreColor"
                  stroke-width="10"
                  stroke-linecap="round"
                  :stroke-dasharray="`${scoreCircumference}`"
                  :stroke-dashoffset="`${scoreOffset}`"
                  transform="rotate(-90 60 60)"
                  style="transition: stroke-dashoffset 1s ease"/>
                <text x="60" y="55" text-anchor="middle" font-size="22" font-weight="700" fill="var(--color-text-primary)">
                  {{ scoreText }}
                </text>
                <text x="60" y="72" text-anchor="middle" font-size="11" fill="var(--color-text-muted)">
                  回答命中率
                </text>
              </svg>
            </div>
            <div class="score-bars">
              <div v-for="d in difficultyBars" :key="d.name" class="score-bar-item">
                <div class="score-bar-label">
                  <span>{{ d.name }}</span>
                  <span class="score-bar-val">{{ d.passed }}/{{ d.total }}</span>
                </div>
                <el-progress :percentage="d.pct" :color="d.color" :show-text="false" :stroke-width="8"/>
              </div>
            </div>
          </div>
        </div>

        <!-- 逐条明细 -->
        <div class="card" style="padding: 20px; margin-bottom: 16px;">
          <h3 class="section-title">逐条明细</h3>
          <el-table :data="result.results" stripe style="width: 100%">
            <el-table-column prop="index" label="#" width="50" />
            <el-table-column prop="q" label="问题" min-width="220" show-overflow-tooltip />
            <el-table-column prop="category" label="类别" width="130" />
            <el-table-column label="难度" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="{ easy: 'success', medium: 'warning', hard: 'danger' }[row.difficulty]">
                  {{ row.difficulty }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="结果" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.passed ? 'success' : 'danger'">
                  {{ row.passed ? '命中' : '未命中' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="命中词" min-width="140">
              <template #default="{ row }">
                <span v-if="row.hit_keywords?.length" class="hit-kw">{{ row.hit_keywords.join(' / ') }}</span>
                <span v-else class="hit-kw miss">无</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ (row.latency_ms / 1000).toFixed(1) }}s</template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="expand-detail">
                  <p class="detail-label">标准答案</p>
                  <p class="detail-text">{{ row.answer }}</p>
                  <p class="detail-label">模型回答</p>
                  <p class="detail-text">{{ row.model_answer || row.error || '（无返回）' }}</p>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 原始数据 -->
        <div class="card" style="padding: 20px;">
          <div class="raw-data-header">
            <h3 class="section-title">原始数据</h3>
            <el-button text size="small" @click="showRaw = !showRaw">
              {{ showRaw ? '收起' : '展开' }}
            </el-button>
          </div>
          <transition name="expand">
            <div v-if="showRaw" class="raw-json">
              <pre>{{ JSON.stringify(result, null, 2) }}</pre>
            </div>
          </transition>
        </div>

      </div>

      <!-- 空状态 -->
      <div v-else class="card empty-result">
        <div class="empty-state">
          <div class="empty-icon">
            <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
              <rect width="56" height="56" rx="16" fill="#f0f2f5"/>
              <path d="M18 20h20M18 28h14M18 36h17" stroke="#d1d5db" stroke-width="2" stroke-linecap="round"/>
              <circle cx="40" cy="40" r="10" fill="#fff" stroke="#d1d5db" stroke-width="2"/>
              <path d="M37 40h6M40 37v6" stroke="#d1d5db" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <p class="empty-title">尚未运行评测</p>
          <p class="empty-desc">设置评测条数后点击「开始评测」，查看 RAG 系统的召回效果。</p>
        </div>
      </div>
    </transition>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { runEval, listEvalRuns, getEvalRun, getTestsetSize } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { TrendCharts, Timer, Document, CircleCheck, VideoPlay } from '@element-plus/icons-vue'

const auth = useAuthStore()

const limit = ref(30)
const topK = ref(6)
const running = ref(false)
const result = ref(null)
const showRaw = ref(false)
// 测试集条数，进页面时从后端拉取（评测条数上限不写死）
const testsetSize = ref(0)

onMounted(async () => {
  try {
    testsetSize.value = (await getTestsetSize()).count
    // 默认跑前 30 条，测试集不足 30 条时对齐全量
    if (limit.value > testsetSize.value) limit.value = testsetSize.value
  } catch { /* 后端不可用时保持默认值 */ }
})

// 综合评分（满分 100，基于 hit_rate）
const scoreText = computed(() => {
  if (!result.value) return '—'
  return Math.round(result.value.hit_rate * 100)
})
const scoreColor = computed(() => {
  const v = result.value?.hit_rate ?? 0
  if (v >= 0.8) return '#34d399'
  if (v >= 0.5) return '#5b8def'
  return '#f87171'
})
const scoreCircumference = 2 * Math.PI * 50  // ≈ 314
const scoreOffset = computed(() => {
  const pct = (result.value?.hit_rate ?? 0)
  return scoreCircumference * (1 - pct)
})

const DIFF_COLORS = { easy: '#34d399', medium: '#f59e0b', hard: '#f87171' }
const difficultyBars = computed(() => {
  if (!result.value) return []
  return Object.entries(result.value.by_difficulty || {}).map(([name, s]) => ({
    name,
    total: s.total,
    passed: s.passed,
    pct: +(s.passed / s.total * 100).toFixed(1),
    color: DIFF_COLORS[name] || '#5b8def'
  }))
})

const metricCards = computed(() => {
  if (!result.value) return []
  const r = result.value
  return [
    {
      icon: TrendCharts, color: scoreColor.value,
      value: (r.hit_rate * 100).toFixed(1) + '%',
      label: '回答命中率',
      desc: '答案命中标准关键词的比例',
      change: '', changeClass: ''
    },
    {
      icon: CircleCheck, color: '#22c55e',
      value: `${r.passed}/${r.total}`,
      label: '命中条数',
      desc: '本次评测通过的条数',
      change: '', changeClass: ''
    },
    {
      icon: Timer, color: '#f97316',
      value: r.avg_latency_ms ? (r.avg_latency_ms / 1000).toFixed(1) + ' s' : '—',
      label: '平均响应耗时',
      desc: '单条问答端到端耗时',
      change: '', changeClass: ''
    },
    {
      icon: Document, color: '#5b8def',
      value: r.top_k,
      label: 'TopK',
      desc: '检索召回的文档片段数',
      change: '', changeClass: ''
    },
  ]
})

const onRun = async () => {
  running.value = true
  result.value = null
  try {
    // mode=full：LLM 问答（hit_rate）+ 检索指标（recall/MRR）一起算并存库
    result.value = await runEval({ limit: limit.value, top_k: topK.value, mode: 'full' })
    ElMessage.success({ message: `评测完成，命中 ${result.value.passed}/${result.value.total} 条`, duration: 3000 })
  } catch (e) {
    ElMessage.error('评测失败：' + (e?.data?.message || e.message))
  } finally {
    running.value = false
  }
}

// 进页面时自动渲染最近一次完整评测（无历史时保持空状态提示）
// 接口明细字段叫 detail，模板表格绑定的是 results，取回后统一改名
const loadLatest = async () => {
  try {
    const fullRuns = (await listEvalRuns({ run_type: 'full' })).items
    if (fullRuns.length) {
      const run = await getEvalRun(fullRuns[0].id)
      result.value = { ...run, results: run.detail }
    }
  } catch { /* 无历史或接口失败时静默保持空状态 */ }
}
loadLatest()
</script>

<style scoped>
/* ===== 控制栏 ===== */
.control-bar { display: flex; align-items: center; justify-content: space-between; }
.control-left { display: flex; align-items: center; gap: 12px; }
.control-label { font-size: 13px; color: var(--color-text-secondary); font-weight: 500; }
.control-hint { font-size: 12px; color: var(--color-text-muted); }

/* ===== 指标卡片 ===== */
.metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 16px; }
.metric-card { padding: 20px; }
.metric-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.metric-icon {}
.metric-value { font-size: 28px; font-weight: 700; line-height: 1.1; margin-bottom: 4px; }
.metric-label { font-size: 13px; font-weight: 500; color: var(--color-text-primary); margin-bottom: 4px; }
.metric-desc { font-size: 11px; color: var(--color-text-muted); }

/* ===== 评分区 ===== */
.section-title { font-size: 14px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 16px; }
.score-display { display: flex; align-items: center; gap: 40px; }
.score-ring-wrap { flex-shrink: 0; }
.score-bars { flex: 1; display: flex; flex-direction: column; gap: 16px; }
.score-bar-item {}
.score-bar-label { display: flex; justify-content: space-between; font-size: 12px; color: var(--color-text-secondary); margin-bottom: 6px; }
.score-bar-val { font-weight: 600; color: var(--color-text-primary); }

/* ===== 逐条明细 ===== */
.hit-kw { font-size: 12px; color: var(--color-text-secondary); }
.hit-kw.miss { color: var(--color-text-muted); }
.expand-detail { padding: 4px 16px 8px 48px; }
.detail-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin: 8px 0 4px; }
.detail-text { font-size: 13px; color: var(--color-text-primary); line-height: 1.7; margin: 0; }

/* ===== 原始数据 ===== */
.raw-data-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.raw-json pre {
  background: #1a1f36; color: #e5e7eb; padding: 16px; border-radius: var(--radius-md);
  font-family: var(--font-mono); font-size: 12px; line-height: 1.7; overflow-x: auto;
}

/* ===== 空状态 ===== */
.empty-result { padding: 0; }
.empty-state { display: flex; flex-direction: column; align-items: center; padding: 60px 24px; }
.empty-icon { margin-bottom: 16px; }
.empty-title { font-size: 16px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 8px; }
.empty-desc { font-size: 13px; color: var(--color-text-secondary); text-align: center; max-width: 360px; }

/* ===== 展开动画 ===== */
.expand-enter-active, .expand-leave-active { transition: all var(--transition-base); overflow: hidden; }
.expand-enter-from, .expand-leave-to { opacity: 0; max-height: 0; }
.expand-enter-to, .expand-leave-from { opacity: 1; max-height: 800px; }
</style>
