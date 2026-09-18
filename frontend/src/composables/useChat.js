/**
 * SSE 流式聊天 Hook
 * 负责与后端 /api/chat 通信，采用统一 SSE 消息协议
 *
 * 协议格式：
 *   { type, run_id, thread_id, step, data }
 *   type: message_chunk | query_rewrite | tool_call | tool_result | review_start | review_result | done | error
 *
 * 消息模型（assistant）：
 *   { role, content, toolCalls: [{name, status, input, output}], citations: [{title, url}], reviews: [{round, verdict, feedback}] }
 */
import { ref, watch } from 'vue'

const STORAGE_KEY = 'ai_chat_session'

// 工具显示名 → 中文友好名
const TOOL_LABELS = {
  web_search: '网络搜索',
  url_reader: '网页阅读',
  calculator: '计算器',
  python_executor: '代码执行',
  get_current_time: '获取时间',
  search_knowledge_base: '知识库检索',
}

// 从 web_search 输出中提取引用链接
function extractCitations(output) {
  if (!output) return []
  const citations = []
  const re = /【结果 \d+】(.+?)\n[\s\S]*?链接：(https?:\/\/\S+)/g
  let m
  while ((m = re.exec(output)) !== null) {
    citations.push({ title: m[1].trim(), url: m[2].trim() })
  }
  return citations
}

// 创建空的 AI 消息
function createAiMessage() {
  return { role: 'assistant', content: '', toolCalls: [], citations: [], queryRewrite: null, reviews: [] }
}

// 从 localStorage 恢复会话状态
function loadSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const data = JSON.parse(raw)
      // 兼容旧格式：确保每条 assistant 消息有 toolCalls / citations / queryRewrite
      if (data.messages) {
        data.messages = data.messages.map(m =>
          m.role === 'assistant'
            ? { toolCalls: [], citations: [], queryRewrite: null, reviews: [], ...m }
            : m
        )
      }
      return data
    }
  } catch { /* ignore */ }
  return { threadId: null, messages: [] }
}

// 保存会话到 localStorage
function saveSession(threadId, messages) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ threadId, messages }))
}

export function useChat() {
  const saved = loadSession()
  const messages = ref(saved.messages)
  const streaming = ref(false)
  const currentTool = ref(null)
  const currentStep = ref(null)
  const error = ref(null)
  const threadId = ref(saved.threadId)

  // 自动同步到 localStorage（非流式状态时）
  watch([threadId, messages], () => {
    if (!streaming.value) {
      saveSession(threadId.value, messages.value)
    }
  }, { deep: true })

  /**
   * 发送消息并接收流式回复
   * @param {string} text - 用户输入
   */
  async function send(text) {
    if (!text.trim() || streaming.value) return

    messages.value.push({ role: 'user', content: text })
    messages.value.push(createAiMessage())

    streaming.value = true
    error.value = null
    currentStep.value = null

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          thread_id: threadId.value,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      const aiMsg = messages.value[messages.value.length - 1]
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6).trim()
          if (!jsonStr) continue

          try {
            const event = JSON.parse(jsonStr)

            if (event.thread_id && !threadId.value) {
              threadId.value = event.thread_id
            }

            switch (event.type) {
              case 'message_chunk':
                aiMsg.content += event.data.text
                currentStep.value = event.step
                break

              case 'query_rewrite':
                aiMsg.queryRewrite = {
                  original: event.data.original,
                  rewritten: event.data.rewritten,
                }
                currentStep.value = 'rag'
                break

              case 'tool_call': {
                const tc = {
                  name: event.data.name,
                  label: TOOL_LABELS[event.data.name] || event.data.name,
                  status: 'running',
                  input: event.data.input || '',
                  output: '',
                }
                aiMsg.toolCalls.push(tc)
                currentTool.value = event.data.name
                currentStep.value = 'tool'
                break
              }

              case 'tool_result': {
                // 找到最后一个匹配名称且 status=running 的工具调用
                const tcs = aiMsg.toolCalls
                for (let i = tcs.length - 1; i >= 0; i--) {
                  if (tcs[i].name === event.data.name && tcs[i].status === 'running') {
                    tcs[i].status = 'done'
                    tcs[i].output = event.data.output || ''
                    break
                  }
                }
                // 从 web_search 结果中提取引用
                if (event.data.name === 'web_search' && event.data.output) {
                  const newCitations = extractCitations(event.data.output)
                  aiMsg.citations.push(...newCitations)
                }
                // 从 search_knowledge_base 结果中提取引用（结构化数据，后端直接附加）
                if (event.data.name === 'search_knowledge_base' && event.data.citations) {
                  aiMsg.citations.push(...event.data.citations)
                }
                currentTool.value = null
                break
              }

              case 'review_start': {
                // 评审开始，追加一条评审记录（verdict 待定）
                if (!aiMsg.reviews) aiMsg.reviews = []
                aiMsg.reviews.push({
                  round: event.data.round,
                  verdict: 'pending',
                  feedback: '',
                })
                currentStep.value = 'review'
                break
              }

              case 'review_result': {
                // 评审结果：更新最后一条评审记录
                if (aiMsg.reviews && aiMsg.reviews.length > 0) {
                  const lastReview = aiMsg.reviews[aiMsg.reviews.length - 1]
                  lastReview.verdict = event.data.verdict
                  lastReview.feedback = event.data.feedback || ''
                }
                currentStep.value = 'review'
                break
              }

              case 'done':
                currentStep.value = null
                break

              case 'error':
                error.value = event.data.message
                aiMsg.content = `❌ ${event.data.message}`
                break
            }
          } catch (e) {
            console.warn('解析 SSE 数据失败:', jsonStr, e)
          }
        }
      }
    } catch (e) {
      error.value = e.message
      const aiMsg = messages.value[messages.value.length - 1]
      if (!aiMsg.content) {
        aiMsg.content = `❌ 请求失败：${e.message}`
      }
    } finally {
      streaming.value = false
      currentTool.value = null
      currentStep.value = null
      saveSession(threadId.value, messages.value)
    }
  }

  function clear() {
    messages.value = []
    error.value = null
    threadId.value = null
    localStorage.removeItem(STORAGE_KEY)
  }

  return { messages, streaming, currentTool, currentStep, error, threadId, send, clear }
}
