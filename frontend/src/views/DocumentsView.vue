<template>
  <div class="page-container">

    <!-- 页面标题 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">知识库管理</h2>
        <p class="page-desc">管理知识库中的文档，支持上传、查看、删除操作。</p>
      </div>
      <el-button type="primary" @click="uploadDialog = true">
        <el-icon><Upload /></el-icon>
        上传文档
      </el-button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar card" style="padding: 16px 20px; margin-bottom: 16px;">
      <div class="filter-left">
        <el-input
          v-model="keyword" placeholder="搜索文档标题..."
          clearable size="large" style="width: 320px"
          @clear="loadList" @keyup.enter="loadList">
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button size="large" @click="loadList">搜索</el-button>
      </div>
      <div class="filter-right">
        <span class="total-hint">共 {{ total }} 条文档</span>
      </div>
    </div>

    <!-- 文档列表 -->
    <div class="card" style="padding: 0; overflow: hidden;">
      <el-table
        :data="list" v-loading="loading"
        @sort-change="onSort"
        row-key="ID"
        stripe>

        <el-table-column prop="ID" label="ID" width="120" sortable="custom" show-overflow-tooltip />
        <el-table-column prop="FILE_TITLE" label="文档标题" min-width="200">
          <template #default="{ row }">
            <div class="doc-title-cell">
              <div class="doc-icon">
                <el-icon><Document /></el-icon>
              </div>
              <div>
                <div class="doc-title">{{ row.FILE_TITLE }}</div>
                <div class="doc-file-name">{{ row.FILE_NAME }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="FILE_TYPE" label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.FILE_TYPE?.toUpperCase() }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="CHUNK_COUNT" label="片段数" width="100" sortable="custom" align="center">
          <template #default="{ row }">
            <span class="chunk-badge">{{ row.CHUNK_COUNT }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="CREATE_DATE" label="创建时间" width="170" sortable="custom">
          <template #default="{ row }">
            <span class="time-cell">{{ formatDate(row.CREATE_DATE) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-button size="small" link type="primary" @click="onDownload(row)">
                <el-icon><Download /></el-icon> 下载
              </el-button>
              <el-popconfirm
                v-if="auth.isAdmin"
                :title="`确认删除「${row.FILE_TITLE}」？此操作不可恢复。`"
                confirm-button-text="删除" cancel-button-text="取消"
                confirm-button-type="danger" width="260"
                @confirm="onDelete(row)">
                <template #reference>
                  <el-button size="small" link type="danger">
                    <el-icon><Delete /></el-icon> 删除
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>

        <!-- 空状态 -->
        <template #empty>
          <div class="empty-state">
            <div class="empty-icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <rect width="48" height="48" rx="12" fill="#f0f2f5"/>
                <path d="M16 18h16M16 24h10M16 30h12" stroke="#d1d5db" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </div>
            <p>暂无文档，请先上传</p>
            <el-button type="primary" size="small" @click="uploadDialog = true" style="margin-top:8px">
              上传文档
            </el-button>
          </div>
        </template>
      </el-table>

      <!-- 分页 -->
      <div class="table-footer" v-if="total > 0">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="loadList" @size-change="loadList" />
      </div>
    </div>

    <!-- ===== 上传文档对话框 ===== -->
    <el-dialog
      v-model="uploadDialog"
      title="上传文档"
      width="520"
      :close-on-click-modal="false"
      class="upload-dialog">
      <div class="upload-body">
        <!-- 拖拽上传区 -->
        <el-upload
          ref="uploader"
          :auto-upload="false"
          :limit="1"
          accept=".pdf,.txt,.json,.md"
          :on-change="onFileChange"
          :file-list="fileList"
          :on-remove="onFileRemove"
          drag
          class="upload-drag">
          <div class="drag-inner">
            <div class="drag-icon">
              <el-icon :size="36" color="var(--color-primary)"><Upload /></el-icon>
            </div>
            <div class="drag-text">将文件拖拽到此处，或<span>点击上传</span></div>
            <div class="drag-hint">支持 .pdf / .txt / .json / .md，单文件不超过 100MB</div>
          </div>
        </el-upload>

        <!-- 已选文件展示 -->
        <div v-if="selectedFile" class="selected-file">
          <div class="file-info">
            <div class="file-icon">
              <el-icon><Document /></el-icon>
            </div>
            <div class="file-meta">
              <div class="file-name">{{ selectedFile.name }}</div>
              <div class="file-size">{{ formatFileSize(selectedFile.size) }}</div>
            </div>
            <el-button text circle size="small" @click="onFileRemove">
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
        </div>

        <!-- 切分参数 -->
        <div class="chunk-params">
          <div class="params-title">切分参数</div>
          <div class="params-row">
            <div class="param-item">
              <label>块大小 (chunk_size)</label>
              <el-input-number v-model="uploadForm.chunk_size" :min="100" :max="3000" :step="50" />
              <span class="param-hint">每段文本的字符数，推荐 300~800</span>
            </div>
            <div class="param-item">
              <label>重叠字符 (chunk_overlap)</label>
              <el-input-number v-model="uploadForm.chunk_overlap" :min="0" :max="500" :step="10" />
              <span class="param-hint">相邻块之间的重叠量</span>
            </div>
          </div>
        </div>

        <!-- 自定义标题 -->
        <div class="custom-title">
          <label>自定义标题 <span class="optional">(留空则使用文件名)</span></label>
          <el-input v-model="uploadForm.title" placeholder="例如：2026年考勤制度 v2.0" clearable />
        </div>
      </div>

      <template #footer>
        <el-button @click="uploadDialog = false" :disabled="uploading">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="onUpload">
          {{ uploading ? '上传中...' : '确认上传' }}
        </el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { listDocuments, uploadDocument, downloadDocument, deleteDocument } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const list = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const keyword = ref('')

// 上传
const uploadDialog = ref(false)
const uploading = ref(false)
const selectedFile = ref(null)
const fileList = ref([])

const uploadForm = reactive({ title: '', chunk_size: 500, chunk_overlap: 50 })

const formatDate = (d) => d ? new Date(d).toLocaleString('zh-CN') : '-'
const formatFileSize = (b) => {
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(1) + ' MB'
}

const loadList = async () => {
  loading.value = true
  try {
    const data = await listDocuments({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value
    })
    list.value = data.items || []
    total.value = data.total || 0
  } catch {}
  finally { loading.value = false }
}

const onSort = ({ prop, order }) => {
  // 简单排序，可扩展
  if (!order) { loadList(); return }
  const asc = order === 'ascending' ? 1 : -1
  list.value.sort((a, b) => (a[prop] > b[prop] ? asc : -asc))
}

const onFileChange = (file) => {
  selectedFile.value = file.raw
  fileList.value = [file]
}

const onFileRemove = () => {
  selectedFile.value = null
  fileList.value = []
}

const onUpload = async () => {
  if (!selectedFile.value) { ElMessage.warning('请先选择文件'); return }
  // 后端 title 为必填 query 参数，留空时用文件名（去扩展名）兜底
  const title = uploadForm.title.trim() || selectedFile.value.name.replace(/\.[^.]+$/, '')
  uploading.value = true
  try {
    const data = await uploadDocument(selectedFile.value, {
      title,
      chunk_size: uploadForm.chunk_size,
      chunk_overlap: uploadForm.chunk_overlap
    })
    ElMessage.success({ message: `上传成功，共 ${data.chunk_count} 个片段入库`, duration: 3000 })
    uploadDialog.value = false
    selectedFile.value = null
    fileList.value = []
    uploadForm.title = ''
    loadList()
  } catch {}
  finally { uploading.value = false }
}

const onDownload = async (row) => {
  try {
    const blob = await downloadDocument(row.ID)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.FILE_NAME || 'download'
    a.click()
    URL.revokeObjectURL(url)
  } catch {}
}

const onDelete = async (row) => {
  try {
    await deleteDocument(row.ID)
    ElMessage.success({ message: '文档已删除', duration: 2000 })
    loadList()
  } catch {}
}

onMounted(loadList)
</script>

<style scoped>
/* ===== 筛选栏 ===== */
.filter-bar { display: flex; align-items: center; justify-content: space-between; }
.filter-left { display: flex; align-items: center; gap: 10px; }
.filter-right {}
.total-hint { font-size: 13px; color: var(--color-text-secondary); }

/* ===== 表格 ===== */
.doc-title-cell { display: flex; align-items: center; gap: 10px; }
.doc-icon {
  width: 34px; height: 34px; border-radius: 8px; background: var(--color-primary-bg);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  color: var(--color-primary); font-size: 16px;
}
.doc-title { font-size: 13px; font-weight: 500; color: var(--color-text-primary); }
.doc-file-name { font-size: 11px; color: var(--color-text-muted); margin-top: 2px; }
.chunk-badge {
  background: var(--color-primary-bg); color: var(--color-primary);
  padding: 2px 8px; border-radius: 9999px; font-size: 12px; font-weight: 600;
}
.time-cell { font-size: 12px; color: var(--color-text-secondary); }
.action-btns { display: flex; gap: 4px; }
.table-footer { padding: 12px 20px; border-top: 1px solid var(--color-border-light); }

/* ===== 上传弹窗 ===== */
.upload-body { display: flex; flex-direction: column; gap: 20px; }
.upload-drag { width: 100%; }
.upload-drag :deep(.el-upload-dragger) {
  border-radius: var(--radius-lg); border: 2px dashed var(--color-border);
  background: var(--color-bg); padding: 32px; transition: all var(--transition-fast);
}
.upload-drag :deep(.el-upload-dragger:hover) {
  border-color: var(--color-primary); background: var(--color-primary-bg-light);
}
.drag-inner { text-align: center; }
.drag-icon { margin-bottom: 12px; }
.drag-text { font-size: 14px; color: var(--color-text-secondary); margin-bottom: 6px; }
.drag-text span { color: var(--color-primary); font-weight: 500; cursor: pointer; }
.drag-hint { font-size: 12px; color: var(--color-text-muted); }

.selected-file {
  background: var(--color-bg); border-radius: var(--radius-md); padding: 12px 16px;
}
.file-info { display: flex; align-items: center; gap: 12px; }
.file-icon {
  width: 36px; height: 36px; border-radius: 8px; background: var(--color-primary-bg);
  display: flex; align-items: center; justify-content: center; color: var(--color-primary);
}
.file-meta { flex: 1; }
.file-name { font-size: 13px; font-weight: 500; color: var(--color-text-primary); }
.file-size { font-size: 12px; color: var(--color-text-muted); margin-top: 2px; }

.chunk-params { background: var(--color-bg); border-radius: var(--radius-md); padding: 16px; }
.params-title { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.params-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.param-item { display: flex; flex-direction: column; gap: 6px; }
.param-item label { font-size: 12px; font-weight: 500; color: var(--color-text-primary); }
.param-hint { font-size: 11px; color: var(--color-text-muted); }

.custom-title label { font-size: 12px; font-weight: 500; color: var(--color-text-primary); display: block; margin-bottom: 6px; }
.optional { color: var(--color-text-muted); font-weight: 400; }
</style>
