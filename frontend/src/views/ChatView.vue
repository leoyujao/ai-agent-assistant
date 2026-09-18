<template>
  <div class="chat-view">
    <!-- 消息列表区域 -->
    <div class="messages-container" ref="messagesContainer">
      <!-- 空状态 -->
      <div v-if="messages.length === 0" class="empty-state">
        <div class="empty-icon">💬</div>
        <h3>开始对话</h3>
        <p>输入问题，AI Agent 将使用工具来帮助你</p>
        <div class="examples">
          <span class="example-chip" @click="sendExample('现在几点了？')">现在几点了？</span>
          <span class="example-chip" @click="sendExample('计算 123 * 456 + 789')">计算 123 * 456</span>
          <span class="example-chip" @click="sendExample('搜索今天的科技新闻')">搜索科技新闻</span>
        </div>
      </div>

      <!-- 消息列表 -->
      <ChatMessage
        v-for="(msg, idx) in messages"
        :key="idx"
        :msg="msg"
        :is-streaming="streaming && idx === messages.length - 1"
        :tool-name="streaming && idx === messages.length - 1 ? currentTool : null"
        :step="streaming && idx === messages.length - 1 ? currentStep : null"
      />
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <div class="input-wrapper">
        <input
          v-model="inputText"
          type="text"
          placeholder="输入问题，按 Enter 发送..."
          :disabled="streaming"
          @keyup.enter="handleSend"
          class="msg-input"
        />
        <button
          @click="handleSend"
          :disabled="streaming || !inputText.trim()"
          class="send-btn"
        >
          发送
        </button>
      </div>
      <div class="actions">
        <button @click="clear" class="clear-btn" :disabled="messages.length === 0">
          🗑️ 清空对话
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import ChatMessage from '../components/ChatMessage.vue'
import { useChat } from '../composables/useChat.js'

const { messages, streaming, currentTool, currentStep, send, clear } = useChat()

const inputText = ref('')
const messagesContainer = ref(null)

// 发送消息
function handleSend() {
  const text = inputText.value.trim()
  if (!text || streaming.value) return
  inputText.value = ''
  send(text)
}

// 点击示例问题
function sendExample(text) {
  if (streaming.value) return
  send(text)
}

// 消息更新时自动滚动到底部
watch(
  () => messages.value.length,
  async () => {
    await nextTick()
    scrollToBottom()
  }
)

// 流式输出时也持续滚动
watch(
  () => messages.value[messages.value.length - 1]?.content,
  async () => {
    await nextTick()
    scrollToBottom()
  }
)

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 900px;
  margin: 0 auto;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #666;
  text-align: center;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-state h3 {
  margin: 0 0 8px;
  color: #333;
}

.empty-state p {
  margin: 0 0 20px;
  font-size: 0.9rem;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.example-chip {
  padding: 6px 14px;
  background: #f0f2f8;
  border-radius: 20px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}

.example-chip:hover {
  background: #e0e4f0;
  color: #667eea;
}

.input-area {
  padding: 16px 0;
  border-top: 1px solid #e8ecf4;
}

.input-wrapper {
  display: flex;
  gap: 8px;
}

.msg-input {
  flex: 1;
  padding: 12px 16px;
  border: 1.5px solid #e0e4f0;
  border-radius: 12px;
  font-size: 1rem;
  outline: none;
  transition: border-color 0.2s;
}

.msg-input:focus {
  border-color: #667eea;
}

.msg-input:disabled {
  background: #f8f9fc;
}

.send-btn {
  padding: 12px 24px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  cursor: pointer;
  transition: opacity 0.2s;
  min-width: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.send-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.clear-btn {
  padding: 6px 12px;
  background: transparent;
  border: 1px solid #e0e4f0;
  border-radius: 8px;
  color: #666;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}

.clear-btn:hover:not(:disabled) {
  border-color: #ff6b6b;
  color: #ff6b6b;
}

.clear-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
