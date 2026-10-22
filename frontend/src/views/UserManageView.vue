<template>
  <div class="page-container animate-in">
    <div class="page-header flex-between">
      <div>
        <div class="page-title">用户管理</div>
        <div class="page-desc">账号增删改、启停与密码重置；新账号首次登录需强制改密</div>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </div>

    <div class="card user-card">
      <!-- 工具栏 -->
      <div class="toolbar">
        <el-input
          v-model="filters.username"
          placeholder="按用户名模糊搜索"
          clearable
          class="search-input"
          :prefix-icon="Search"
          @keyup.enter="load(1)"
          @clear="load(1)" />
        <el-button type="primary" plain :icon="Search" @click="load(1)">查询</el-button>
      </div>

      <!-- 用户列表 -->
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="display_name" label="显示名" min-width="120">
          <template #default="{ row }">{{ row.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="90">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" effect="light">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active === 1 ? 'success' : 'info'" effect="plain">
              {{ row.is_active === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="强制改密" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.must_change_password === 1" type="warning" effect="plain">待修改</el-tag>
            <span v-else class="muted-text">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openReset(row)">重置密码</el-button>
            <el-button
              link
              :type="row.is_active === 1 ? 'danger' : 'success'"
              @click="toggleActive(row)">
              {{ row.is_active === 1 ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @current-change="load()"
          @size-change="load(1)" />
      </div>
    </div>

    <!-- 新建用户 -->
    <el-dialog v-model="createVisible" title="新建用户" width="440px" :close-on-click-modal="false">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="createForm.username" placeholder="2-50 个字符" />
        </el-form-item>
        <el-form-item label="显示名" prop="display_name">
          <el-input v-model="createForm.display_name" placeholder="选填，默认同用户名" />
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-radio-group v-model="createForm.role">
            <el-radio value="user">普通用户</el-radio>
            <el-radio value="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createLoading" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="resetVisible" :title="`重置密码 · ${resetTarget?.username || ''}`" width="440px" :close-on-click-modal="false">
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules" label-width="80px">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="resetForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="resetForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <p class="reset-tip">重置后该用户需用新密码重新登录，并在首次登录时强制修改密码。</p>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetLoading" @click="submitReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { gatewayApi } from '@/api/gateway'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const filters = reactive({ username: '' })

async function load(pageNo) {
  if (pageNo) page.value = pageNo
  loading.value = true
  try {
    const data = await gatewayApi.listUsers({
      page: page.value,
      page_size: pageSize.value,
      username: filters.username,
    })
    rows.value = data.items
    total.value = data.total
  } catch {
    // 错误提示由拦截器统一处理
  } finally {
    loading.value = false
  }
}

async function toggleActive(row) {
  const action = row.is_active === 1 ? '停用' : '启用'
  const tip = row.is_active === 1 && row.role === 'admin' ? ' 停用后其 JWT 立即失效。' : ''
  try {
    await ElMessageBox.confirm(`确定要${action}用户「${row.username}」吗？${tip}`, '确认操作', { type: 'warning' })
  } catch {
    return
  }
  try {
    await gatewayApi.patchUser(row.id, { is_active: row.is_active === 1 ? 0 : 1 })
    ElMessage.success(`已${action}`)
    load()
  } catch {
    // 后端 4001（如停用最后一个管理员）已由拦截器提示
  }
}

// ===== 新建用户 =====
const createVisible = ref(false)
const createLoading = ref(false)
const createFormRef = ref()
const createForm = reactive({ username: '', display_name: '', password: '', role: 'user' })
const createRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '长度 2-50 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 6, max: 128, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

function openCreate() {
  createForm.username = ''
  createForm.display_name = ''
  createForm.password = ''
  createForm.role = 'user'
  createVisible.value = true
}

async function submitCreate() {
  const ok = await createFormRef.value.validate().catch(() => false)
  if (!ok) return
  createLoading.value = true
  try {
    await gatewayApi.createUser({ ...createForm })
    ElMessage.success('用户已创建，首次登录需改密')
    createVisible.value = false
    load(1)
  } finally {
    createLoading.value = false
  }
}

// ===== 重置密码 =====
const resetVisible = ref(false)
const resetLoading = ref(false)
const resetFormRef = ref()
const resetTarget = ref(null)
const resetForm = reactive({ password: '', confirm: '' })
const resetRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 128, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: (_r, v, cb) => v !== resetForm.password ? cb(new Error('两次输入不一致')) : cb(), trigger: 'blur' },
  ],
}

function openReset(row) {
  resetTarget.value = row
  resetForm.password = ''
  resetForm.confirm = ''
  resetVisible.value = true
}

async function submitReset() {
  const ok = await resetFormRef.value.validate().catch(() => false)
  if (!ok) return
  resetLoading.value = true
  try {
    await gatewayApi.patchUser(resetTarget.value.id, { reset_password: resetForm.password })
    ElMessage.success('密码已重置，用户需在下次登录时改密')
    resetVisible.value = false
    load()
  } finally {
    resetLoading.value = false
  }
}

function fmtDateTime(v) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : '—'
}

onMounted(() => load())
</script>

<style scoped>
.user-card { padding: 20px; }

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.search-input { width: 260px; }

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.muted-text { color: var(--color-text-muted); }
.reset-tip {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: -8px;
  margin-bottom: 8px;
}
</style>