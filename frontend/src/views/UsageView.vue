<template>
  <div class="page-container animate-in">
    <div class="page-header">
      <div class="page-title">用量看板</div>
      <div class="page-desc">今日各模型调用 token 消耗与近 {{ trendDays }} 日趋势</div>
    </div>

    <!-- 今日用量卡片 -->
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-label">今日已用</div>
        <div class="stat-value">{{ fmtNum(today.used) }}</div>
        <div class="stat-sub">token</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">日限额</div>
        <div class="stat-value">{{ today.limit > 0 ? fmtNum(today.limit) : '不限额' }}</div>
        <div class="stat-sub">{{ today.limit > 0 ? 'token' : '未配置' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">剩余可用</div>
        <div class="stat-value" :class="{ warn: today.remaining !== null && today.remaining / today.limit < 0.2 }">
          {{ today.remaining === null ? '—' : fmtNum(today.remaining) }}
        </div>
        <div class="stat-sub">{{ today.remaining === null ? '无限额' : 'token' }}</div>
      </div>
    </div>

    <!-- 分模型用量 -->
    <div class="card model-card">
      <div class="section-title">今日分模型用量</div>
      <el-table v-if="modelRows.length" :data="modelRows" stripe>
        <el-table-column prop="kind" label="模型" min-width="140" />
        <el-table-column label="输入 token">
          <template #default="{ row }">{{ fmtNum(row.input) }}</template>
        </el-table-column>
        <el-table-column label="输出 token">
          <template #default="{ row }">{{ fmtNum(row.output) }}</template>
        </el-table-column>
        <el-table-column label="合计">
          <template #default="{ row }">
            <span class="total-text">{{ fmtNum(row.total) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="占比">
          <template #default="{ row }">
            <el-progress :percentage="percent(row.total)" :stroke-width="10" :show-text="false" />
          </template>
        </el-table-column>
      </el-table>
      <div v-else-if="!loading" class="empty-state">
        <el-icon class="empty-icon"><TrendCharts /></el-icon>
        <p>今日暂无调用记录</p>
      </div>
    </div>

    <!-- 趋势图 -->
    <div class="card trend-card">
      <div class="section-title flex-between">
        <span>近 {{ trendDays }} 日消耗趋势</span>
        <el-radio-group v-model="trendDays" size="small" @change="loadTrend">
          <el-radio-button value="7">7 日</el-radio-button>
          <el-radio-button value="30">30 日</el-radio-button>
          <el-radio-button value="90">90 日</el-radio-button>
        </el-radio-group>
      </div>
      <div ref="chartRef" class="trend-chart"></div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import * as echarts from 'echarts'
import { TrendCharts } from '@element-plus/icons-vue'
import { gatewayApi } from '@/api/gateway'

const loading = ref(false)
const today = reactive({ date: '', limit: 0, used: 0, remaining: null, items: {} })
const trendDays = ref(90)
const chartRef = ref()
let chart = null

const modelRows = computed(() =>
  Object.entries(today.items || {}).map(([kind, v]) => ({ kind, ...v }))
)
const maxTotal = computed(() => Math.max(1, ...modelRows.value.map(r => r.total)))

function percent(total) {
  return Number(((total / maxTotal.value) * 100).toFixed(1))
}

function fmtNum(v) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString()
}

async function loadToday() {
  try {
    const data = await gatewayApi.usageToday()
    Object.assign(today, data)
  } catch {
    // 错误提示由拦截器统一处理
  }
}

async function loadTrend() {
  try {
    const data = await gatewayApi.usageTrend(trendDays.value)
    renderChart(data.items)
  } catch {
    // 错误提示由拦截器统一处理
  }
}

function renderChart(items) {
  if (!chart && chartRef.value) {
    chart = echarts.init(chartRef.value)
  }
  if (!chart) return
  // 后端降序返回（最新在前），图表时间轴需升序
  const asc = [...items].reverse()
  chart.setOption({
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v) => Number(v).toLocaleString() },
    xAxis: { type: 'category', data: asc.map(i => i.date), axisLine: { lineStyle: { color: '#e4e7ed' } } },
    yAxis: { type: 'value', name: 'token', splitLine: { lineStyle: { color: '#f0f2f5' } } },
    series: [{
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      data: asc.map(i => i.total_tokens),
      lineStyle: { width: 2.5, color: '#5b8def' },
      itemStyle: { color: '#5b8def' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(91,141,239,0.28)' },
          { offset: 1, color: 'rgba(91,141,239,0.02)' },
        ]),
      },
    }],
  })
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  loadToday()
  loadTrend()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
}
.stat-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}
.stat-value {
  margin-top: 8px;
  font-size: 28px;
  font-weight: 700;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.stat-value.warn { color: var(--color-danger); }
.stat-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.model-card,
.trend-card {
  padding: 20px;
  margin-bottom: 16px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 16px;
}

.total-text {
  font-weight: 600;
  color: var(--color-primary);
  font-variant-numeric: tabular-nums;
}

.trend-chart {
  height: 320px;
  width: 100%;
}
</style>