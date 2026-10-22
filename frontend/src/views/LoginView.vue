<template>
  <div class="login-page">
    <!-- ===== 背景层：光晕 + 网格 + 噪点 ===== -->
    <div class="bg-orb bg-orb-a"></div>
    <div class="bg-orb bg-orb-b"></div>
    <div class="bg-orb bg-orb-c"></div>
    <div class="bg-grid"></div>
    <div class="bg-noise"></div>

    <!-- ===== 左：品牌区 ===== -->
    <div class="brand-panel">
      <div class="brand-inner">
        <div class="brand-logo">
          <svg width="52" height="52" viewBox="0 0 52 52" fill="none">
            <defs>
              <linearGradient id="logoGrad" x1="0" y1="0" x2="52" y2="52">
                <stop offset="0%" stop-color="#7ba4f7"/>
                <stop offset="100%" stop-color="#4f7df0"/>
              </linearGradient>
            </defs>
            <rect width="52" height="52" rx="14" fill="url(#logoGrad)"/>
            <path d="M15 19h22M15 26h15M15 33h18" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
          </svg>
        </div>
        <h1 class="brand-name">智答</h1>
        <p class="brand-sub">大模型应用统一网关</p>
        <p class="brand-desc">
          统一的入口接入智能问答与知识库服务，把鉴权、密钥、审计、用量集中管起来。
        </p>

        <div class="feature-list">
          <div v-for="f in features" :key="f.title" class="feature-item">
            <span class="feature-icon">
              <el-icon :size="16"><component :is="f.icon" /></el-icon>
            </span>
            <div class="feature-text">
              <div class="feature-title">{{ f.title }}</div>
              <div class="feature-desc">{{ f.desc }}</div>
            </div>
          </div>
        </div>

        <div class="brand-footer">
          <span class="tag tag-ai">AI</span>
          <span>Powered by Zhipu GLM</span>
          <i class="dot"></i>
          <span>v1.0.0</span>
        </div>
      </div>
    </div>

    <!-- ===== 右：登录表单 ===== -->
    <div class="form-panel">
      <div class="login-card">
        <div class="form-head">
          <h2>欢迎回来</h2>
          <p>登录以继续访问智答工作台</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          class="login-form"
          @submit.prevent="onSubmit">
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              autocomplete="username"
              @keyup.enter="onSubmit">
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              show-password
              autocomplete="current-password"
              @keyup.enter="onSubmit">
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-button
            type="primary"
            native-type="submit"
            class="login-btn"
            size="large"
            :loading="loading">
            <span>进 入 工 作 台</span>
            <el-icon v-if="!loading" class="btn-arrow"><ArrowRight /></el-icon>
          </el-button>
        </el-form>

        <div class="form-foot">
          <span class="foot-lock">
            <el-icon :size="13"><Lock /></el-icon>
            安全连接 · 登录态加密传输
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { User, Lock, ArrowRight, Key, Tickets, Odometer } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const features = [
  { icon: Key,      title: '统一鉴权', desc: '一个账号接入所有服务，天然安全' },
  { icon: Tickets,  title: '审计留痕', desc: '每一次调用都有据可查、可追溯' },
  { icon: Odometer, title: '用量管控', desc: '配额与额度清晰可见、自由掌控' },
]

