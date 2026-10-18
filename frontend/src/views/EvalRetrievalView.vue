<template>
  <div class="page-container">

    <div class="page-header">
      <div>
        <h2 class="page-title">{{ pageTitle }}</h2>
        <p class="page-desc">{{ pageDesc }}</p>
      </div>
    </div>

    <!-- 控制栏 -->
    <div class="control-bar card" style="padding: 16px 20px; margin-bottom: 16px;">
      <div class="control-left">
        <span class="control-label">评测条数上限</span>
        <el-input-number v-model="limit" :min="1" :max="testsetSize || undefined" :step="5" size="large" style="width:120px" />
        <span class="control-label" style="margin-left: 12px;">TopK</span>
        <el-input-number v-model="topK" :min="1" :max="10" size="large" style="width:140px" />
        <span class="control-hint">只检索向量库不调大模型，全量 {{ testsetSize || '…' }} 条秒级完成</span>
      </div>
      <div class="control-right">
        <el-button type="primary" size="large" :loading="running" :disabled="running" @click="onRun">
          <el-icon v-if="!running"><VideoPlay /></el-icon>
          {{ running ? '评测中...' : '开始评测' }}
        </el-button>
      </div>
    </div>

    <!-- 本次结果 -->
    <transition name="fade">
      <div v-if="result" class="result-area">

        <!-- 指标卡：主指标在前，对偶口径在后 -->
        <div class="metrics-row">
          <div v-for="m in metricCards" :key="m.label" class="metric-card card">
            <div class="metric-value" :style="{ color: m.color }">{{ m.value }}</div>
            <div class="metric-label">{{ m.label }}</div>
            <div class="metric-desc">{{ m.desc }}</div>
          </div>
        </div>

      </div>
    </transition>

    <!-- 逐题排名明细：跨评测汇总，按评测时间倒序分页 -->
    <div class="card" style="padding: 20px; margin-bottom: 16px;">
      <h3 class="section-title">逐题排名明细（跨评测汇总，最新在前）</h3>
      <el-table :data="detail.items" stripe style="width: 100%">
        <el-table-column label="评测时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.run_type === 'full' ? 'primary' : 'info'">
              {{ row.run_type === 'full' ? '完整' : '检索' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="run_id" label="run_id" width="70" />
        <el-table-column prop="index" label="#" width="50" />
        <el-table-column prop="q" label="问题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="category" label="类别" width="110" />
        <el-table-column label="难度" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="{ easy: 'success', medium: 'warning', hard: 'danger' }[row.difficulty]">
              {{ row.difficulty }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="rank_any" width="95">
          <template #default="{ row }">{{ row.ranks.rank_any || '—' }}</template>
        </el-table-column>
        <el-table-column label="rank_all" width="95">
          <template #default="{ row }">{{ row.ranks.rank_all || '—' }}</template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-detail">
              <p class="detail-label">Top{{ row.top_k }} 分块预览</p>
              <p v-for="(chunk, idx) in row.chunk_previews" :key="idx" class="detail-chunk">
                #{{ idx + 1 }} {{ chunk }}...
              </p>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="detailPage"
        v-model:page-size="detailSize"
        :page-sizes="[10, 20, 30]"
        :total="detail.total"
        layout="total, sizes, prev, pager, next"
        class="detail-pagination"
        @current-change="loadDetail"
        @size-change="onDetailSizeChange"
      />
    </div>

    <!-- 指标趋势：拉全部历史，不随下方表格分页变化 -->
    <div class="card" style="padding: 20px; margin-bottom: 16px;">
      <div class="history-header">
        <h3 class="section-title">指标趋势（全部历史，从左到右为评测时间顺序）</h3>
        <el-radio-group v-model="runType" size="small" @change="onRunTypeChange">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="full">完整</el-radio-button>
          <el-radio-button value="retrieval">检索</el-radio-button>
        </el-radio-group>
      </div>
      <div ref="trendRef" class="trend-chart"></div>
      <p v-if="!trend.length" class="detail-label">暂无数据</p>
    </div>

    <!-- 历史评测 -->
    <div class="card" style="padding: 20px;">
      <div class="history-header">
        <h3 class="section-title">历史评测（含完整评测的结果）</h3>
        <el-button text size="small" @click="reloadHistory">刷新</el-button>
      </div>
      <el-table :data="runs" stripe style="width: 100%" @expand-change="onExpand">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.run_type === 'full' ? 'primary' : 'info'">
              {{ row.run_type === 'full' ? '完整' : '检索' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="top_k" label="TopK" width="70" />
        <el-table-column prop="total" label="题数" width="70" />
        <el-table-column label="hit_rate" width="100">
          <template #default="{ row }">{{ pct(row.hit_rate) }}</template>
        </el-table-column>
        <el-table-column label="recall_any" width="110">
          <template #default="{ row }">{{ pct(row.recall_any) }}</template>
        </el-table-column>
        <el-table-column label="recall_all" width="110">
          <template #default="{ row }">{{ pct(row.recall_all) }}</template>
        </el-table-column>
        <el-table-column label="mrr_any" width="100">
          <template #default="{ row }">{{ num(row.mrr_any) }}</template>
        </el-table-column>
        <el-table-column label="mrr_all" width="100">
          <template #default="{ row }">{{ num(row.mrr_all) }}</template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-detail">
              <template v-if="detailCache[row.id]">
                <div v-for="d in detailCache[row.id].detail" :key="d.index" class="history-row">
                  <span class="history-q">{{ d.index }}. {{ d.q }}</span>
                  <span class="history-rank">rank_any={{ d.ranks.rank_any || '—' }} rank_all={{ d.ranks.rank_all || '—' }}</span>
                </div>
              </template>
              <p v-else class="detail-label">加载中...</p>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="runsPage"
        v-model:page-size="runsSize"
        :page-sizes="[30, 50, 100]"
        :total="runsTotal"
        layout="total, sizes, prev, pager, next"
        class="detail-pagination"
        @current-change="loadRuns"
        @size-change="onRunsSizeChange"
      />
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay, Aim, Odometer } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { runEval, listEvalRuns, getEvalRun, getEvalDetail, getTestsetSize } from '@/api'

const pageTitle = '检索评估'
const pageDesc = 'Recall@k：top-k 检索块中能找到答案的比例。MRR：首个相关块排名的倒数均值，排名越靠前得分越高。两者均以 rank_any（块命中任一关键词）和 rank_all（块包含全部关键词，更严格）双口径给出。'

// 评测条数上限默认取测试集全量，进页面时从后端拉取（不写死）
const testsetSize = ref(0)
const limit = ref(0)
const topK = ref(6)
const running = ref(false)
const result = ref(null)
const runs = ref([])
const runsTotal = ref(0)
const runsPage = ref(1)
const runsSize = ref(30)
const runType = ref('')       // '' 全部 / 'full' 完整 / 'retrieval' 检索，折线图与历史表共用
const detailCache = ref({})   // 已展开加载过的历史明细 { run_id: detail }
// 跨评测汇总的逐题排名明细（分页，最新评测在前）
const detail = ref({ total: 0, items: [] })
const detailPage = ref(1)
const detailSize = ref(10)
// 折线图数据源：全部历史（不分页），与表格分页相互独立
const trend = ref([])
const trendRef = ref(null)
let chart = null

// 相关键词的块比包含全部关键词的块更容易命中，所以 any 口径数值 >= all 口径
const metricCards = computed(() => {
  if (!result.value) return []
  const r = result.value
  const cards = [
    { key: 'recall_any', label: 'Recall@k（任一关键词）', desc: 'top-k 中存在命中任一关键词的块', fmt: pct, icon: Aim, color: '#34d399' },
    { key: 'recall_all', label: 'Recall@k（全部关键词）', desc: 'top-k 中存在包含全部关键词的块', fmt: pct, icon: Aim, color: '#22c55e' },
    { key: 'mrr_any', label: 'MRR（任一关键词）', desc: '首个相关块排名倒数的均值', fmt: num, icon: Odometer, color: '#5b8def' },
    { key: 'mrr_all', label: 'MRR（全部关键词）', desc: '严格口径的 MRR', fmt: num, icon: Odometer, color: '#8b5cf6' },
  ]
  return cards.map(c => ({ ...c, value: c.fmt(r[c.key]) }))
})

const pct = (v) => v != null ? (v * 100).toFixed(1) + '%' : '—'
const num = (v) => v != null ? Number(v).toFixed(4) : '—'
const fmtTime = (s) => s ? String(s).replace('T', ' ').slice(0, 19) : '—'

const loadRuns = async () => {
  try {
    const data = await listEvalRuns({ run_type: runType.value, page: runsPage.value, page_size: runsSize.value })
    runs.value = data.items
    runsTotal.value = data.total
  } catch (e) {
    ElMessage.error('加载历史失败：' + (e?.message || e))
  }
}

// 四条指标线共用同一 Y 轴：recall/mrr 都是 0~1 比率，量级可比
const METRIC_LINES = [
  { key: 'recall_any', color: '#34d399' },
  { key: 'recall_all', color: '#22c55e' },
  { key: 'mrr_any', color: '#5b8def' },
  { key: 'mrr_all', color: '#8b5cf6' },
]

const renderTrend = () => {
  if (!chart) return
  // 接口按 id 倒序返回（最新在前），折线图按时间从左到右，故反转为升序
  const rows = [...trend.value].reverse()

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const r = rows[ps[0].dataIndex]
        const head = `#${r.id} ${r.run_type === 'full' ? '完整' : '检索'} · TopK=${r.top_k} · ${r.total}题<br/>${fmtTime(r.created_at)}`
        const body = ps.map(p => `${p.marker}${p.seriesName}: ${p.value == null ? '—' : Number(p.value).toFixed(4)}`)
        return [head, ...body].join('<br/>')
      }
    },
    legend: { top: 0, data: METRIC_LINES.map(l => l.key) },
    grid: { left: 56, right: 24, top: 36, bottom: 40 },
    xAxis: { type: 'category', name: '评测序号', data: rows.map(r => '#' + r.id), axisLabel: { fontSize: 11 } },
    // scale=true 让 Y 轴自适应数据区间，避免固定 0~1 把差异压平
    yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v) => Number(v).toFixed(2) } },
    series: METRIC_LINES.map(l => ({
      name: l.key,
      type: 'line',
      data: rows.map(r => r[l.key]),
      connectNulls: true,
      symbolSize: 5,
      itemStyle: { color: l.color },
      lineStyle: { color: l.color, width: 2 },
    })),
  }, true)
}

