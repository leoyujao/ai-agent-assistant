<template>
  <div v-if="citations && citations.length" class="citation-list">
    <div class="list-label">📎 参考来源</div>
    <div class="chips">
      <template v-for="(c, i) in citations">
        <!-- 有 URL 的引用（web_search 等） -->
        <a
          v-if="c.url"
          :key="'web-' + i"
          :href="c.url"
          target="_blank"
          rel="noopener noreferrer"
          class="citation-chip"
          :title="c.url"
        >
          <span class="chip-index">{{ i + 1 }}</span>
          <span class="chip-title">{{ c.title || c.url }}</span>
          <span class="chip-arrow">↗</span>
        </a>
        <!-- 无 URL 的引用（RAG 知识库溯源） -->
        <span
          v-else
          :key="'doc-' + i"
          class="citation-chip chip-doc"
          :title="c.snippet || c.title"
        >
          <span class="chip-index chip-index-doc">{{ i + 1 }}</span>
          <span class="chip-title">{{ c.title || '未知来源' }}</span>
          <span class="chip-arrow">📄</span>
        </span>
      </template>
    </div>
  </div>
</template>

<script setup>
defineProps({
  citations: {
    type: Array,
    default: () => [],
    // [{ title: string, url?: string, snippet?: string }]
  },
})
</script>

<style scoped>
.citation-list {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #edf0f7;
}

.list-label {
  font-size: 0.75rem;
  color: #8896ab;
  margin-bottom: 6px;
  font-weight: 500;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* 通用 chip 样式 */
.citation-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  background: #eef2ff;
  border: 1px solid #d6deff;
  border-radius: 14px;
  font-size: 0.8rem;
  color: #4a5fd6;
  text-decoration: none;
  max-width: 260px;
  transition: background 0.15s, border-color 0.15s;
  cursor: pointer;
}

a.citation-chip:hover {
  background: #dde4ff;
  border-color: #b3c0ff;
  text-decoration: none;
}

/* RAG 知识库引用 chip（绿色调，区分于 web 蓝色调） */
.chip-doc {
  background: #eefbf3;
  border-color: #c6ecd4;
  color: #1a7a3a;
  cursor: help;
}

.chip-doc:hover {
  background: #daf5e4;
  border-color: #9fd8b4;
}

.chip-index {
  font-size: 0.7rem;
  font-weight: 700;
  background: #4a5fd6;
  color: white;
  border-radius: 50%;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 1;
}

/* RAG 引用的序号圆点（绿色） */
.chip-index-doc {
  background: #1a7a3a;
}

.chip-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chip-arrow {
  font-size: 0.75rem;
  flex-shrink: 0;
  opacity: 0.6;
}
</style>