async function onSubmit() {
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  loading.value = true
  try {
    const user = await auth.login(form.username, form.password)
    // 首次登录/被重置后强制改密，先走改密页；否则回跳原目标页或默认页
    const next = user.must_change_password
      ? '/force-change-password'
      : (route.query.redirect || '/qa')
    router.replace(next)
  } catch {
    // 错误提示已由 api 拦截器统一弹出（4010/4230），这里无需重复处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  background:
    radial-gradient(1100px 500px at 85% -10%, rgba(122,78,236,0.10), transparent 60%),
    radial-gradient(900px 600px at 10% 110%, rgba(91,141,239,0.12), transparent 55%),
    linear-gradient(165deg, #f6f8fc 0%, #eef2f9 100%);
  color: #1a1f36;
  overflow: hidden;
}

/* ---------- 背景层 ---------- */
.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.75;
  pointer-events: none;
  animation: orbFloat 22s ease-in-out infinite alternate;
}
.bg-orb-a {
  width: 640px; height: 640px;
  left: -180px; top: -220px;
  background: radial-gradient(circle, rgba(91,141,239,0.22), transparent 65%);
}
.bg-orb-b {
  width: 560px; height: 560px;
  right: -160px; bottom: -200px;
  background: radial-gradient(circle, rgba(122,78,236,0.16), transparent 65%);
  animation-delay: -8s;
}
.bg-orb-c {
  width: 380px; height: 380px;
  right: 32%; top: -140px;
  background: radial-gradient(circle, rgba(52,211,153,0.14), transparent 65%);
  animation-delay: -15s;
}
@keyframes orbFloat {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to   { transform: translate3d(40px, 30px, 0) scale(1.08); }
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(26,31,54,0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(26,31,54,0.045) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: radial-gradient(ellipse 90% 70% at 50% 40%, #000 0%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse 90% 70% at 50% 40%, #000 0%, transparent 75%);
  pointer-events: none;
}

.bg-noise {
  position: absolute;
  inset: 0;
  opacity: 0.03;
  pointer-events: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.6'/%3E%3C/svg%3E");
}

/* ---------- 左：品牌区 ---------- */
.brand-panel {
  flex: 1.1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 64px 72px;
  position: relative;
  z-index: 1;
}
.brand-inner {
  width: min(460px, 100%);
  animation: fadeInUp 0.7s var(--transition-base) both;
}

.brand-logo {
  display: inline-flex;
  filter: drop-shadow(0 8px 28px rgba(91,141,239,0.38));
  animation: logoIn 0.8s cubic-bezier(0.22, 1, 0.36, 1) both;
}
@keyframes logoIn {
  from { opacity: 0; transform: scale(0.8) rotate(-6deg); }
  to   { opacity: 1; transform: scale(1) rotate(0); }
}

.brand-name {
  margin-top: 22px;
  font-size: 40px;
  font-weight: 700;
  letter-spacing: 4px;
  background: linear-gradient(120deg, #16224a 20%, #3d6fd6 75%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand-sub {
  margin-top: 10px;
  font-size: 15px;
  font-weight: 500;
  color: var(--color-text-secondary);
  letter-spacing: 2px;
}
.brand-desc {
  margin-top: 18px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text-secondary);
  max-width: 420px;
}

.feature-list {
  margin-top: 36px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  border-top: 1px solid rgba(26,31,54,0.08);
  padding-top: 30px;
}
.feature-item {
  display: flex;
  align-items: center;
  gap: 14px;
}
.feature-icon {
  width: 36px; height: 36px;
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: 10px;
  border: 1px solid rgba(91,141,239,0.22);
  background: var(--color-primary-bg);
  color: var(--color-primary);
}
.feature-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.feature-desc {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--color-text-muted);
}

.brand-footer {
  margin-top: 44px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--color-text-muted);
}
.tag-ai {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #fff;
  background: linear-gradient(135deg, #5b8def, #7a5bef);
}
.dot {
  width: 3px; height: 3px;
  border-radius: 50%;
  background: rgba(26,31,54,0.2);
}

/* ---------- 右：表单区 ---------- */
.form-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 64px 56px 64px 24px;
  position: relative;
  z-index: 1;
}

.login-card {
  width: 400px;
  padding: 40px 36px 28px;
  border-radius: 20px;
  background: rgba(255,255,255,0.82);
  border: 1px solid rgba(255,255,255,0.95);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  box-shadow:
    0 24px 64px rgba(31,45,90,0.14),
    0 2px 8px rgba(31,45,90,0.05);
  animation: fadeInUp 0.7s var(--transition-base) 0.12s both;
}

.form-head {
  margin-bottom: 30px;
}
.form-head h2 {
  font-size: 24px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--color-text-primary);
}
.form-head p {
  margin-top: 8px;
  font-size: 13px;
  color: var(--color-text-muted);
}

/* 浅色卡片内输入框覆盖 */
.login-form :deep(.el-input__wrapper) {
  background: rgba(255,255,255,0.9);
  box-shadow: 0 0 0 1px rgba(26,31,54,0.10) inset;
  border-radius: 12px;
  padding: 4px 14px;
  transition: box-shadow var(--transition-fast), background var(--transition-fast);
}
.login-form :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: 0 0 0 1px rgba(91,141,239,0.6) inset, 0 0 0 4px rgba(91,141,239,0.12);
}
.login-form :deep(.el-input__inner) {
  color: var(--color-text-primary);
  height: 42px;
}
.login-form :deep(.el-input__inner::placeholder) {
  color: var(--color-text-muted);
}
.login-form :deep(.el-input__prefix) {
  color: var(--color-text-muted);
  transition: color var(--transition-fast);
}
.login-form :deep(.el-input__wrapper.is-focus .el-input__prefix) {
  color: var(--color-primary);
}
/* 密码可见性切换按钮颜色 */
.login-form :deep(.el-input__suffix) {
  color: var(--color-text-muted);
}

.login-btn {
  width: 100%;
  margin-top: 6px;
  height: 46px;
  border-radius: 12px;
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 4px;
  border: none;
  background: linear-gradient(135deg, #5b8def, #7a5bef);
  box-shadow: 0 8px 24px rgba(91,141,239,0.32);
  transition: transform var(--transition-fast), box-shadow var(--transition-fast), opacity var(--transition-fast);
}
.login-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 32px rgba(91,141,239,0.42);
}
.login-btn:active {
  transform: translateY(0);
}
.login-btn :deep(.btn-arrow) {
  margin-left: 6px;
  transition: transform var(--transition-fast);
}
.login-btn:hover :deep(.btn-arrow) {
  transform: translateX(4px);
}
.login-btn.is-loading :deep(.el-loading-mask) {
  background: transparent;
}

.form-foot {
  margin-top: 24px;
  display: flex;
  justify-content: center;
}
.foot-lock {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}

/* ---------- 入场动画 ---------- */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(18px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ---------- 响应式 ---------- */
@media (max-width: 1024px) {
  .brand-panel { padding: 48px 36px; }
  .form-panel  { padding: 48px 24px; }
}
@media (max-width: 860px) {
  .brand-panel { display: none; }
  .form-panel {
    flex: 1;
    justify-content: center;
    padding: 32px 20px;
  }
  .login-card { width: min(400px, 100%); }
}
</style>