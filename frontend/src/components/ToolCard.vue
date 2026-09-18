<template>
  <div class="tool-card" :class="[`status-${status}`, `tool-${name}`]">
    <!-- 卡片头部 -->
    <div class="card-header" @click="expanded = !expanded">
      <div class="left">
        <span class="tool-icon">{{ icon }}</span>
        <span class="tool-label">{{ label || name }}</span>
      </div>
      <div class="right">
        <span class="status-badge" :class="status">
          <span v-if="status === 'running'" class="spinner-dot"></span>
          <span v-else-if="status === 'done'">✓</span>
          <span v-else-if="status === 'error'">✗</span>
        </span>
        <span class="chevron" :class="{ expanded }">›</span>
      </div>
    </div>

    <!-- 可展开详情 -->
    <transition name="slide">
      <div v-if="expanded" class="card-body">
        <div v-if="input" class="detail-row">
          <span class="detail-label">输入</span>
          <span class="detail-value input-val">{{ truncatedInput }}</span>
        </div>
        <div v-if="output" class="detail-row">
          <span class="detail-label">输出</span>
          <span class="detail-value output-val">{{ truncatedOutput }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  name:   { type: String, required: true },
  label:  { type: String, default: null },
  status: { type: String, default: 'running' },  // running | done | error
  input:  { type: String, default: '' },
  output: { type: String, default: '' },
})

const expanded = ref(false)

const TOOL_ICONS = {
  web_search:          '🔍',
  url_reader:          '🌐',
  calculator:          '🧮',
  python_executor:     '🐍',
  get_current_time:    '🕐',
  search_knowledge_base: '📚',
}

const icon = computed(() => TOOL_ICONS[props.name] || '⚙️')

const truncatedInput = computed(() =>
  props.input.length > 200 ? props.input.slice(0, 200) + '…' : props.input
)
const truncatedOutput = computed(() =>
  props.output.length > 300 ? props.output.slice(0, 300) + '…' : props.output
)
</script>

<style scoped>
.tool-card {
  border-radius: 10px;
  margin: 8px 0;
  background: #f8f9fc;
  border: 1px solid #e8ecf4;
  overflow: hidden;
  font-size: 0.88rem;
  transition: border-color 0.2s;
}

.tool-card.status-done   { border-color: #d4edda; }
.tool-card.status-error  { border-color: #f8d7da; }
.tool-card.status-running { border-color: #cce5ff; }

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  gap: 8px;
}

.card-header:hover { background: #f0f2f8; }

.left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tool-icon { font-size: 1rem; flex-shrink: 0; }

.tool-label {
  font-weight: 500;
  color: #3d4f6e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.status-badge {
  font-size: 0.78rem;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.status-badge.running {
  background: #d6eaff;
  color: #1a5fb4;
}

.status-badge.done {
  background: #d4edda;
  color: #1a7f37;
}

.status-badge.error {
  background: #f8d7da;
  color: #c92a2a;
}

.spinner-dot {
  width: 8px;
  height: 8px;
  border: 2px solid #1a5fb4;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.chevron {
  font-size: 1rem;
  color: #aaa;
  transition: transform 0.2s;
  line-height: 1;
}

.chevron.expanded { transform: rotate(90deg); }

.card-body {
  border-top: 1px solid #e8ecf4;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.detail-label {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: #8896ab;
  padding-top: 2px;
  min-width: 28px;
}

.detail-value {
  color: #4a5568;
  word-break: break-all;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.82rem;
  line-height: 1.5;
  white-space: pre-wrap;
}

.output-val { color: #2d6a4f; }

.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.slide-enter-to,
.slide-leave-from {
  opacity: 1;
  max-height: 300px;
}
</style>
