<template>
  <div class="page-container animate-in">
    <div class="page-header flex-between">
      <div>
        <div class="page-title">密钥管理</div>
        <div class="page-desc">供外部系统（信披推送等）调用的 API Key；明文仅创建与轮换时各展示一次</div>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建密钥</el-button>
    </div>

    <div class="card key-card">
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="key_name" label="密钥名称" min-width="140" />
        <el-table-column label="IP 白名单" min-width="200">
          <template #default="{ row }">
            <template v-if="(row.ip_whitelist || []).length">
              <el-tag v-for="ip in row.ip_whitelist" :key="ip" size="small" effect="plain">{{ ip }}</el-tag>
            </template>
            <span v-else class="muted-text">不限</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active === 1 ? 'success' : 'info'" effect="plain">
              {{ row.is_active === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="到期时间" width="170">
          <template #default="{ row }">{{ fmtDateTime(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="rotate(row)">轮换</el-button>
            <el-button
              link
              :type="row.is_active === 1 ? 'danger' : 'success'"
              @click="toggleActive(row)">
              {{ row.is_active === 1 ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!rows.length && !loading" class="empty-state">
        <el-icon class="empty-icon"><Key /></el-icon>
        <p>暂无密钥，点击右上角「新建密钥」创建</p>
      </div>
    </div>

    <!-- 新建密钥 -->
    <el-dialog v-model="createVisible" title="新建密钥" width="480px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon title="密钥明文仅在此处展示一次，关闭后不可再次查看，请立即保存。" class="create-alert" />
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="90px" class="create-form">
        <el-form-item label="密钥名称" prop="key_name">
          <el-input v-model="createForm.key_name" placeholder="如：信披推送-A组" />
        </el-form-item>
        <el-form-item label="IP 白名单" prop="ip_whitelist">
          <el-select
            v-model="createForm.ip_whitelist"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入 IP 后回车添加，至少一项">
            <el-option v-for="ip in createForm.ip_whitelist" :key="ip" :label="ip" :value="ip" />
          </el-select>
        </el-form-item>
        <el-form-item label="到期时间" prop="expires_at">
          <el-date-picker
            v-model="createForm.expires_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="留空则不限期" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createLoading" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 明文结果（创建 / 轮换共用） -->
    <el-dialog v-model="plainVisible" :title="plainTitle" width="560px" :close-on-click-modal="false">
      <p class="plain-tip">密钥明文仅展示这一次，关闭后不可再次查看。请复制并妥善保存。</p>
      <el-input :model-value="plainKey" readonly>
        <template #append>
          <el-button :icon="CopyDocument" @click="copyPlain">复制</el-button>
        </template>
      </el-input>
      <template #footer>
        <el-button type="primary" @click="plainVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Key, Plus, CopyDocument } from '@element-plus/icons-vue'
import { gatewayApi } from '@/api/gateway'

const loading = ref(false)
const rows = ref([])

async function load() {
  loading.value = true
  try {
    const data = await gatewayApi.listApiKeys()
    rows.value = data.items
  } catch {
    // 错误提示由拦截器统一处理
  } finally {
    loading.value = false
  }
}

async function toggleActive(row) {
  const action = row.is_active === 1 ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(`确定要${action}密钥「${row.key_name}」吗？`, '确认操作', { type: 'warning' })
  } catch {
    return
  }
  try {
    await gatewayApi.patchApiKey(row.id, { is_active: row.is_active === 1 ? 0 : 1 })
    ElMessage.success(`已${action}`)
    load()
  } catch {
    // 后端错误已由拦截器提示
  }
}

// ===== 新建密钥 =====
const createVisible = ref(false)
const createLoading = ref(false)
const createFormRef = ref()
const createForm = reactive({ key_name: '', ip_whitelist: [], expires_at: null })
const createRules = {
  key_name: [{ required: true, message: '请输入密钥名称', trigger: 'blur' }],
  ip_whitelist: [{ required: true, type: 'array', min: 1, message: 'IP 白名单不能为空', trigger: 'change' }],
}

function openCreate() {
  createForm.key_name = ''
  createForm.ip_whitelist = []
  createForm.expires_at = null
  createVisible.value = true
}

async function submitCreate() {
  const ok = await createFormRef.value.validate().catch(() => false)
  if (!ok) return
  createLoading.value = true
  try {
    const data = await gatewayApi.createApiKey({
      key_name: createForm.key_name,
      ip_whitelist: createForm.ip_whitelist,
      expires_at: createForm.expires_at || null,
    })
    createVisible.value = false
    showPlain(`密钥已创建「${data.key_name}」`, data.api_key)
    load()
  } catch {
    // 后端 4001（IP 白名单为空等）已由拦截器提示
  } finally {
    createLoading.value = false
  }
}

// ===== 密钥轮换 =====
async function rotate(row) {
  try {
    await ElMessageBox.confirm(`轮换后密钥「${row.key_name}」的旧明文立即失效，确定继续？`, '确认轮换', { type: 'warning' })
  } catch {
    return
  }
  try {
    const data = await gatewayApi.rotateApiKey(row.id)
    showPlain(`新密钥已生效「${row.key_name}」`, data.api_key)
    load()
  } catch {
    // 错误提示由拦截器统一处理
  }
}

// ===== 明文展示 =====
const plainVisible = ref(false)
const plainTitle = ref('')
const plainKey = ref('')

function showPlain(title, key) {
  plainTitle.value = title
  plainKey.value = key
  plainVisible.value = true
}

async function copyPlain() {
  try {
    await navigator.clipboard.writeText(plainKey.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

function fmtDateTime(v) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : '—'
}

onMounted(() => load())
</script>

<style scoped>
.key-card { padding: 20px; }

.create-alert { margin-bottom: 16px; }
.create-form :deep(.el-select) { width: 100%; }

.plain-tip {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 12px;
}
.muted-text { color: var(--color-text-muted); }
</style>