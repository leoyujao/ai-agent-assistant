# AI Agent 对话助手 — 前端文档

Vue3 + Vite 构建的前端项目，通过 SSE（Server-Sent Events）与 FastAPI 后端通信，实现流式 AI 对话体验。

后端文档见 [`../PROJECT.md`](../PROJECT.md)。

---

## 项目结构

```
frontend/
├── index.html                  # Vite 入口 HTML
├── package.json                # 依赖配置
├── vite.config.js              # Vite 配置（开发代理 /api → :8000）
└── src/
    ├── main.js                 # Vue 应用入口
    ├── App.vue                 # 根组件（标题栏 + Tab 切换）
    ├── style.css               # 全局样式（字体、滚动条、链接）
    ├── views/
    │   ├── ChatView.vue        # 聊天页面（消息列表 + 输入框）
    │   └── KnowledgeView.vue   # 知识库管理页面（文件上传 + 状态）
    ├── components/
    │   ├── ChatMessage.vue     # 单条消息气泡（集成工具卡片、引用来源、推理过程）
    │   ├── ToolCard.vue        # 工具调用卡片（状态动画 + 可展开详情）
    │   ├── CitationList.vue    # 参考来源引用列表（web_search 链接 + RAG 知识库文档标签）
    │   └── ReasoningBlock.vue  # 可折叠推理过程（工具步骤时间线）
    └── composables/
        └── useChat.js          # SSE 流式聊天核心逻辑（Composition API Hook）
```

---

## 技术栈

| 包 | 版本 | 用途 |
|---|---|---|
| `vue` | ^3.5 | 响应式 UI 框架 |
| `vite` | ^6.2 | 开发构建工具 |
| `@vitejs/plugin-vue` | ^5.2 | Vite 的 Vue SFC 支持 |
| `marked` | ^15.0 | Markdown 渲染（AI 回复支持代码块、表格等） |
| `dompurify` | ^3.2 | HTML 净化，防止 XSS 注入 |

---

## 核心模块详解

### `useChat.js` — SSE 流式聊天 Hook

核心 Composition API Hook，封装与后端 SSE 通信的完整逻辑，并通过 `localStorage` 持久化会话状态：

```javascript
const STORAGE_KEY = 'ai_chat_session'

export function useChat() {
  const saved = loadSession()                    // 从 localStorage 恢复
  const messages = ref(saved.messages)           // 消息列表 [{role, content, toolCalls, citations, queryRewrite}]
  const streaming = ref(false)                   // 是否正在接收流
  const currentTool = ref(null)                  // 当前正在调用的工具名
  const threadId = ref(saved.threadId)           // 会话 ID（后端返回，checkpointer 关联）
  const error = ref(null)                        // 错误信息

  async function send(text) { ... }              // 发送消息 + SSE 流式接收
  function clear() { ... }                       // 清空历史 + 重置 threadId + 清除 localStorage

  return { messages, streaming, currentTool, currentStep, error, threadId, send, clear }
}
```

**AI 消息数据结构（新增 `toolCalls`、`citations` 和 `queryRewrite`）：**

```javascript
{
  role: 'assistant',
  content: 'LLM 回复的 Markdown 文本',
  toolCalls: [
    {
      name: 'web_search',         // 工具英文名
      label: '网络搜索',           // 工具中文标签
      status: 'done',             // running | done | error
      input: '搜索关键词',
      output: '搜索结果摘要...'
    }
  ],
  citations: [
    // web_search 引用（有 URL，可点击跳转）
    { title: '新闻标题', url: 'https://...' },
    // RAG 知识库引用（无 URL，hover 显示原文片段）
    { title: '文档A.docx', snippet: '原文前150字...' }
  ],
  queryRewrite: {
    // Query Rewrite：RAG 检索前的查询改写
    original: '用户原始查询',
    rewritten: 'LLM 改写后的查询'
  }  // 无查询改写时为 null
}
```

**数据流**：

```
send("搜索今天科技新闻")
  → POST /api/chat  body: { message, thread_id }
  ← SSE: {"type":"tool_call",  "data":{"name":"web_search","input":"科技新闻"}}
       → toolCalls.push({ name, status:'running', input })
  ← SSE: {"type":"tool_result","data":{"name":"web_search","output":"..."}}
       → 匹配 running 条目: status='done', output=...; 从输出正则提取 citations

send("知识库中有什么关于XX的内容？")
  ← SSE: {"type":"query_rewrite","data":{"original":"关于XX","rewritten":"文档中XX功能的详细介绍和相关配置"}}
       → queryRewrite = { original, rewritten }
  ← SSE: {"type":"tool_call",  "data":{"name":"search_knowledge_base","input":"..."}}
  ← SSE: {"type":"tool_result","data":{"name":"search_knowledge_base","output":"...","citations":[{title,snippet}]}}
       → 匹配 running 条目: status='done'; 直接将 citations 数组 push 到 aiMsg

  ← SSE: {"type":"message_chunk","data":{"text":"根据检索..."}}
       → content += text
  ← SSE: {"type":"done",       "data":{"text":"完整回复"}}
```

