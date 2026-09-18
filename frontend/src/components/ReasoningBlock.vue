<template>
  <div v-if="content || steps.length" class="reasoning-block">
    <div class="reasoning-header" @click="collapsed = !collapsed">
      <span class="reasoning-icon">🧠</span>
      <span class="reasoning-label">{{ label || '推理过程' }}</span>
      <span class="chevron" :class="{ open: !collapsed }">▸</span>
    </div>

    <transition name="fade">
      <div v-if="!collapsed" class="reasoning-body">
        <!-- 推理文本 -->
        <div v-if="content" class="reasoning-text" v-html="renderedContent"></div>

        <!-- 工具调用步骤时间线 -->
        <div v-if="steps.length" class="timeline">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="timeline-step"
            :class="`step-${step.status}`"
          >
            <div class="step-dot">
              <span v-if="step.status === 'running'" class="step-spinner"></span>
              <span v-else-if="step.status === 'done'" class="step-check">✓</span>
              <span v-else class="step-num">{{ i + 1 }}</span>
            </div>
            <div class="step-info">
              <span class="step-name">{{ step.label || step.name }}</span>
              <span v-if="step.summary" class="step-summary">{{ step.summary }}</span>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({
  content:  { type: String, default: '' },
  steps:    { type: Array, default: () => [] },  // [{name, label, status, summary}]
  label:    { type: String, default: null },
  defaultOpen: { type: Boolean, default: false },
})

const collapsed = ref(!props.defaultOpen)

const renderedContent = computed(() => {
  if (!props.content) return ''
  const html = marked(props.content, { breaks: true })
  return DOMPurify.sanitize(html)
})
</script>

<style scoped>
.reasoning-block {
  margin: 8px 0;
  border-radius: 10px;
  background: #f8f5ff;
  border: 1px solid #e8e0f8;
  overflow: hidden;
  font-size: 0.88rem;
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
}

.reasoning-header:hover { background: #f0ebff; }

.reasoning-icon { font-size: 1rem; }

.reasoning-label {
  font-weight: 500;
  color: #6b4db3;
  flex: 1;
}

.chevron {
  font-size: 0.9rem;
  color: #9b7fd4;
  transition: transform 0.2s;
}

.chevron.open { transform: rotate(90deg); }

.reasoning-body {
  border-top: 1px solid #e8e0f8;
  padding: 10px 14px;
}

.reasoning-text {
  color: #5c4a8a;
  line-height: 1.6;
  white-space: pre-wrap;
}

.reasoning-text :deep(p) {
  margin: 0.3em 0;
}

/* 时间线 */
.timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.timeline-step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 5px 0;
  position: relative;
}

.timeline-step:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 11px;
  top: 24px;
  bottom: -4px;
  width: 2px;
  background: #d9cff0;
}

.step-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 700;
  position: relative;
  z-index: 1;
}

.step-running .step-dot { background: #d6eaff; }
.step-done .step-dot    { background: #d4edda; }
.step-error .step-dot   { background: #f8d7da; }

.step-spinner {
  width: 9px;
  height: 9px;
  border: 2px solid #1a5fb4;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.step-check { color: #1a7f37; font-size: 0.78rem; }
.step-num   { color: #6b4db3; }

.step-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding-top: 2px;
}

.step-name {
  font-weight: 500;
  color: #4a3880;
  font-size: 0.85rem;
}

.step-summary {
  font-size: 0.78rem;
  color: #7c6aaa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fade-enter-active,
.fade-leave-active { transition: all 0.2s ease; overflow: hidden; }
.fade-enter-from,
.fade-leave-to { opacity: 0; max-height: 0; }
.fade-enter-to,
.fade-leave-from { opacity: 1; max-height: 500px; }
</style>
