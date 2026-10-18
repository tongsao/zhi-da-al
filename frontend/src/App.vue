<template>
  <el-container class="layout">

    <!-- ===== 左侧边栏 ===== -->
    <el-aside class="sidebar" width="260px">
      <!-- Logo -->
      <div class="sidebar-logo">
        <div class="logo-mark">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <rect width="28" height="28" rx="8" fill="#5b8def"/>
            <path d="M8 10h12M8 14h8M8 18h10" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="logo-text">
          <span class="logo-name">智答</span>
          <span class="logo-sub">RAG 知识库</span>
        </div>
      </div>

      <el-divider class="sidebar-divider" />

      <!-- 主导航 -->
      <nav class="sidebar-nav">
        <div class="nav-label">功能</div>
        <template v-for="item in navItems" :key="item.path">
          <!-- 有 children 的是分组头，纯展示不可点，高亮交给子项 -->
          <div v-if="item.children" class="nav-item nav-group">
            <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
            <span class="nav-text">{{ item.label }}</span>
          </div>
          <router-link
            v-else
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path.startsWith(item.path) }">
            <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
            <span class="nav-text">{{ item.label }}</span>
            <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
          </router-link>
          <!-- 子菜单项，用精确匹配避免和分组头同时高亮 -->
          <router-link
            v-for="child in item.children || []"
            :key="child.path"
            :to="child.path"
            class="nav-item nav-child"
            :class="{ active: route.path === child.path }">
            <span class="nav-text">{{ child.label }}</span>
          </router-link>
        </template>
      </nav>

      <!-- 底部：健康状态 -->
      <div class="sidebar-footer">
        <div class="health-indicator" :class="healthClass">
          <span class="health-dot"></span>
          <span class="health-text">{{ healthText }}</span>
        </div>
        <div class="version">v1.0.0 · 2026</div>
      </div>
    </el-aside>

    <!-- ===== 主内容区 ===== -->
    <el-container class="main-wrap">
      <!-- 顶部栏 -->
      <el-header class="topbar">
        <div class="topbar-left">
          <h1 class="page-title-text">{{ currentPageTitle }}</h1>
        </div>
        <div class="topbar-right">
          <el-tooltip content="刷新页面" placement="bottom">
            <el-button text circle @click="$router.go(0)">
              <el-icon><RefreshRight /></el-icon>
            </el-button>
          </el-tooltip>
          <div class="health-chip" :class="healthClass">
            <span class="health-dot-sm"></span>
            {{ healthText }}
          </div>
        </div>
      </el-header>

      <!-- 页面内容 -->
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="slide-up" mode="out-in">
            <component :is="Component" :key="route.path" />
          </transition>
        </router-view>
      </el-main>
    </el-container>

  </el-container>
</template>

<script setup>
import { computed, onMounted, reactive } from 'vue'
import { useRoute } from 'vue-router'
import {
  ChatDotRound, Document, DataAnalysis, Histogram, RefreshRight
} from '@element-plus/icons-vue'
import { checkHealth } from '@/api'

const route = useRoute()

const navItems = [
  { path: '/qa',        label: '智能问答',    icon: ChatDotRound  },
  { path: '/documents', label: '知识库管理',  icon: Document      },
  { path: '/kb',        label: '知识库维护',  icon: DataAnalysis  },
  {
    path: '/eval', label: '效果评测', icon: Histogram,
    children: [
      { path: '/eval/hit-rate',   label: 'hit_rate 回答命中率' },
      { path: '/eval/retrieval',  label: '检索评估' },
      { path: '/eval/gen',        label: '生成评估' },
      { path: '/eval/manual',     label: '人工测评分析' }
    ]
  },
]

const currentPageTitle = computed(() => {
  for (const item of navItems) {
    // 子菜单标题优先，命中评测子页时显示子页标题
    for (const child of item.children || []) {
      if (route.path.startsWith(child.path)) return child.label
    }
    if (route.path.startsWith(item.path)) return item.label
  }
  return '智答'
})

const health = reactive({ status: 'checking' })
const healthClass = computed(() => ({
  ok: health.status === 'ok',
  degraded: health.status === 'degraded',
  down: health.status === 'down' || health.status === 'checking',
  checking: health.status === 'checking'
}))
const healthText = computed(() => ({
  ok: '服务正常', degraded: '部分异常', down: '服务异常', checking: '检测中...'
}[health.status] ?? '未知'))

