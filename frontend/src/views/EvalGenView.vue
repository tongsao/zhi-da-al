<template>
  <div class="page-container">

    <div class="page-header">
      <div>
        <h2 class="page-title">生成评估</h2>
        <p class="page-desc">逐题走生产问答链路（hybridRetrieve 检索 + 生成提示词 + temperature=0）生成答案，再由裁判模型按事实正确性 / 要点完整性 / 忠于资料三维打分，每题满分 2 分。页面只展示最新一次评测的结果。</p>
      </div>
    </div>

    <!-- 控制栏 -->
    <div class="control-bar card" style="padding: 16px 20px; margin-bottom: 16px;">
      <div class="control-left">
        <span class="control-label">评测条数上限</span>
        <el-input-number v-model="limit" :min="1" :max="testsetSize || undefined" :step="5" size="large" style="width:120px" />
        <span class="control-label" style="margin-left: 12px;">TopK</span>
        <el-input-number v-model="topK" :min="1" :max="10" size="large" style="width:140px" />
        <span class="control-hint">评测集共 {{ testsetSize || '…' }} 条，逐题约 40 秒，本次约需 {{ estimateMinutes }} 分钟</span>
      </div>
      <div class="control-right">
        <el-button v-if="auth.isAdmin" type="primary" size="large" :loading="running" :disabled="running || rerunning" @click="onRun">
          <el-icon v-if="!running"><VideoPlay /></el-icon>
          {{ running ? '评测中...' : '开始评测' }}
        </el-button>
      </div>
    </div>

    <!-- 后台评测进度（重跑复用同一张卡） -->
    <div v-if="running || rerunning" class="card" style="padding: 20px; margin-bottom: 16px;">
      <div class="history-header">
        <h3 class="section-title">{{ progressLabel }}</h3>
        <span class="progress-count">{{ progress.done }} / {{ progress.total }}</span>
      </div>
      <el-progress :percentage="progressPct" :stroke-width="10" :show-text="false" />
      <p class="control-hint" style="margin-top: 10px;">{{ running ? '评测在后台运行，可离开本页，回来会接着显示进度。' : '重跑在后台运行，结果会覆盖到当前批次的对应题。' }}</p>
    </div>

    <transition name="fade">
      <div v-if="result" class="result-area">

        <!-- 三维均分卡 -->
        <div class="metrics-row">
          <div v-for="m in metricCards" :key="m.label" class="metric-card card">
            <div class="metric-value" :style="{ color: m.color }">{{ m.value }}</div>
            <div class="metric-label">{{ m.label }}</div>
            <div class="metric-rate">满分率 {{ m.rateText }}</div>
            <div class="metric-desc">{{ m.desc }}</div>
          </div>
        </div>

        <!-- 逐题明细 -->
        <div class="card" style="padding: 20px;">
          <div class="history-header">
            <h3 class="section-title">逐题明细（{{ fmtTime(result.created_at) }} · TopK={{ result.top_k }} · 耗时 {{ result.elapsed_seconds }}s）</h3>
            <div class="detail-actions">
              <span class="control-hint">{{ validCount }} 题有效 / {{ result.records.length }} 题</span>
              <el-button
                plain size="small"
                :disabled="running || rerunning || !rateFailedRows.length"
                @click="onSelectFailed"
              >选中限流失败（{{ rateFailedRows.length }}）</el-button>
              <el-button
                v-if="auth.isAdmin"
                type="primary" plain size="small"
                :disabled="!selectedRows.length || running || rerunning"
                @click="onRerun(selectedRows.map(r => r.index))"
              >重跑选中（{{ selectedRows.length }}）</el-button>
            </div>
          </div>
          <el-table ref="tableRef" :data="result.records" row-key="index" stripe style="width: 100%"
                    @selection-change="onSelectChange">
            <el-table-column type="selection" width="46" :selectable="() => !running && !rerunning" />
            <el-table-column prop="index" label="#" width="50" />
            <el-table-column prop="q" label="问题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="category" label="类别" width="110" />
            <el-table-column label="难度" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="{ easy: 'success', medium: 'warning', hard: 'danger' }[row.difficulty]">
                  {{ row.difficulty }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="正确性" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="scoreType(row.correctness)">{{ row.correctness ?? '—' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="完整性" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="scoreType(row.completeness)">{{ row.completeness ?? '—' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="忠实度" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="scoreType(row.faithfulness)">{{ row.faithfulness ?? '—' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="扣分原因" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.error" class="fail-text">{{ row.error }}</span>
                <span v-else-if="isFull(row)" class="pass-text">满分项，无扣分</span>
                <span v-else>{{ row.reason }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button v-if="auth.isAdmin" link type="primary" :disabled="running || rerunning" @click="onRerun([row.index])">重跑</el-button>
              </template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="expand-detail">
                  <template v-if="row.error">
                    <p class="detail-label">评测失败</p>
                    <p class="detail-text fail-text">{{ row.error }}</p>
                  </template>
                  <template v-else>
                    <p class="detail-label">标准答案</p>
                    <p class="detail-text">{{ row.golden }}</p>
                    <p class="detail-label">生成答案（生产链路实测输出）</p>
                    <p class="detail-text">{{ row.generated }}</p>
                    <p class="detail-label">扣分原因</p>
                    <p class="detail-text">{{ row.reason }}</p>
                  </template>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

      </div>

      <div v-else-if="!running && !rerunning" class="card empty-result">
        <div class="empty-state">
          <div class="empty-icon">
            <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
              <rect width="56" height="56" rx="16" fill="#f0f2f5"/>
              <path d="M18 20h20M18 28h14M18 36h17" stroke="#d1d5db" stroke-width="2" stroke-linecap="round"/>
              <circle cx="40" cy="40" r="10" fill="#fff" stroke="#d1d5db" stroke-width="2"/>
              <path d="M37 40h6M40 37v6" stroke="#d1d5db" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <p class="empty-title">尚未运行生成评估</p>
          <p class="empty-desc">设置评测条数后点击「开始评测」，逐题跑生产问答链路并由裁判模型打分。</p>
        </div>
      </div>
    </transition>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay } from '@element-plus/icons-vue'
import { startGenEval, rerunGenEval, listGenRuns, getGenRun, getTestsetSize } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

// 三维评分口径与后端裁判 prompt 一致
const DIMENSIONS = [
  { key: 'correctness', label: '事实正确性', color: '#5b8def', desc: '2=完全正确，1=部分错误，0=事实错误' },
  { key: 'completeness', label: '要点完整性', color: '#34d399', desc: '2=要点齐全，1=遗漏部分要点，0=严重遗漏' },
  { key: 'faithfulness', label: '忠于资料', color: '#8b5cf6', desc: '2=无编造，1=轻微推断，0=有编造内容' },
]

// 评测条数上限默认取测试集全量，进页面时从后端拉取（不写死）
const testsetSize = ref(0)
const limit = ref(0)
const topK = ref(6)          // 与问答页请求的默认 TopK 一致，保证评的就是线上效果
const running = ref(false)
const rerunning = ref(false)
const result = ref(null)
const progress = ref({ done: 0, total: 0 })
const tableRef = ref(null)
const selectedRows = ref([])
let pollTimer = null
let runId = null             // 页面当前跟踪的那次评测
let pollMode = 'batch'       // batch=整批评测（进度取库里 done/total）/ rerun=重跑（进度取 detail 里的 rerun）
let rerunFailed = 0          // 上一轮重跑的失败题数，rerun 字段消失后靠它出提示

const progressLabel = computed(() => running.value ? '评测进行中' : '重跑进行中')

const estimateMinutes = computed(() => Math.max(1, Math.round(limit.value * 40 / 60)))
const progressPct = computed(() =>
  progress.value.total ? Math.round(progress.value.done / progress.value.total * 100) : 0)
const validCount = computed(() => (result.value?.records || []).filter(r => r.correctness != null).length)

// 限流失败判定：后端把 429 等异常以字符串记在 error 字段，按常见文案识别
const isRateLimitError = (text) => {
  const s = String(text || '')
  return /429|rate\s*limit|速率限制|请求频率/.test(s)
}
const rateFailedRows = computed(() =>
  (result.value?.records || []).filter(r => isRateLimitError(r.error)))

const onSelectFailed = () => {
  tableRef.value?.clearSelection()
  rateFailedRows.value.forEach(row => tableRef.value?.toggleRowSelection(row, true))
}

const metricCards = computed(() => {
  if (!result.value) return []
  const r = result.value
  return DIMENSIONS.map(d => ({
    ...d,
    value: r[`${d.key}_avg`] != null ? `${Number(r[`${d.key}_avg`]).toFixed(2)} / 2.0` : '—',
    rateText: r[`${d.key}_full_rate`] != null ? `${(r[`${d.key}_full_rate`] * 100).toFixed(0)}%` : '—',
  }))
})

const scoreType = (v) => v === 2 ? 'success' : v === 1 ? 'warning' : v === 0 ? 'danger' : 'info'
const isFull = (row) => row.correctness === 2 && row.completeness === 2 && row.faithfulness === 2
const fmtTime = (s) => s ? String(s).replace('T', ' ').slice(0, 19) : '—'

const onSelectChange = (rows) => { selectedRows.value = rows }

// 批次详情落到页面上，detail 统一映射成 records
const applyRun = (run) => {
  result.value = { ...run, records: run.detail || [] }
}

const showRun = async (id) => {
  applyRun(await getGenRun(id))
}

// 本页只认表里最新写入的那次：在跑就接着轮询，跑完就渲染它，失败则只提示原因
const loadLatest = async () => {
  try {
    const { items } = await listGenRuns({ page: 1, page_size: 1 })
    if (!items.length) return

    const newest = items[0]
    if (newest.status === 'running') {
      startPoll(newest.id, newest.total, newest.done)
    } else if (newest.status === 'success') {
      await showRun(newest.id)
      // 重跑不写库，进度在详情里，刷新页面后照样接着显示
      if (result.value?.rerun) {
        startPoll(newest.id, result.value.rerun.total, result.value.rerun.done, 'rerun')
      }
    } else {
      ElMessage.error('最近一次评测失败：' + (newest.error_msg || '未知错误'))
    }
  } catch { /* 错误提示由响应拦截器统一处理 */ }
}

const stopPoll = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  running.value = false
  rerunning.value = false
}

// mode=batch 跑整批，进度取批次行的 done/total；mode=rerun 只跑几题，进度取详情里的 rerun 字段
const startPoll = (id, total, done = 0, mode = 'batch') => {
  runId = id
  pollMode = mode
  progress.value = { done, total }
  running.value = mode === 'batch'
  rerunning.value = mode === 'rerun'
  pollTimer = setInterval(async () => {
    try {
      const run = await getGenRun(runId)

      if (pollMode === 'rerun') {
        if (run.rerun) {
          progress.value = { done: run.rerun.done, total: run.rerun.total }
          rerunFailed = (run.rerun.failed || []).length
          return
        }
        stopPoll()
        applyRun(run)
        tableRef.value?.clearSelection()
        if (rerunFailed) {
          ElMessage.warning(`重跑完成，其中 ${rerunFailed} 题失败（已记为失败并重算统计），详见明细`)
        } else {
          ElMessage.success(`重跑完成，已更新到批次 #${run.id}`)
        }
        return
      }

      progress.value = { done: run.done, total: run.total }
      if (run.status === 'running') return

      stopPoll()
      if (run.status === 'success') {
        applyRun(run)
        ElMessage.success(`评测完成：${run.total} 题，耗时 ${run.elapsed_seconds}s`)
      } else {
        ElMessage.error('评测失败：' + (run.error_msg || '未知错误'))
      }
    } catch {
      // 轮询本身失败（如后端重启）就停下，别每 3 秒刷一次错误提示
      stopPoll()
    }
  }, 3000)
}

const onRun = async () => {
  try {
    const started = await startGenEval({ limit: limit.value, top_k: topK.value })
    result.value = null
    startPoll(started.run_id, started.total)
    ElMessage.info({ message: `评测已在后台开始（${started.total} 题），可离开本页`, duration: 4000 })
  } catch {
    // 常见失败：已有评测进行中，原因由响应拦截器提示
  }
}

// 重跑指定题：不新建批次，结果显示在当前这批里，所以 target 就是页面正在看的 result.id
const onRerun = async (indexes) => {
  if (!result.value || !indexes.length) return
  const id = result.value.id
  try {
    const started = await rerunGenEval(id, indexes)
    rerunFailed = 0
    startPoll(id, started.total, 0, 'rerun')
    ElMessage.info({
      message: `正在重跑 ${started.total} 题（批次 TopK=${started.top_k}），结果会覆盖到批次 #${id}`,
      duration: 4000,
    })
  } catch {
    // 常见失败：已有评测在跑，原因由响应拦截器提示
  }
}

onMounted(async () => {
  try {
    testsetSize.value = (await getTestsetSize()).count
    limit.value = testsetSize.value  // 默认全量
  } catch { /* 后端不可用时保持默认值 */ }

  await loadLatest()
})

onBeforeUnmount(stopPoll)
</script>

<style scoped>
/* ===== 控制栏 ===== */
.control-bar { display: flex; align-items: center; justify-content: space-between; }
.control-left { display: flex; align-items: center; gap: 12px; }
.control-label { font-size: 13px; color: var(--color-text-secondary); font-weight: 500; }
.control-hint { font-size: 12px; color: var(--color-text-muted); }

/* ===== 指标卡片 ===== */
.metrics-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
.metric-card { padding: 20px; }
.metric-value { font-size: 26px; font-weight: 700; line-height: 1.1; margin-bottom: 4px; }
.metric-label { font-size: 13px; font-weight: 500; color: var(--color-text-primary); margin-bottom: 4px; }
.metric-rate { font-size: 12px; color: var(--color-text-secondary); margin-bottom: 4px; }
.metric-desc { font-size: 11px; color: var(--color-text-muted); }

/* ===== 区块头 ===== */
.section-title { font-size: 14px; font-weight: 600; color: var(--color-text-primary); }
.history-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.detail-actions { display: flex; align-items: center; gap: 12px; }
.progress-count { font-size: 13px; font-weight: 600; color: #5b8def; }

/* ===== 逐题明细 ===== */
.expand-detail { padding: 4px 16px 8px 48px; }
.detail-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin: 8px 0 4px; }
.detail-text { font-size: 13px; color: var(--color-text-primary); line-height: 1.7; margin: 0; white-space: pre-wrap; }
.pass-text { color: #34d399; }
.fail-text { color: #f87171; }

/* ===== 空状态 ===== */
.empty-result { padding: 0; }
.empty-title { font-size: 16px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 8px; }
.empty-desc { font-size: 13px; color: var(--color-text-secondary); text-align: center; max-width: 380px; }
</style>