**关键设计**：
- 使用 `fetch` + `ReadableStream` 读取 SSE 流（比 `EventSource` 更灵活，支持 POST 请求）
- 维护 `buffer` 处理不完整的数据行，避免 JSON 被截断
- `query_rewrite` 事件 → 存储到 `aiMsg.queryRewrite`，在 ChatMessage 中展示改写对比
- `tool_call` 事件 → 追加 `toolCalls` 条目（`status: 'running'`）
- `tool_result` 事件 → 匹配对应条目改为 `status: 'done'`；`web_search` 结果正则提取 citations，`search_knowledge_base` 结果直接读取 `citations` 字段
- 请求体只传 `message` + `thread_id`，会话历史由后端 AsyncSqliteSaver checkpointer 自动管理
- 流结束后显式调用 `saveSession()` 将完整消息（含 toolCalls、citations）持久化到 `localStorage`
- 兼容旧格式：读取 localStorage 时自动补齐 `toolCalls: []`、`citations: []` 和 `queryRewrite: null`

### `ChatMessage.vue` — 消息气泡组件

AI 消息按以下顺序渲染 5 个区块：

```
1. ReasoningBlock  — 「执行过程」折叠块，包含工具调用步骤时间线
1.5 Query Rewrite — 查询改写对比卡片（原始查询划线 → 改写后查询）
2. ToolCard × N   — 每个工具调用一张卡片（状态动画 + 可展开详情）
3. LLM 回复文本   — Markdown 渲染 + XSS 过滤 + 流式光标
4. CitationList   — 参考来源引用 chips（web_search 蓝色链接 + RAG 知识库绿色文档标签）
```

用户消息仍为纯文本气泡（右对齐渐变色）。

### `ToolCard.vue` — 工具调用卡片

- 每次工具调用单独渲染一张卡片，包含图标、中文名称、状态徽章
- `running`：蓝色徽章 + 旋转 spinner；`done`：绿色徽章 + ✓
- 点击卡片可展开/折叠 input（输入）和 output（输出）详情
- 支持 6 种工具的中文标签和专属 emoji 图标

| 工具 | 图标 | 中文标签 |
|------|------|------|
| `web_search` | 🔍 | 网络搜索 |
| `url_reader` | 🌐 | 网页阅读 |
| `calculator` | 🧮 | 计算器 |
| `python_executor` | 🐍 | 代码执行 |
| `get_current_time` | 🕐 | 获取时间 |
| `search_knowledge_base` | 📚 | 知识库检索 |

### `CitationList.vue` — 引用来源列表

- 仅在 `msg.citations` 有内容时渲染（`v-if`）
- **双类型支持**：
  - **有 URL 的引用**（web_search 等）：蓝色 chip，可点击在新标签页打开（`target="_blank"`）
  - **无 URL 的引用**（RAG 知识库溯源）：绿色 chip + 📄 图标，hover 显示原文片段（`title` tooltip）
- 编号圆点颜色区分：蓝色 = 网络来源，绿色 = 文档来源
- 标题过长时省略号截断（`text-overflow: ellipsis`）

**数据格式**：

```javascript
// web_search 引用
{ title: '新闻标题', url: 'https://example.com' }
// RAG 知识库引用（无 url 字段）
{ title: '内部文档.docx', snippet: '原文前150字...' }
```

**后端传递机制**：RAG 引用通过 `tool_result` SSE 事件的 `citations` 字段传递，由 `rag.py` 的 `search()` 函数返回结构化 `(text, sources)` 元组，经 `agent.py` 的 `chat_stream` 在 `on_tool_end` 中注入事件数据。

### `ReasoningBlock.vue` — 推理过程折叠块

- 标题「🧠 执行过程」，点击展开/折叠（过渡动画）
- 内部渲染工具调用**步骤时间线**：竖线连接、圆形状态点（`running` 旋转 / `done` ✓）
- 流式期间默认展开（`defaultOpen` prop），流结束后可手动折叠
- 同时支持可选的推理文本（Markdown 渲染）

