<template>
  <div class="app">
    <!-- 顶部标题栏 -->
    <header class="header">
      <h1 class="title">🤖 AI Agent 对话助手</h1>
      <p class="subtitle">基于 LangChain + DeepSeek-v4 | 支持知识库问答</p>
    </header>

    <!-- Tab 切换 -->
    <nav class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['tab-btn', { active: activeTab === tab.id }]"
        @click="activeTab = tab.id"
      >
        {{ tab.icon }} {{ tab.label }}
      </button>
    </nav>

    <!-- 内容区域 -->
    <main class="main-content">
      <ChatView v-if="activeTab === 'chat'" />
      <KnowledgeView v-else />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ChatView from './views/ChatView.vue'
import KnowledgeView from './views/KnowledgeView.vue'

const activeTab = ref('chat')

const tabs = [
  { id: 'chat', icon: '💬', label: '智能对话' },
  { id: 'kb', icon: '📚', label: '知识库' },
]
</script>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f7fb;
}

.header {
  text-align: center;
  padding: 20px 20px 0;
}

.title {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.subtitle {
  margin: 4px 0 0;
  font-size: 0.85rem;
  color: #888;
}

.tabs {
  display: flex;
  justify-content: center;
  gap: 4px;
  padding: 16px 20px;
}

.tab-btn {
  padding: 10px 24px;
  background: transparent;
  border: none;
  border-radius: 10px;
  font-size: 0.95rem;
  cursor: pointer;
  color: #666;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: #e8ecf4;
}

.tab-btn.active {
  background: white;
  color: #667eea;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.15);
  font-weight: 500;
}

.main-content {
  flex: 1;
  background: white;
  border-radius: 20px 20px 0 0;
  margin: 0 12px;
  box-shadow: 0 -2px 20px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  padding: 0 16px;
}
</style>