const loadTrend = async () => {
  try {
    // page_size=0 表示不分页，一次取回全部历史供折线图使用
    trend.value = (await listEvalRuns({ run_type: runType.value, page_size: 0 })).items
    renderTrend()
  } catch (e) {
    ElMessage.error('加载趋势失败：' + (e?.message || e))
  }
}

// 刷新按钮：表格与折线图一起重拉
const reloadHistory = () => {
  loadRuns()
  loadTrend()
}

// 切换每页条数回到第一页，避免页码超出新范围
const onRunsSizeChange = () => {
  runsPage.value = 1
  loadRuns()
}

const onRunTypeChange = () => {
  runsPage.value = 1
  reloadHistory()
}

const resizeChart = () => chart?.resize()

const loadDetail = async () => {
  try {
    detail.value = await getEvalDetail({ page: detailPage.value, page_size: detailSize.value })
  } catch (e) {
    ElMessage.error('加载明细失败：' + (e?.message || e))
  }
}

// 切换每页条数时回到第一页，避免页码超出新范围
const onDetailSizeChange = () => {
  detailPage.value = 1
  loadDetail()
}

const onExpand = async (row, expandedRows) => {
  if (!expandedRows.includes(row) || detailCache.value[row.id]) return
  try {
    detailCache.value[row.id] = await getEvalRun(row.id)
  } catch (e) {
    ElMessage.error('加载明细失败：' + (e?.message || e))
  }
}

