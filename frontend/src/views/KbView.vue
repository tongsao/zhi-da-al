<template>
  <div class="page-container">

    <div class="page-header">
      <div>
        <h2 class="page-title">知识库维护</h2>
        <p class="page-desc">查看知识库统计信息。</p>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div v-for="stat in statCards" :key="stat.label" class="stat-card card animate-in">
        <div class="stat-icon" :style="{ background: stat.iconBg, color: stat.iconColor }">
          <el-icon :size="22"><component :is="stat.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ stat.value }}</div>
          <div class="stat-label">{{ stat.label }}</div>
        </div>
      </div>
    </div>

    <!-- 操作区 -->
    <div class="ops-row">

      <!-- 刷新统计 -->
      <div class="card rebuild-card">
        <div class="rebuild-header">
          <div>
            <h3 class="rebuild-title">统计概览</h3>
            <p class="rebuild-desc">统计数据来自 MySQL 文档记录与向量库 Embedding 配置。文档增删后可点击刷新同步。</p>
          </div>
        </div>

        <div class="rebuild-actions">
          <el-button size="large" type="primary" @click="loadStats" :loading="loading">
            <el-icon v-if="!loading"><Refresh /></el-icon> 刷新统计
          </el-button>
        </div>
      </div>

      <!-- 向量维度信息 -->
      <div class="card info-card">
        <h3 class="info-title">向量配置</h3>
        <div class="info-list">
          <div class="info-row">
            <span class="info-label">Embedding 模型</span>
            <span class="info-value">DeepSeek Embedding</span>
          </div>
          <div class="info-row">
            <span class="info-label">向量维度</span>
            <span class="info-value code">{{ stats.vector_dim || '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">向量库</span>
            <span class="info-value">ChromaDB (本地持久化)</span>
          </div>
          <div class="info-row">
            <span class="info-label">存储路径</span>
            <span class="info-value code">data/vector_store/</span>
          </div>
        </div>
      </div>

    </div>

  </div>
</template>

<script setup>
import { reactive, computed, ref, onMounted } from 'vue'
import { kbStats } from '@/api'
import { Document, CopyDocument, DataLine, CircleCheck, Refresh } from '@element-plus/icons-vue'

const stats = reactive({ document_count: 0, chunk_count: 0, vector_dim: 0 })
const loading = ref(false)

const statCards = computed(() => [
  {
    icon: Document, iconBg: '#eef3fd', iconColor: '#5b8def',
    value: stats.document_count, label: '文档总数'
  },
  {
    icon: CopyDocument, iconBg: '#f0fdf4', iconColor: '#22c55e',
    value: stats.chunk_count, label: '切片总数'
  },
  {
    icon: CircleCheck, iconBg: '#f0f9ff', iconColor: '#0ea5e9',
    value: stats.vector_dim ? stats.vector_dim + ' 维' : '—', label: '向量维度'
  },
])

const loadStats = async () => {
  loading.value = true
  try { Object.assign(stats, await kbStats()) } catch {}
  finally { loading.value = false }
}

onMounted(loadStats)
</script>

<style scoped>
/* ===== 统计卡片 ===== */
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 20px; }
.stat-card { padding: 20px; display: flex; align-items: center; gap: 16px; }
.stat-icon {
  width: 48px; height: 48px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.stat-value { font-size: 26px; font-weight: 700; color: var(--color-text-primary); line-height: 1.2; }
.stat-label { font-size: 13px; color: var(--color-text-secondary); margin-top: 2px; }

/* ===== 操作区 ===== */
.ops-row { display: grid; grid-template-columns: 1fr 340px; gap: 16px; }
.rebuild-card { padding: 24px; }
.rebuild-header { margin-bottom: 16px; }
.rebuild-title { font-size: 15px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 6px; }
.rebuild-desc { font-size: 13px; color: var(--color-text-secondary); line-height: 1.6; }
.rebuild-actions { display: flex; gap: 10px; }

/* ===== 信息卡 ===== */
.info-card { padding: 24px; }
.info-title { font-size: 14px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 16px; }
.info-list { display: flex; flex-direction: column; gap: 12px; }
.info-row { display: flex; justify-content: space-between; align-items: center; }
.info-label { font-size: 12px; color: var(--color-text-secondary); }
.info-value { font-size: 12px; font-weight: 500; color: var(--color-text-primary); }
.info-value.code { font-family: var(--font-mono); background: var(--color-bg); padding: 2px 6px; border-radius: 4px; }
</style>
