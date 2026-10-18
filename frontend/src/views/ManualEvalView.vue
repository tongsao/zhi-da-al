<template>
  <div class="page-container">

    <div class="page-header">
      <div>
        <h2 class="page-title">人工测评分析</h2>
        <p class="page-desc">统计用户对模型回答的操作（复制/可用/需修改/不可用），并支持按问题与操作类型筛选查看明细。</p>
      </div>
      <el-button text size="small" @click="reloadAll">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>

    <!-- ===== 第一部分：操作分布扇形图 ===== -->
    <div class="card" style="padding: 20px; margin-bottom: 16px;">
      <h3 class="section-title">操作分布统计</h3>
      <div ref="pieRef" class="pie-chart"></div>
      <p v-if="!stats.length" class="empty-hint">暂无数据，用户在「智能问答」页复制或评价回答后此处会出现统计</p>
    </div>

    <!-- ===== 第二部分：明细列表 ===== -->
    <div class="card" style="padding: 20px;">
      <h3 class="section-title">测评明细</h3>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-input
          v-model="questionFilter"
          placeholder="用户问题模糊查询"
          clearable
          style="width: 260px"
          @keyup.enter="onSearch"
          @clear="onSearch" />
        <el-select v-model="actionFilter" placeholder="用户操作" clearable style="width: 140px" @change="onSearch">
          <el-option v-for="(label, key) in ACTION_META" :key="key" :label="label.text" :value="key" />
        </el-select>
        <el-button type="primary" @click="onSearch">
          <el-icon><Search /></el-icon> 查询
        </el-button>
        <el-button @click="onReset">重置</el-button>
      </div>

      <el-table :data="detail.items" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-tag size="small" :color="ACTION_META[row.action]?.color" effect="dark" class="action-tag">
              {{ ACTION_META[row.action]?.text || row.action }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="用户问题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="answer" label="模型回答" min-width="280" show-overflow-tooltip />
        <el-table-column prop="conversation_id" label="会话ID" width="150" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-detail">
              <p class="detail-label">用户问题</p>
              <p class="detail-text">{{ row.question }}</p>
              <p class="detail-label">模型回答</p>
              <p class="detail-text pre-wrap">{{ row.answer }}</p>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[30, 50, 100]"
        :total="detail.total"
        layout="total, sizes, prev, pager, next"
        class="detail-pagination"
        @current-change="loadList"
        @size-change="onSizeChange"
      />
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { feedbackStats, feedbackList } from '@/api'

// 操作元数据：扇形图、表格标签、筛选下拉共用一套文案与颜色
const ACTION_META = {
  copy:     { text: '复制',   color: '#5b8def' },
  usable:   { text: '可用',   color: '#34d399' },
  need_fix: { text: '需修改', color: '#fbbf24' },
  unusable: { text: '不可用', color: '#ef4444' },
}

const stats = ref([])
const detail = ref({ total: 0, items: [] })
const page = ref(1)
const pageSize = ref(30)
const questionFilter = ref('')
const actionFilter = ref('')
const pieRef = ref(null)
let chart = null

const loadStats = async () => {
  try {
    stats.value = await feedbackStats()
    renderPie()
  } catch (e) {
    ElMessage.error('加载统计失败：' + (e?.message || e))
  }
}

const renderPie = () => {
  if (!pieRef.value) return
  if (!chart) {
    chart = echarts.init(pieRef.value)
    // 点击扇形联动明细筛选；再点同一个扇形取消筛选
    chart.on('click', (params) => {
      const key = Object.keys(ACTION_META).find(k => ACTION_META[k].text === params.name)
      if (!key) return
      actionFilter.value = actionFilter.value === key ? '' : key
      page.value = 1
      loadList()
    })
  }
  const data = stats.value
    .filter(s => s.count > 0)
    .map(s => ({
      name: ACTION_META[s.action]?.text || s.action,
      value: s.count,
      itemStyle: { color: ACTION_META[s.action]?.color }
    }))

  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} 次（{d}%）' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['38%', '62%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: true,
      label: { formatter: '{b}\n{c} 次（{d}%）' },
      data,
    }]
  }, true)
}

const loadList = async () => {
  try {
    detail.value = await feedbackList({
      page: page.value,
      page_size: pageSize.value,
      question: questionFilter.value,
      action: actionFilter.value,
    })
  } catch (e) {
    ElMessage.error('加载明细失败：' + (e?.message || e))
  }
}

const onSearch = () => {
  page.value = 1
  loadList()
}

const onReset = () => {
  questionFilter.value = ''
  actionFilter.value = ''
  onSearch()
}

const onSizeChange = () => {
  page.value = 1
  loadList()
}

const reloadAll = () => {
  loadStats()
  loadList()
}

const resizeChart = () => chart?.resize()

onMounted(() => {
  reloadAll()
  window.addEventListener('resize', resizeChart)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.page-title { font-size: 20px; font-weight: 700; color: var(--color-text-primary); }
.page-desc { font-size: 13px; color: var(--color-text-secondary); margin-top: 4px; }
.page-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 16px;
}
.section-title { font-size: 15px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 14px; }
.pie-chart { width: 100%; height: 340px; }
.empty-hint { font-size: 13px; color: var(--color-text-muted); text-align: center; padding: 8px 0 16px; }
.filter-bar {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 14px;
}
.action-tag { border: none; }
.expand-detail { padding: 8px 24px 12px; }
.detail-label { font-size: 12px; color: var(--color-text-muted); margin: 8px 0 4px; }
.detail-text { font-size: 13px; color: var(--color-text-secondary); line-height: 1.7; }
.detail-text.pre-wrap { white-space: pre-wrap; }
.detail-pagination { margin-top: 14px; justify-content: flex-end; }
</style>
