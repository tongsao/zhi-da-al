<template>
  <div class="page-container animate-in">
    <div class="page-header">
      <div class="page-title">审计查询</div>
      <div class="page-desc">网关调用全量留痕：认证 / 限流 / 业务接口的访问记录</div>
    </div>

    <div class="card audit-card">
      <!-- 筛选栏 -->
      <el-form inline class="filter-bar" @submit.prevent>
        <el-form-item label="调用方">
          <el-select v-model="filters.caller_type" placeholder="全部" clearable style="width: 120px">
            <el-option label="用户" value="user" />
            <el-option label="密钥" value="key" />
            <el-option label="匿名" value="anonymous" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" placeholder="全部" clearable style="width: 120px">
            <el-option label="成功" value="success" />
            <el-option label="未认证" value="unauthorized" />
            <el-option label="无权限" value="forbidden" />
            <el-option label="限流" value="rate_limited" />
            <el-option label="错误" value="error" />
          </el-select>
        </el-form-item>
        <el-form-item label="路径">
          <el-input v-model="filters.path" placeholder="接口路径模糊匹配" clearable style="width: 200px" @keyup.enter="load(1)" />
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="dateRange"
            type="datetimerange"
            value-format="YYYY-MM-DDTHH:mm:ss"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            style="width: 340px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load(1)">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 明细表 -->
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="调用方" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="callerTypeTag(row.caller_type)" effect="plain">
              {{ callerTypeText(row.caller_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="调用方 ID" width="110">
          <template #default="{ row }">{{ row.caller_id ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="方法" width="80">
          <template #default="{ row }">
            <span class="method-tag" :class="row.method.toLowerCase()">{{ row.method }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="path" label="接口路径" min-width="200" show-overflow-tooltip />
        <el-table-column prop="ip" label="IP" width="130" />
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)" effect="light">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status_code" label="HTTP" width="70" />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="90" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="load()"
          @size-change="load(1)" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { gatewayApi } from '@/api/gateway'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dateRange = ref(null)

const filters = reactive({ caller_type: '', status: '', path: '' })

async function load(pageNo) {
  if (pageNo) page.value = pageNo
  loading.value = true
  try {
    const data = await gatewayApi.listAudit({
      ...filters,
      start: dateRange.value?.[0] || null,
      end: dateRange.value?.[1] || null,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = data.items
    total.value = data.total
  } catch {
    // 错误提示由拦截器统一处理
  } finally {
    loading.value = false
  }
}

function reset() {
  filters.caller_type = ''
  filters.status = ''
  filters.path = ''
  dateRange.value = null
  load(1)
}

function callerTypeText(t) {
  return { user: '用户', key: '密钥', anonymous: '匿名' }[t] || t
}
function callerTypeTag(t) {
  return { user: 'primary', key: 'warning', anonymous: 'info' }[t] || 'info'
}
function statusText(s) {
  return {
    success: '成功', unauthorized: '未认证', forbidden: '无权限',
    rate_limited: '限流', error: '错误',
  }[s] || s
}
function statusTag(s) {
  return {
    success: 'success', unauthorized: 'info', forbidden: 'warning',
    rate_limited: 'danger', error: 'danger',
  }[s] || 'info'
}

function fmtDateTime(v) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : '—'
}

onMounted(() => load())
</script>

<style scoped>
.audit-card { padding: 20px; }

.filter-bar { margin-bottom: 4px; }
.filter-bar :deep(.el-form-item) { margin-bottom: 12px; }

.method-tag {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}
.method-tag.get    { background: var(--color-success-bg); color: #059669; }
.method-tag.post   { background: var(--color-primary-bg); color: var(--color-primary); }
.method-tag.patch, .method-tag.put { background: var(--color-warning-bg); color: #b45309; }
.method-tag.delete { background: var(--color-danger-bg); color: #dc2626; }

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>