### `ChatView.vue` — 聊天页面

- 消息列表自动滚动到底部（watch messages 变化 + nextTick）
- 空状态显示示例问题（点击可直接发送）
- 输入框 Enter 发送，流式期间禁用输入
- 发送按钮流式期间显示 spinner

### `KnowledgeView.vue` — 知识库管理页

- 支持点击选择和拖拽上传 .docx 文件
- 上传使用 `FormData` + `POST /api/upload`
- 显示导入结果列表和当前知识库状态
- 刷新按钮手动更新状态

### `App.vue` — 根组件

- 顶部标题栏（渐变色标题 + 副标题）
- Tab 切换（智能对话 / 知识库）
- 内容区域白色卡片布局

---

## 样式设计

整体配色方案：

| 元素 | 样式 |
|------|------|
| 主色调 | `#667eea` → `#764ba2` 渐变 |
| 页面背景 | `#f5f7fb` |
| 用户气泡 | 渐变色背景 + 白色文字，右下圆角 |
| AI 气泡 | 白色背景 + 浅灰边框，左下圆角 |
| 代码块 | 深色主题 `#1e1e2e`，文字 `#cdd6f4` |
| 滚动条 | 6px 宽度，圆角灰色滑块 |

---

## 开发环境配置

### vite.config.js

```javascript
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

开发时 Vite 将 `/api/*` 请求代理到 FastAPI 后端（`localhost:8000`），前端无需关心跨域问题。

---

## 启动方式

### 安装依赖

```powershell
cd d:\my_agent\frontend
npm install
```

### 开发模式

```powershell
# 确保后端已启动：
# cd d:\my_agent
# .\.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload --reload-exclude "*.db*"
npm run dev
# 访问 http://localhost:5173
```

### 生产构建

```powershell
npm run build
# 产出 dist/ 目录，由 FastAPI 的 StaticFiles 托管
```

---

## 文件职责一览

| 文件 | 职责 | 行数 |
|------|------|------|
| `src/main.js` | Vue 应用入口，挂载 `#app` | ~5 |
| `src/App.vue` | 根组件，标题栏 + Tab 切换 | ~110 |
| `src/style.css` | 全局样式（字体、滚动条、链接） | ~43 |
| `src/views/ChatView.vue` | 聊天页面（消息列表、输入框、示例问题） | ~258 |
| `src/views/KnowledgeView.vue` | 知识库管理（拖拽上传、状态显示） | ~318 |
| `src/components/ChatMessage.vue` | 消息气泡（集成 ToolCard、CitationList、ReasoningBlock） | ~200 |
| `src/components/ToolCard.vue` | 工具调用卡片（状态动画、可展开详情） | ~217 |
| `src/components/CitationList.vue` | 参考来源引用列表（web_search 蓝色链接 + RAG 知识库绿色文档标签） | ~120 |
| `src/components/ReasoningBlock.vue` | 推理过程折叠块（步骤时间线、Markdown 文本） | ~197 |
| `src/composables/useChat.js` | SSE 流式聊天 Hook（toolCalls/citations/queryRewrite 数据模型 + localStorage 持久化） | ~220 |
| `vite.config.js` | Vite 配置（Vue 插件、开发代理） | ~17 |

---

## 与后端的数据交互

| 场景 | 前端操作 | 后端接口 |
|------|---------|---------|
| 发送消息 | `fetch('/api/chat', { POST, body })` | `POST /api/chat` → SSE 流 |
| 上传文档 | `FormData` + `fetch('/api/upload', { POST })` | `POST /api/upload` → JSON |
| 查询状态 | `fetch('/api/kb/status')` | `GET /api/kb/status` → JSON |
| 健康检查 | — | `GET /api/health` → JSON |

---

## 扩展方向

- **流式中断**：AbortController 取消 fetch，后端感知 CancelledError 终止推理
- **消息重试**：失败消息显示重试按钮
- **暗色主题**：CSS 变量 + `prefers-color-scheme` 媒体查询
- **新工具图标**：在 `ToolCard.vue` 的 `TOOL_ICONS` 对象中添加新工具的 emoji 和中文标签
- ~~**引用来源增强**~~：`CitationList.vue` 已支持 `search_knowledge_base` 来源（文档名 + 原文片段，绿色 chip 样式）✅
- ~~**查询改写（Query Rewrite）**~~：已支持 RAG 检索前 LLM 改写查询，前端展示改写对比卡片 ✅
