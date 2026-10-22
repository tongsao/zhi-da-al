import { defineStore } from 'pinia'
import { gatewayApi } from '@/api/gateway'

const TOKEN_KEY = 'zd_token'
const USER_KEY = 'zd_user'

/**
 * 登录态：token + user 双持久化（刷新不丢）。
 * 改密成功后旧 token 被后端作废，需重新登录（见 changePassword）。
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    isAdmin: (s) => s.user?.role === 'admin',
    mustChangePassword: (s) => !!s.user?.must_change_password,
  },
  actions: {
    setSession(token, user) {
      this.token = token
      this.user = user
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    },
    async login(username, password) {
      // 后端返回 { token, user }；user 含 must_change_password 标志
      const { token, user } = await gatewayApi.login({ username, password })
      this.setSession(token, user)
      return user
    },
    async fetchMe() {
      const data = await gatewayApi.me()
      this.user = { ...this.user, ...data.user }
      localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      return this.user
    },
    async changePassword(oldPassword, newPassword) {
      await gatewayApi.changePassword({ old_password: oldPassword, new_password: newPassword })
      // 改密即失效旧 token，需重新登录
      this.logout()
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})