onMounted(async () => {
  try {
    const data = await checkHealth()
    health.status = data?.status ?? 'ok'
  } catch {
    health.status = 'down'
  }
})
</script>

<style scoped>
/* ===== 整体布局 ===== */
.layout {
  height: 100vh;
  overflow: hidden;
}

/* ===== 侧边栏 ===== */
.sidebar {
  background: #0f1923;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255,255,255,0.05);
  overflow: hidden;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 24px 20px 20px;
}
.logo-mark {
  flex-shrink: 0;
  filter: drop-shadow(0 2px 8px rgba(91,141,239,0.4));
}
.logo-text { display: flex; flex-direction: column; line-height: 1.2; }
.logo-name {
  font-size: 18px; font-weight: 700; color: #fff; letter-spacing: 1px;
}
.logo-sub { font-size: 11px; color: rgba(255,255,255,0.35); margin-top: 2px; }

.sidebar-divider {
  border-color: rgba(255,255,255,0.06) !important;
  margin: 0 12px 16px;
}

/* ===== 导航 ===== */
.sidebar-nav { flex: 1; padding: 0 12px; overflow-y: auto; }
.nav-label {
  font-size: 10px; font-weight: 600; color: rgba(255,255,255,0.25);
  text-transform: uppercase; letter-spacing: 1.2px;
  padding: 0 8px; margin-bottom: 8px;
}
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 10px; cursor: pointer;
  color: rgba(255,255,255,0.55); text-decoration: none;
  font-size: 14px; margin-bottom: 2px;
  transition: all 180ms ease;
  position: relative;
}
.nav-item:hover {
  background: rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.85);
}
.nav-item.active {
  background: rgba(91,141,239,0.15);
  color: #5b8def;
  font-weight: 500;
}
.nav-item.active::before {
  content: '';
  position: absolute; left: 0; top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 60%; border-radius: 0 3px 3px 0;
  background: #5b8def;
}
.nav-icon { font-size: 16px; flex-shrink: 0; }
.nav-text { flex: 1; }
.nav-badge {
  background: rgba(91,141,239,0.2); color: #5b8def;
  font-size: 11px; padding: 1px 6px; border-radius: 9999px;
}
/* 评测分组头：纯展示不可点，不响应 hover/高亮 */
.nav-group {
  color: rgba(255,255,255,0.85);
  font-weight: 600;
  cursor: default;
  margin-top: 10px;
}
.nav-group:hover { background: none; }
/* 评测子菜单：缩进小字 */
.nav-child {
  padding-left: 38px;
  font-size: 13px;
}

/* ===== 侧边栏底部 ===== */
.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.health-indicator {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; margin-bottom: 4px;
}
.health-dot {
  width: 7px; height: 7px; border-radius: 50%;
  flex-shrink: 0;
}
.health-indicator.ok .health-dot { background: #34d399; box-shadow: 0 0 6px #34d399; }
.health-indicator.degraded .health-dot { background: #fbbf24; }
.health-indicator.down .health-dot,
.health-indicator.checking .health-dot { background: #9ca3af; }
.health-indicator.ok .health-text { color: #34d399; }
.health-indicator.degraded .health-text { color: #fbbf24; }
.health-indicator.down .health-text,
.health-indicator.checking .health-text { color: rgba(255,255,255,0.35); }
.version { font-size: 11px; color: rgba(255,255,255,0.2); }

/* ===== 主内容区 ===== */
.main-wrap { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

/* ===== 顶部栏 ===== */
.topbar {
  height: 60px !important;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 28px !important;
  flex-shrink: 0;
}
.topbar-left {}
.page-title-text { font-size: 16px; font-weight: 600; color: var(--color-text-primary); }
.topbar-right { display: flex; align-items: center; gap: 12px; }

.health-chip {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 500;
}
.health-chip.ok { background: var(--color-success-bg); color: #059669; }
.health-chip.degraded { background: var(--color-warning-bg); color: #b45309; }
.health-chip.down, .health-chip.checking { background: #f3f4f6; color: var(--color-text-muted); }
.health-dot-sm {
  width: 6px; height: 6px; border-radius: 50%;
}
.health-chip.ok .health-dot-sm { background: #34d399; }
.health-chip.degraded .health-dot-sm { background: #fbbf24; }
.health-chip.down .health-dot-sm,
.health-chip.checking .health-dot-sm { background: #9ca3af; }

/* ===== 内容区 ===== */
.main-content {
  flex: 1; overflow-y: auto; padding: 0 !important;
  background: var(--color-bg);
}
</style>
