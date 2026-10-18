<template>
  <div class="qa-page">

    <!-- ===== 历史会话侧栏 ===== -->
    <aside class="history-sidebar">
      <div class="history-header">
        <span class="history-title">历史会话</span>
        <el-tooltip content="刷新列表" placement="top">
          <el-button text circle size="small" @click="loadConversations">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
      <div class="history-list">
        <div v-if="!conversations.length" class="history-empty">暂无历史会话</div>
        <div
          v-for="id in conversations"
          :key="id"
          class="history-item"
          :class="{ active: id === String(store.conversationId ?? '') }"
          @click="onSelectConversation(id)">
          <el-icon><ChatDotRound /></el-icon>
          <span class="history-item-title">会话 {{ id }}</span>
          <el-icon class="history-item-del" @click.stop="onDeleteConversation(id)">
            <Delete />
          </el-icon>
        </div>
      </div>
    </aside>

    <!-- ===== 右侧主区 ===== -->
    <div class="qa-main">

    <!-- ===== 空状态引导 ===== -->
    <transition name="fade">
      <div v-if="!store.messages.length" class="welcome">
        <div class="welcome-inner animate-in">
          <div class="welcome-icon">
            <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
              <rect width="56" height="56" rx="16" fill="#eef3fd"/>
              <path d="M18 20h20M18 28h14M18 36h17" stroke="#5b8def" stroke-width="2.5" stroke-linecap="round"/>
            </svg>
          </div>
          <h2 class="welcome-title">你好，我是智答</h2>
          <p class="welcome-desc">基于企业内部知识库的智能问答助手，可以帮你快速查找文档、解答问题。</p>
          <div class="quick-prompts">
            <span class="quick-label">试试这样问：</span>
            <button
              v-for="p in quickPrompts" :key="p"
              class="prompt-chip" @click="onPrompt(p)">{{ p }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- ===== 对话区域 ===== -->
    <div class="chat-area" ref="chatArea">

      <div class="messages-list">
        <transition-group name="msg-in" tag="div">
          <div
            v-for="(msg, idx) in store.messages"
            :key="idx"
            :class="['msg-row', msg.role]">

            <!-- AI 头像 -->
            <div v-if="msg.role === 'assistant'" class="avatar ai-avatar">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <rect width="20" height="20" rx="5" fill="#5b8def"/>
                <path d="M5 7h10M5 10h7M5 13h8" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </div>

            <div class="msg-bubble-wrap">
              <!-- 气泡 -->
              <div :class="['bubble', msg.role]">
                <div v-if="msg.role === 'user'" class="bubble-text">{{ msg.content }}</div>
                <div v-else class="bubble-text markdown-body" v-html="renderMarkdown(msg.content)"></div>

                <!-- 引用来源 -->
                <div v-if="msg.sources?.length" class="sources-section">
                  <div class="sources-header" @click="toggleSources(idx)">
                    <el-icon><Document /></el-icon>
                    <span>引用了 {{ msg.sources.length }} 个来源</span>
                    <el-icon class="chevron" :class="{ open: expandedSources.has(idx) }">
                      <CaretBottom />
                    </el-icon>
                  </div>
                  <transition name="expand">
                    <div v-if="expandedSources.has(idx)" class="sources-list">
                      <div
                        v-for="(src, sIdx) in msg.sources"
                        :key="sIdx"
                        class="source-card">
                        <div class="source-card-left">
                          <span class="source-num">{{ sIdx + 1 }}</span>
                        </div>
                        <div class="source-card-body">
                          <div class="source-title">{{ src.document_title }}</div>
                          <div class="source-preview">{{ src.content_preview }}</div>
                          <div class="source-meta">
                            <el-tag size="small" type="info">相关度 {{ (src.score * 100).toFixed(1) }}%</el-tag>
                          </div>
                        </div>
                      </div>
                    </div>
                  </transition>
                </div>

                <!-- 底部操作栏（仅 AI） -->
                <div v-if="msg.role === 'assistant'" class="msg-actions">
                  <el-tooltip content="复制回答">
                    <el-button text size="small" @click="onCopy(msg)">
                      <el-icon><CopyDocument /></el-icon>
                    </el-button>
                  </el-tooltip>
                  <el-button
                    :type="msg.feedback === 'usable' ? 'success' : 'default'"
                    text size="small"
                    @click="onFeedback(msg, 'usable')">
                    可用
                  </el-button>
                  <el-button
                    :type="msg.feedback === 'need_fix' ? 'warning' : 'default'"
                    text size="small"
                    @click="onFeedback(msg, 'need_fix')">
                    需修改
                  </el-button>
                  <el-button
                    :type="msg.feedback === 'unusable' ? 'danger' : 'default'"
                    text size="small"
                    @click="onFeedback(msg, 'unusable')">
                    不可用
                  </el-button>
                </div>
              </div>

              <!-- 时间戳 -->
              <div class="msg-time" v-if="msg.createdAt">{{ formatTime(msg.createdAt) }}</div>
            </div>

            <!-- 用户头像 -->
            <div v-if="msg.role === 'user'" class="avatar user-avatar">U</div>
          </div>
        </transition-group>

        <!-- ===== 思考中的动画（豆包风格：三点跳动 + 思考中，流式有内容后由 streaming 收起） ===== -->
        <div v-if="loading && !streaming" class="msg-row assistant">
          <div class="avatar ai-avatar">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <rect width="20" height="20" rx="5" fill="#5b8def"/>
              <path d="M5 7h10M5 10h7M5 13h8" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="msg-bubble-wrap">
            <div class="bubble assistant thinking-bubble">
              <span class="thinking-dot"></span>
              <span class="thinking-dot"></span>
              <span class="thinking-dot"></span>
              <span class="thinking-text">思考中</span>
            </div>
          </div>
        </div>

        <!-- 底部锚点 -->
        <div ref="bottomAnchor"></div>
      </div>
    </div>

    <!-- ===== 输入区域 ===== -->
    <div class="input-panel">
      <div class="input-card">
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          :autosize="{ minRows: 1, maxRows: 6 }"
          placeholder="输入你的问题，按 Enter 发送，Shift+Enter 换行..."
          :disabled="loading"
          resize="none"
          @keydown.enter.exact.prevent="onSend"
          @input="autoResize" />
        <div class="input-footer">
          <div class="input-tips">
            <span v-if="store.conversationId" class="session-id">
              会话 ID: {{ store.conversationId }}
            </span>
          </div>
          <div class="input-actions">
            <el-button text @click="onNewConversation" :disabled="loading || !store.messages.length">
              <el-icon><RefreshRight /></el-icon> 新会话
            </el-button>
            <el-button
              v-if="loading"
              type="danger"
              @click="onStop"
              class="send-btn">
              <el-icon><Close /></el-icon>
              停止
            </el-button>
            <el-button
              v-else
              type="primary"
              :disabled="!question.trim()"
              @click="onSend"
              class="send-btn">
              <el-icon><Promotion /></el-icon>
              发送
            </el-button>
          </div>
        </div>
      </div>
      <div class="input-hint">Powered by DeepSeek + RAG · 仅供内部使用</div>
    </div>

    </div>

  </div>
</template>

<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { chatStream, listMessages, listConversationIds, deleteConversation, feedback, stopChat } from '@/api'
import { marked } from 'marked'
import {
  ChatDotRound, Document, CaretBottom, CopyDocument,
  RefreshRight, Promotion, Refresh, Delete, Close
} from '@element-plus/icons-vue'

const store = useChatStore()
const question = ref('')
const loading = ref(false)
// 流式期间为 true：首个 token 到达后收起"思考中"骨架，让占位回答气泡原地逐字生长
const streaming = ref(false)
// 当前流式请求的 AbortController，供「停止」按钮掐断连接
let activeController = null
// 用户点停止：catch 分支保留已生成文本，不覆盖成错误；每次发送前重置
let stopped = false
const chatArea = ref(null)
const bottomAnchor = ref(null)
const expandedSources = reactive(new Set())

const quickPrompts = [
  '年假最多可以休多少天？',
  '如何上传新文档到知识库？',
  'Git 主干分支叫什么？',
  '标准午休时间是几点到几点？',
]

// ===== 历史会话 =====
const conversations = ref([])

const loadConversations = async () => {
  try {
    const data = await listConversationIds()
    // 时间戳 ID 位数一致，但混有早期测试用短 ID，统一转数值降序
    conversations.value = (data?.conversation_id || [])
      .slice()
      .sort((a, b) => Number(b) - Number(a))
  } catch {}
}

const onSelectConversation = async (id) => {
  if (loading.value) return
  store.reset()
  store.setConversation(id)
  expandedSources.clear()
  try {
    const data = await listMessages(id)
    // 历史消息按 human/ai 顺序交替，回答的问题取它前面最近一条 human
    let lastQuestion = ''
    const msgs = (data?.messages || []).map(m => {
      if (m.role === 'human') lastQuestion = m.content
      return {
        role: m.role === 'human' ? 'user' : 'assistant',
        content: m.content,
        question: m.role === 'human' ? null : lastQuestion,
        feedback: null,
        createdAt: null   // sqlite 历史无时间戳
      }
    })
    msgs.forEach(m => store.pushMessage(m))
    await scrollToBottom(false)
  } catch {}
}

const onDeleteConversation = async (id) => {
  try {
    await ElMessageBox.confirm(`确定删除会话 ${id} 吗？此操作不可恢复。`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch { return }   // 用户取消

  try {
    await deleteConversation(id)
    ElMessage.success({ message: '会话已删除', duration: 1500 })
    conversations.value = conversations.value.filter(x => x !== id)
    // 删除的是当前会话则清空对话区
    if (String(id) === String(store.conversationId ?? '')) {
      store.reset()
      expandedSources.clear()
    }
  } catch {}
}

// breaks 必须关：开启时每个 \n 都会渲染成 <br>，答案会变成满屏换行
marked.setOptions({ breaks: false })

const renderMarkdown = (text) => {
  try { return marked.parse(text) } catch { return text }
}

const scrollToBottom = async (smooth = true) => {
  await nextTick()
  if (bottomAnchor.value) {
    bottomAnchor.value.scrollIntoView({ behavior: smooth ? 'smooth' : 'instant' })
  }
}

const toggleSources = (idx) => {
  if (expandedSources.has(idx)) expandedSources.delete(idx)
  else expandedSources.add(idx)
}

const onNewConversation = () => {
  store.reset()
  expandedSources.clear()
  question.value = ''
}

const onPrompt = (p) => {
  question.value = p
  onSend()
}

const onSend = async () => {
  const q = question.value.trim()
  if (!q || loading.value) return

  // 后端 conversation_id 必填，新会话由前端生成时间戳 ID
  if (!store.conversationId) store.setConversation(Date.now())

  // 关闭所有引用展开
  expandedSources.clear()
  store.pushMessage({ role: 'user', content: q, createdAt: new Date().toISOString() })
  question.value = ''
  loading.value = true
  await scrollToBottom()

  // 每次消息都有平滑滚动动画，逐 token 触发会抖动，限频 100ms 再滚
  let lastScroll = 0
  const scrollWhileStreaming = async () => {
    if (Date.now() - lastScroll < 100) return
    lastScroll = Date.now()
    await scrollToBottom()
  }

  // 占位回答气泡延迟到首个 token 到达时才创建：骨架 v-if="loading && !streaming"，
  // 若提前 push 空消息，检索决策期（最长几十秒）会同时出现骨架框 + 空气泡两栏，
  // 看起来像两个聊天框。首个 token 到时创建气泡并收起骨架，两者严格同步。
  let botMsg = null
  const controller = new AbortController()
  activeController = controller
  stopped = false
  try {
    // stream=true 走 SSE，首个 token 到达即亮出答案气泡、收起骨架
    await chatStream(
      { question: q, conversation_id: store.conversationId, top_k: 6 },
      (chunk) => {
        if (!botMsg) {
          streaming.value = true
          store.pushMessage({
            role: 'assistant',
            content: '',
            question: q,
            feedback: null,
            createdAt: new Date().toISOString()
          })
          // 注意不能用 push 前的对象引用：push 进 reactive 数组后 Vue 会再包一层代理，
          // 直接改原对象不会触发视图更新，必须改数组里取出的代理。
          botMsg = store.messages[store.messages.length - 1]
        }
        botMsg.content += chunk
        scrollWhileStreaming()
      },
      controller.signal
    )
    loadConversations()
  } catch (e) {
    // 用户点「停止」：后端已掐断上游，保留已生成的部分，不覆盖成错误
    if (stopped) return
    // 无首个 token 时补一条错误消息，否则原地覆盖占位气泡
    const errText = '抱歉，发生了错误：' + (e?.message || e?.data?.message || '请检查后端服务是否启动')
    if (botMsg) {
      botMsg.content = errText
    } else {
      store.pushMessage({
        role: 'assistant',
        content: errText,
        question: q,
        feedback: null,
        createdAt: new Date().toISOString()
      })
    }
  } finally {
    activeController = null
    streaming.value = false
    loading.value = false
    await nextTick()
    await scrollToBottom()
  }
}

// 用户点「停止生成」：先置位后端取消令牌（掐断模型上游、停止烧钱），再断开 SSE 读流
const onStop = async () => {
  stopped = true
  const controller = activeController
  try {
    await stopChat(store.conversationId)
  } catch {}
  if (controller) controller.abort()
}

const ACTION_LABELS = { usable: '可用', need_fix: '需修改', unusable: '不可用' }

const onFeedback = (msg, action) => {
  msg.feedback = action
  feedback({
    conversation_id: String(store.conversationId ?? ''),
    question: msg.question || '',
    answer: msg.content,
    action
  }).catch(() => {})
  ElMessage.success({ message: `已记录：${ACTION_LABELS[action]}`, duration: 1500 })
}

const onCopy = (msg) => {
  navigator.clipboard.writeText(msg.content).then(() => {
    ElMessage.success({ message: '已复制到剪贴板', duration: 1500 })
  })
  // 复制也算一次行为留痕，不改变评价状态，重复复制会产生多条记录
  feedback({
    conversation_id: String(store.conversationId ?? ''),
    question: msg.question || '',
    answer: msg.content,
    action: 'copy'
  }).catch(() => {})
}

const formatTime = (iso) => {
  try {
    const d = new Date(iso)
    return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`
  } catch { return '' }
}

const autoResize = () => {
  // textarea autosize 已由 :autosize 处理
}

onMounted(loadConversations)
</script>

<style scoped>
/* ===== 整体布局 ===== */
.qa-page {
  height: 100%;
  display: flex;
  flex-direction: row;
  overflow: hidden;
}

/* ===== 历史会话侧栏 ===== */
.history-sidebar {
  width: 230px; flex-shrink: 0; height: 100%;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  display: flex; flex-direction: column;
}
.history-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 12px 10px 16px;
}
.history-title { font-size: 13px; font-weight: 600; color: var(--color-text-secondary); }
.history-list { flex: 1; overflow-y: auto; padding: 0 8px 12px; }
.history-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 10px; border-radius: 8px; cursor: pointer;
  font-size: 13px; color: var(--color-text-secondary); margin-bottom: 2px;
  transition: all var(--transition-fast);
  white-space: nowrap; overflow: hidden;
}
.history-item:hover { background: var(--color-bg); color: var(--color-text-primary); }
.history-item.active {
  background: var(--color-primary-bg); color: var(--color-primary); font-weight: 500;
}
.history-item-title { overflow: hidden; text-overflow: ellipsis; }
.history-item-del {
  margin-left: auto; flex-shrink: 0; color: var(--color-text-muted);
  opacity: 0; transition: opacity var(--transition-fast);
}
.history-item:hover .history-item-del { opacity: 1; }
.history-item-del:hover { color: var(--el-color-danger); }
.history-empty {
  font-size: 12px; color: var(--color-text-muted);
  text-align: center; padding: 24px 0;
}
.qa-main {
  flex: 1; min-width: 0; height: 100%;
  display: flex; flex-direction: column;
}

/* ===== 空状态 ===== */
.welcome {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}
.welcome-inner {
  text-align: center; max-width: 520px;
}
.welcome-icon { margin-bottom: 20px; display: inline-block; }
.welcome-title { font-size: 24px; font-weight: 700; color: var(--color-text-primary); margin-bottom: 12px; }
.welcome-desc { font-size: 14px; color: var(--color-text-secondary); line-height: 1.7; margin-bottom: 24px; }
.quick-prompts { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: center; }
.quick-label { font-size: 12px; color: var(--color-text-muted); }
.prompt-chip {
  padding: 6px 14px; border-radius: 9999px; border: 1px solid var(--color-border);
  background: var(--color-surface); font-size: 13px; color: var(--color-text-secondary);
  cursor: pointer; transition: all var(--transition-fast);
}
.prompt-chip:hover {
  border-color: var(--color-primary); color: var(--color-primary);
  background: var(--color-primary-bg); box-shadow: var(--shadow-xs);
}

/* ===== 对话区 ===== */
.chat-area {
  flex: 1; overflow-y: auto; padding: 0 0 8px;
}
.messages-list { padding: 20px 28px; max-width: 860px; margin: 0 auto; }

/* ===== 消息行 ===== */
.msg-row {
  display: flex; gap: 12px; align-items: flex-start;
  margin-bottom: 16px;
  animation: fadeInUp 300ms ease both;
}
.msg-row.assistant { flex-direction: row; }
.msg-row.user { justify-content: flex-end; }

/* ===== 头像 ===== */
.avatar {
  width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700;
}
.ai-avatar { background: var(--color-primary-bg); }
.user-avatar {
  background: var(--color-primary); color: #fff;
  font-size: 14px;
}

/* ===== 气泡 ===== */
.msg-bubble-wrap { display: flex; flex-direction: column; max-width: 62%; }
.bubble {
  padding: 10px 16px; border-radius: 16px; position: relative;
  line-height: 1.7; font-size: 14px; word-break: break-word;
}
.bubble.user {
  background: #fff;
  color: var(--color-text-primary);
  border-top-right-radius: 4px;
}
.bubble.assistant {
  background: #fff;
  color: var(--color-text-primary);
  border-top-left-radius: 4px;
}
/* QQ 风格小尾巴 */
.bubble::before {
  content: ''; position: absolute; top: 16px;
  width: 0; height: 0; border: 6px solid transparent;
}
.msg-row.assistant .bubble::before {
  left: -9px; border-right: 9px solid #fff;
}
.msg-row.user .bubble::before {
  right: -9px; border-left: 9px solid #fff;
}
.bubble-text { white-space: pre-wrap; word-break: break-word; }
/* AI 走 markdown 渲染，pre-wrap 会把段落文本里的换行符也显示成换行，必须还原成 normal */
.bubble.assistant .bubble-text { white-space: normal; }

/* Markdown 渲染样式 */
.markdown-body { line-height: 1.75; }
.markdown-body :deep(p) { margin-bottom: 10px; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(code) {
  background: var(--color-bg); padding: 2px 5px; border-radius: 4px;
  font-size: 12px; font-family: var(--font-mono);
}
.markdown-body :deep(pre) {
  background: var(--color-bg); padding: 12px; border-radius: 8px;
  overflow-x: auto; margin: 8px 0;
}
.markdown-body :deep(pre code) { background: none; padding: 0; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 20px; margin: 6px 0; }
.markdown-body :deep(strong) { font-weight: 600; color: var(--color-text-primary); }

/* ===== 引用来源 ===== */
.sources-section { margin-top: 10px; }
.sources-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--color-text-muted); cursor: pointer;
  padding: 4px 0; user-select: none;
  transition: color var(--transition-fast);
}
.sources-header:hover { color: var(--color-primary); }
.chevron { transition: transform var(--transition-fast); }
.chevron.open { transform: rotate(180deg); }
.sources-list { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.source-card {
  display: flex; gap: 10px; align-items: flex-start;
  background: var(--color-bg); border-radius: 8px; padding: 10px 12px;
  border: 1px solid var(--color-border-light);
}
.source-card-left { flex-shrink: 0; }
.source-num {
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--color-primary-bg); color: var(--color-primary);
  font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center;
}
.source-card-body { flex: 1; min-width: 0; }
.source-title { font-size: 12px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 4px; }
.source-preview { font-size: 12px; color: var(--color-text-secondary); line-height: 1.5; margin-bottom: 6px;
  overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.source-meta {}

/* ===== 操作栏 ===== */
.msg-actions {
  display: flex; align-items: center; gap: 4px;
  margin-top: 8px; padding-top: 8px;
  border-top: 1px solid var(--color-border-light);
}

.msg-time { font-size: 11px; color: var(--color-text-muted); margin-top: 6px; align-self: stretch; text-align: center; }

/* ===== 思考动画（豆包风格） ===== */
.thinking-bubble {
  min-width: 110px; padding: 14px 18px;
  display: flex; align-items: center; gap: 6px;
}
/* 三点依次向上弹跳再回落，错峰 0.15s 形成"打字"节奏 */
.thinking-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--color-primary);
  animation: thinking-bounce 1.2s infinite ease-in-out;
}
.thinking-dot:nth-child(2) { animation-delay: 0.15s; }
.thinking-dot:nth-child(3) { animation-delay: 0.3s; }
.thinking-text {
  margin-left: 8px; font-size: 13px; color: var(--color-text-muted);
}
@keyframes thinking-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-4px); opacity: 1; }
}

/* ===== 输入区 ===== */
.input-panel {
  flex-shrink: 0; padding: 0 28px 16px;
  background: var(--color-bg);
}
.input-card {
  /* 元宝式输入条：不铺满全宽，居中限定宽度，与上方对话区(860px)同轴但略窄 */
  max-width: 760px; margin: 0 auto;
  background: var(--color-surface); border-radius: 14px;
  box-shadow: var(--shadow-md); padding: 12px 14px 10px;
  border: 1px solid var(--color-border-light);
}
.input-footer {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 8px;
}
.input-tips { flex: 1; }
.session-id { font-size: 11px; color: var(--color-text-muted); }
.input-actions { display: flex; align-items: center; gap: 6px; }
.send-btn { border-radius: 8px !important; font-weight: 500; }
.input-hint { font-size: 11px; color: var(--color-text-muted); text-align: center; margin-top: 8px; }

/* ===== 展开动画 ===== */
.expand-enter-active, .expand-leave-active {
  transition: all var(--transition-base);
  overflow: hidden;
}
.expand-enter-from, .expand-leave-to {
  opacity: 0; max-height: 0; margin-top: 0;
}
.expand-enter-to, .expand-leave-from {
  opacity: 1; max-height: 600px; margin-top: 8px;
}

/* ===== 消息进入动画 ===== */
.msg-in-enter-active { animation: fadeInUp 300ms ease both; }
.msg-in-leave-active { animation: fadeInUp 200ms ease reverse both; }

/* ===== 骨架屏 ===== */
:deep(.el-textarea__inner) {
  border: none !important; box-shadow: none !important;
  padding: 0 !important; font-size: 14px; line-height: 1.6;
  background: transparent !important;
}
:deep(.el-input__count) { display: none; }
</style>
