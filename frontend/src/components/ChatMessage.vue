<template>
  <div class="chat-message" :class="msg.role">
    <!-- 消息内容：AI 侧无头像无气泡，正文直接铺在背景上；用户侧右对齐气泡 -->
    <div class="bubble">
      <!-- =================== AI 消息区 =================== -->
      <template v-if="msg.role === 'assistant'">

        <!-- 1. 推理过程：工具调用时展示时间线 -->
        <ReasoningBlock
          v-if="hasToolCalls"
          :steps="toolSteps"
          :default-open="isStreaming"
          label="执行过程"
        />

        <!-- 1.5 Query Rewrite 展示 -->
        <div v-if="msg.queryRewrite" class="query-rewrite">
          <span class="qr-label">🔍 查询改写</span>
          <div class="qr-detail">
            <span class="qr-original">{{ msg.queryRewrite.original }}</span>
            <span class="qr-arrow">→</span>
            <span class="qr-rewritten">{{ msg.queryRewrite.rewritten }}</span>
          </div>
        </div>

        <!-- 2. 工具卡片列表 -->
        <div v-if="msg.toolCalls && msg.toolCalls.length" class="tool-list">
          <ToolCard
            v-for="(tc, i) in msg.toolCalls"
            :key="i"
            :name="tc.name"
            :label="tc.label"
            :status="tc.status"
            :input="tc.input"
            :output="tc.output"
          />
        </div>

        <!-- 3. 等待回复期间的载入状态（左侧机器人侧，首个 token 到达前一直显示） -->
        <div v-if="isStreaming && !msg.content" class="thinking">
          <span class="thinking-dots"><i></i><i></i><i></i></span>
          <span class="thinking-text">{{ loadingText }}</span>
        </div>

        <!-- 4. LLM 回复文本 -->
        <div
          v-if="msg.content"
          class="content"
          v-html="renderedContent"
        ></div>

        <!-- 5. 引用来源 -->
        <CitationList :citations="msg.citations" />

        <!-- 6. 评审过程展示 -->
        <ReviewBlock :reviews="msg.reviews" />

        <!-- 7. 流式接收时的光标 -->
        <span v-if="isStreaming && msg.content" class="cursor">▌</span>
      </template>

      <!-- =================== 用户消息区 =================== -->
      <div v-else class="content" v-html="renderedContent"></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import ToolCard from './ToolCard.vue'
import CitationList from './CitationList.vue'
import ReasoningBlock from './ReasoningBlock.vue'
import ReviewBlock from './ReviewBlock.vue'

const props = defineProps({
  msg:          { type: Object,  required: true },
  isStreaming:  { type: Boolean, default: false },
  toolName:     { type: String,  default: null },  // 当前流式工具名
  step:         { type: String,  default: null },  // 当前执行阶段：llm / rag / tool / review
})

// Markdown 渲染 + XSS 过滤
const renderedContent = computed(() => {
  if (!props.msg.content) return ''
  const html = marked(props.msg.content, { breaks: true })
  return DOMPurify.sanitize(html)
})

// 是否有工具调用记录
const hasToolCalls = computed(() =>
  props.msg.toolCalls && props.msg.toolCalls.length > 0
)

// 工具调用列表 → ReasoningBlock steps 格式
const toolSteps = computed(() =>
  (props.msg.toolCalls || []).map(tc => ({
    name:    tc.name,
    label:   tc.label || tc.name,
    status:  tc.status,
    summary: tc.input ? tc.input.slice(0, 60) + (tc.input.length > 60 ? '…' : '') : '',
  }))
)

// 载入提示文案：按当前执行阶段切换，让用户在首个 token 到达前知道 Agent 在做什么
const loadingText = computed(() => {
  if (props.toolName) return `正在调用 ${props.toolName} …`
  if (props.step === 'rag') return '正在检索知识库 …'
  if (props.step === 'review') return '正在评审回复 …'
  return '正在思考 …'
})
</script>

<style scoped>
.chat-message {
  display: flex;
  padding: 10px 16px;
  max-width: 800px;
  margin: 0 auto;
}

/* 用户消息：右对齐，与新回合拉开距离 */
.chat-message.user {
  justify-content: flex-end;
  margin-top: 14px;
}

.bubble {
  line-height: 1.6;
  word-break: break-word;
  min-width: 0;
}

/* AI 消息：无头像、无内容块，正文直接铺在页面背景上 */
.chat-message.assistant .bubble {
  flex: 1;
}

/* 用户消息：右对齐浅色气泡 */
.chat-message.user .bubble {
  max-width: 78%;
  padding: 10px 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 16px 16px 4px 16px;
}

.content :deep(pre) {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 0.88rem;
}

.content :deep(code) {
  font-family: 'Consolas', 'Monaco', monospace;
}

.content :deep(p) {
  margin: 0.4em 0;
}

/* 收紧列表间距：覆盖浏览器默认的 1em 外边距与 <li> 之间的松间距 */
.content :deep(ul),
.content :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.5em;
}

.content :deep(li) {
  margin: 0.15em 0;
}

/* 列表项内含段落时（marked 常见输出），去掉重复的段落外边距 */
.content :deep(li > p) {
  margin: 0;
}

/* 工具卡片列表间距 */
.tool-list {
  margin-bottom: 6px;
}

/* Query Rewrite 展示 */
.query-rewrite {
  margin: 6px 0;
  padding: 8px 12px;
  background: #f0f4ff;
  border-radius: 8px;
  border: 1px solid #dde4f6;
  font-size: 0.82rem;
}

.qr-label {
  font-weight: 600;
  color: #4a5dbd;
  font-size: 0.78rem;
}

.qr-detail {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.qr-original {
  color: #888;
  text-decoration: line-through;
  font-size: 0.8rem;
}

.qr-arrow {
  color: #667eea;
  font-weight: 600;
}

.qr-rewritten {
  color: #3d4f6e;
  font-weight: 500;
}

/* 等待回复时的载入状态（左侧机器人侧） */
.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #667eea;
  font-size: 0.9rem;
  padding: 4px 0 8px;
}

.thinking-dots {
  display: inline-flex;
  gap: 4px;
  flex-shrink: 0;
}

.thinking-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #667eea;
  animation: thinking-bounce 1.4s ease-in-out infinite;
}

.thinking-dots i:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots i:nth-child(3) { animation-delay: 0.4s; }

@keyframes thinking-bounce {
  0%, 60%, 100% { transform: translateY(0);    opacity: 0.35; }
  30%           { transform: translateY(-4px); opacity: 1; }
}

.cursor {
  color: #667eea;
  animation: blink 0.8s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}
</style>