const onRun = async () => {
  running.value = true
  result.value = null
  try {
    // mode=retrieval：只查向量库，秒级返回，结果存库
    result.value = await runEval({ limit: limit.value, top_k: topK.value, mode: 'retrieval' })
    ElMessage.success({ message: `评测完成，结果已存库（run_id=${result.value.run_id}）`, duration: 3000 })
    // 新评测排在汇总明细最前，回到第一页刷新；折线图也要补上新记录
    detailPage.value = 1
    runsPage.value = 1
    await loadDetail()
    await reloadHistory()
  } catch (e) {
    ElMessage.error('评测失败：' + (e?.data?.message || e.message))
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  // 折线图容器常驻渲染，挂载即可初始化；数据到达后再 setOption
  chart = echarts.init(trendRef.value)
  window.addEventListener('resize', resizeChart)

  // 进页面时渲染最近一次检索评测结果（历史表也要加载）
  // 接口明细字段叫 detail，模板表格绑定的是 results，取回后统一改名
  try {
    testsetSize.value = (await getTestsetSize()).count
    limit.value = testsetSize.value  // 默认全量
  } catch { /* 后端不可用时保持默认值 */ }
  try {
    const retrievalRuns = (await listEvalRuns({ run_type: 'retrieval' })).items
    if (retrievalRuns.length) {
      const run = await getEvalRun(retrievalRuns[0].id)
      result.value = { ...run, results: run.detail }
    }
  } catch { /* 无历史时静默保持空状态 */ }
  await loadDetail()
  await loadRuns()
  await loadTrend()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
/* ===== 控制栏 ===== */
.control-bar { display: flex; align-items: center; justify-content: space-between; }
.control-left { display: flex; align-items: center; gap: 12px; }
.control-label { font-size: 13px; color: var(--color-text-secondary); font-weight: 500; }
.control-hint { font-size: 12px; color: var(--color-text-muted); }

/* ===== 指标卡 ===== */
.metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 16px; }
.metric-card { padding: 20px; }
.metric-value { font-size: 26px; font-weight: 700; line-height: 1.1; margin-bottom: 4px; }
.metric-label { font-size: 13px; font-weight: 500; color: var(--color-text-primary); margin-bottom: 4px; }
.metric-desc { font-size: 11px; color: var(--color-text-muted); }

/* ===== 明细 ===== */
.section-title { font-size: 14px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 16px; }
.detail-pagination { margin-top: 16px; justify-content: flex-end; }
.history-header { display: flex; align-items: center; justify-content: space-between; }
.trend-chart { width: 100%; height: 320px; margin-top: 8px; }
.expand-detail { padding: 4px 16px 8px 48px; }
.detail-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin: 8px 0 4px; }
.detail-chunk { font-size: 12px; color: var(--color-text-muted); line-height: 1.7; margin: 0; font-family: var(--font-mono); }
.history-row { display: flex; justify-content: space-between; gap: 16px; padding: 3px 0; font-size: 12px; }
.history-q { color: var(--color-text-primary); }
.history-rank { color: var(--color-text-secondary); white-space: nowrap; }
</style>
