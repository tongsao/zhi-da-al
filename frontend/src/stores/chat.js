import { defineStore } from 'pinia'

/**
 * 全局会话状态：当前会话 ID + 历史消息列表
 * 用于问答页多轮对话。
 */
export const useChatStore = defineStore('chat', {
  state: () => ({
    conversationId: null,
    messages: []   // { role: 'user'|'assistant', content, sources?, feedback?, messageId?, createdAt? }
  }),
  actions: {
    setConversation(id) { this.conversationId = id },
    pushMessage(msg) { this.messages.push(msg) },
    updateMessageFeedback(messageId, feedback) {
      const m = this.messages.find(x => x.messageId === messageId)
      if (m) m.feedback = feedback
    },
    reset() {
      this.conversationId = null
      this.messages = []
    }
  }
})