<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">季报 AI 质检</h2>
        <p class="page-desc">
          上游信披中心推送的季报 PDF 与结构化数据经 project_id 关联。业务点击「开始校验」后，
          Agent 抽取 PDF 中的披露日期、金额、披露人、公告标题，按已启用规则与业务数据逐项比对。
        </p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="check-tabs">
      <!-- ===== 校验列表 ===== -->
      <el-tab-pane label="校验列表" name="list">
        <div class="control-bar card">
          <div class="control-left">
            <span class="control-label">状态</span>
            <el-select v-model="filters.status" clearable placeholder="全部" style="width: 140px" @change="reload">
              <el-option v-for="(meta, key) in STATUS" :key="key" :label="meta.label" :value="key" />
            </el-select>
            <span class="control-hint">默认每个项目只显示最新一条校验记录</span>
          </div>
          <div class="control-right">
            <el-button plain :loading="loading" @click="reload">刷新</el-button>
          </div>
        </div>

        <div class="card" style="padding: 16px 20px;">
          <el-table :data="rows" stripe style="width: 100%" v-loading="loading">
            <el-table-column prop="project_name" label="项目名称" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ row.project_name || '—' }}</template>
            </el-table-column>
            <el-table-column prop="project_id" label="项目ID" width="150" show-overflow-tooltip />
            <el-table-column prop="file_name" label="披露文件" min-width="200" show-overflow-tooltip />
            <el-table-column label="状态" width="140">
              <template #default="{ row }">
                <el-tag size="small" :type="statusMeta(row.status).type">{{ statusMeta(row.status).label }}</el-tag>
                <el-tag v-if="row.recheck_from" size="small" type="warning" effect="plain" class="recheck-tag">复检</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="create_date" label="推送时间" width="170" />
            <el-table-column prop="update_date" label="校验时间" width="170" />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row.result_id)">明细</el-button>
                <el-button
                  link type="primary"
                  :disabled="row.status === 'in_progress'"
                  @click="onCheck(row)"
                >{{ row.status === 'pending' ? '开始校验' : '重新校验' }}</el-button>
                <el-button v-if="row.status === 'in_progress'" link type="warning" @click="onReset(row)">重置</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination
              layout="total, prev, pager, next"
              :total="total"
              :current-page="filters.page"
              :page-size="filters.pageSize"
              @current-change="onPageChange"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== 规则配置 ===== -->
      <el-tab-pane label="规则配置" name="rules">
        <div class="card" style="padding: 16px 20px;">
          <p class="control-hint" style="margin-bottom: 12px;">
            规则由开发预置，业务仅可启用/停用；停用的规则不参与校验，也不影响整体结论。
          </p>
          <el-table :data="rules" stripe style="width: 100%">
            <el-table-column prop="field_label" label="校验字段" width="160" />
            <el-table-column prop="compare_type" label="比对方式" width="180">
              <template #default="{ row }">{{ compareLabel(row.compare_type) }}</template>
            </el-table-column>
            <el-table-column label="金额容差（元）" width="220">
              <template #default="{ row }">
                <el-input-number
                  v-if="row.compare_type === 'amount_diff'"
                  v-model="row.tolerance"
                  :min="0"
                  :step="0.01"
                  :precision="2"
                  size="small"
                  @change="(val) => onToleranceChange(row, val)"
                />
                <span v-else class="control-hint">—</span>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="120">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled === 1"
                  @change="(val) => onToggleRule(row, val)"
                />
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ===== 校验明细抽屉 ===== -->
    <el-drawer v-model="drawerVisible" title="校验明细" size="760px">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="项目名称">{{ detail.project_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="项目ID">{{ detail.project_id }}</el-descriptions-item>
          <el-descriptions-item label="披露文件" :span="2">{{ detail.file_name }}</el-descriptions-item>
          <el-descriptions-item label="整体状态">
            <el-tag size="small" :type="statusMeta(detail.status).type">{{ statusMeta(detail.status).label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="校验时间">{{ detail.update_date || '—' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.error_msg" label="异常原因" :span="2">
            <span class="fail-text">{{ detail.error_msg }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <h3 class="section-title" style="margin: 20px 0 12px;">逐字段比对</h3>
        <el-table :data="detailRows" border size="small">
          <el-table-column prop="label" label="字段" width="110" />
          <el-table-column label="PDF 抽取值" min-width="170">
            <template #default="{ row }">
              <span v-if="row.result === 'SKIP'" class="control-hint">未比对</span>
              <span v-else-if="row.pdfText === null" class="control-hint">未提取到</span>
              <span v-else>{{ row.pdfText }}</span>
            </template>
          </el-table-column>
          <el-table-column label="业务数据值" min-width="170">
            <template #default="{ row }">
              <span v-if="row.result === 'SKIP'" class="control-hint">未比对</span>
              <span v-else-if="row.dbText === null" class="control-hint">为空</span>
              <span v-else>{{ row.dbText }}</span>
            </template>
          </el-table-column>
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="resultMeta(row.result).type">{{ resultMeta(row.result).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.reason || '—' }}</template>
          </el-table-column>
        </el-table>

        <h3 class="section-title" style="margin: 24px 0 12px;">该项目校验历史</h3>
        <el-table :data="history" size="small" highlight-current-row @row-click="(row) => openDetail(row.result_id)">
          <el-table-column prop="result_id" label="#" width="60" />
          <el-table-column prop="file_name" label="披露文件" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="statusMeta(row.status).type">{{ statusMeta(row.status).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="update_date" label="校验时间" width="170" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getCheckResult,
  listCheckResults,
  listCheckRules,
  resetCheck,
  triggerCheck,
  updateCheckRule,
} from '@/api'

const STATUS = {
  pending: { label: '待校验', type: 'info' },
  in_progress: { label: '校验中', type: 'warning' },
  success: { label: '一致', type: 'success' },
  failed: { label: '不一致', type: 'danger' },
  error: { label: '校验异常', type: 'danger' },
}
const FIELD_LABELS = {
  disclosure_date: '披露日期',
  amount: '金额',
  discloser: '披露人',
  title: '公告标题',
}
const COMPARE_LABELS = {
  quarter_match: '披露年月季度必须一致',
  amount_diff: '金额差值在容差内',
  name_normalized: '披露人归一化后一致',
  string_exact: '标题与文件名精确一致',
}
const RESULT_META = {
  MATCH: { label: '一致', type: 'success' },
  MISMATCH: { label: '不一致', type: 'danger' },
  SKIP: { label: '未启用', type: 'info' },
}

const activeTab = ref('list')
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const rules = ref([])
const filters = reactive({ status: '', page: 1, pageSize: 10 })

const drawerVisible = ref(false)
const detail = ref(null)
const history = ref([])
let pollTimer = null

const statusMeta = (status) => STATUS[status] || { label: status || '未知', type: 'info' }
const compareLabel = (type) => COMPARE_LABELS[type] || type
const resultMeta = (result) => RESULT_META[result] || { label: result, type: 'info' }

const fmtAmount = (value) => `¥ ${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
const fmtQuarter = (value) =>
  value && value.year != null && value.quarter != null ? `${value.year} 年 Q${value.quarter}` : null

// 按字段类型把原始值转成展示文本，null 交给模板显示「未提取到 / 为空」
const fieldText = (field, value) => {
  if (value === null || value === undefined || value === '') return null
  if (field === 'amount') return fmtAmount(value)
  if (field === 'disclosure_date') return fmtQuarter(value)
  return String(value)
}

const detailRows = computed(() => {
  const checkDetail = detail.value?.check_detail || {}
  return Object.entries(FIELD_LABELS).map(([field, label]) => {
    const item = checkDetail[field] || { result: 'SKIP', reason: '未参与本次校验' }
    return {
      field,
      label,
      result: item.result,
      reason: item.reason,
      pdfText: item.result === 'SKIP' ? null : fieldText(field, item.pdf),
      dbText: item.result === 'SKIP' ? null : fieldText(field, item.db),
    }
  })
})

const loadList = async (showLoading = true) => {
  if (showLoading) loading.value = true
  try {
    const data = await listCheckResults({
      page: filters.page,
      page_size: filters.pageSize,
      status: filters.status || undefined,
    })
    rows.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const loadRules = async () => {
  const data = await listCheckRules()
  rules.value = data.items || []
}

const reload = () => {
  filters.page = 1
  loadList()
}

const onPageChange = (page) => {
  filters.page = page
  loadList()
}

const loadDetail = async (resultId) => {
  detail.value = await getCheckResult(resultId)
  const data = await listCheckResults({
    project_id: detail.value.project_id,
    latest_only: false,
    page: 1,
    page_size: 50,
  })
  history.value = data.items || []
}

const openDetail = async (resultId) => {
  drawerVisible.value = true
  await loadDetail(resultId)
}

// 有记录在跑就轮询：列表状态与打开的明细一起刷新
const ensurePoll = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await loadList(false)
    if (drawerVisible.value && detail.value) {
      await loadDetail(detail.value.result_id)
    }
    const stillRunning =
      rows.value.some((row) => row.status === 'in_progress') ||
      detail.value?.status === 'in_progress'
    if (!stillRunning) stopPoll()
  }, 3000)
}

const stopPoll = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

const onCheck = async (row) => {
  try {
    await triggerCheck(row.result_id)
    row.status = 'in_progress'
    ElMessage.info('校验已在后台开始')
    ensurePoll()
  } catch {
    // 失败原因由响应拦截器统一提示
  }
}

const onReset = async (row) => {
  await ElMessageBox.confirm('将记录重置为「待校验」？仅在进程中断导致卡住时使用。', '重置校验状态', {
    confirmButtonText: '重置', cancelButtonText: '取消', type: 'warning',
  })
  await resetCheck(row.result_id)
  ElMessage.success('已重置为待校验')
  loadList()
}

const onToggleRule = async (row, enabled) => {
  await updateCheckRule(row.id, enabled ? 1 : 0, row.tolerance)
  row.enabled = enabled ? 1 : 0
  ElMessage.success(`${row.field_label}规则已${enabled ? '启用' : '停用'}`)
}

const onToleranceChange = async (row, value) => {
  await updateCheckRule(row.id, row.enabled, value)
  ElMessage.success('金额容差已保存')
}

onMounted(async () => {
  await Promise.all([loadList(), loadRules()])
  if (rows.value.some((row) => row.status === 'in_progress')) ensurePoll()
})

onBeforeUnmount(stopPoll)
</script>

<style scoped>
.control-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.control-left { display: flex; align-items: center; gap: 12px; }
.control-right { display: flex; align-items: center; gap: 12px; }
.control-label { font-size: 13px; color: var(--color-text-secondary); font-weight: 500; }
.control-hint { font-size: 12px; color: var(--color-text-muted); }
.section-title { font-size: 14px; font-weight: 600; color: var(--color-text-primary); }
.pager { display: flex; justify-content: flex-end; margin-top: 16px; }
.recheck-tag { margin-left: 6px; }
.fail-text { color: #f87171; }
</style>
