<template>
  <div class="pwd-page">
    <div class="pwd-card">
      <div class="pwd-header">
        <el-icon class="pwd-icon"><WarningFilled /></el-icon>
        <h2>修改初始密码</h2>
        <p>首次登录或密码被重置后，需要先设置新密码才能继续使用</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        label-position="top"
        @submit.prevent="onSubmit">
        <el-form-item label="原密码" prop="old_password">
          <el-input
            v-model="form.old_password"
            type="password"
            show-password
            autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input
            v-model="form.new_password"
            type="password"
            show-password
            placeholder="至少 6 位"
            autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm">
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            autocomplete="new-password" />
        </el-form-item>
        <el-button
          type="primary"
          class="submit-btn"
          size="large"
          :loading="loading"
          @click="onSubmit">
          确认修改
        </el-button>
      </el-form>

      <div class="pwd-footer">
        <el-button link @click="auth.logout()">返回登录</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ old_password: '', new_password: '', confirm: '' })

const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码至少 6 位', trigger: 'blur' },
    {
      validator: (_r, v, cb) => v === form.old_password ? cb(new Error('新密码不能与原密码相同')) : cb(),
      trigger: 'blur',
    },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r, v, cb) => v !== form.new_password ? cb(new Error('两次输入的新密码不一致')) : cb(),
      trigger: 'blur',
    },
  ],
}

async function onSubmit() {
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  loading.value = true
  try {
    // changePassword 成功后旧 token 在校验时被作废，store 内部会登出
    await auth.changePassword(form.old_password, form.new_password)
    ElMessage.success('密码已修改，请重新登录')
    router.replace('/login')
  } catch {
    // 错误提示已由 api 拦截器统一弹出（4010 原密码错误 / 4001 新旧相同）
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.pwd-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(1200px 600px at 20% -10%, rgba(91,141,239,0.18), transparent 60%),
    radial-gradient(900px 500px at 90% 110%, rgba(91,141,239,0.12), transparent 55%),
    #0f1923;
}

.pwd-card {
  width: 420px;
  padding: 36px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-xl);
  backdrop-filter: blur(12px);
  box-shadow: var(--shadow-lg);
}

.pwd-header {
  text-align: center;
  margin-bottom: 24px;
  color: #fff;
}
.pwd-icon {
  font-size: 28px;
  color: #fbbf24;
}
.pwd-header h2 {
  margin-top: 10px;
  font-size: 20px;
  font-weight: 700;
}
.pwd-header p {
  margin-top: 6px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.45);
}

.pwd-card :deep(.el-form-item__label) {
  color: rgba(255, 255, 255, 0.75);
}
.pwd-card :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.06);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.12) inset;
}
.pwd-card :deep(.el-input__inner) {
  color: #fff;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  font-weight: 600;
  letter-spacing: 4px;
}

.pwd-footer {
  margin-top: 16px;
  text-align: center;
}
.pwd-footer :deep(.el-button) {
  color: rgba(255, 255, 255, 0.55);
}
</style>