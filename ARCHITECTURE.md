# 后端实现详解

> 本文档是 [`PROJECT.md`](PROJECT.md) 的补充，包含各核心文件的实现细节。框架概览请参阅 [`PROJECT.md`](PROJECT.md)。

---

## `api.py` — FastAPI 后端入口

提供 REST API 和 SSE 流式对话能力。使用 FastAPI `lifespan` 进行异步初始化。

### 初始化（lifespan）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    print("正在初始化 AI Agent ...")
    agent = await build_agent()   # 异步创建 Agent + AsyncSqliteSaver
    load_vectorstore()
    print("Agent 初始化完成！")
    yield

app = FastAPI(title="AI Agent API", lifespan=lifespan)
```

### 流式对话接口

```python
@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """
    统一 SSE 事件格式：
      data: {"type": "message_chunk",  "run_id": "xxx", "thread_id": "xxx", "step": "llm",  "data": {"text": "..."}}
      data: {"type": "query_rewrite", "run_id": "xxx", "thread_id": "xxx", "step": "rag",  "data": {"original": "...", "rewritten": "..."}}
      data: {"type": "tool_call",     "run_id": "xxx", "thread_id": "xxx", "step": "tool", "data": {"name": "...", "input": "..."}}
      data: {"type": "tool_result",   "run_id": "xxx", "thread_id": "xxx", "step": "tool", "data": {"name": "...", "output": "..."}}
      data: {"type": "done",          "run_id": "xxx", "thread_id": "xxx", "step": "llm",  "data": {"text": "完整回复"}}
      data: {"type": "error",         "run_id": "xxx", "thread_id": "xxx", "step": "llm", "data": {"message": "..."}}
    """
    thread_id = req.thread_id or uuid.uuid4().hex[:12]

    async def event_generator():
        async for event in chat_stream(agent, req.message, thread_id=thread_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**请求体（`ChatRequest`）：**

```json
{
  "message": "搜索今天的科技新闻",
  "thread_id": "abc123"
}
```

会话历史由 AsyncSqliteSaver checkpointer 按 `thread_id` 自动管理，前端无需传递 `history`。

### SSE 统一消息协议

所有 SSE 事件均包含 5 个核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 事件类型：`message_chunk` / `query_rewrite` / `tool_call` / `tool_result` / `review_start` / `review_result` / `done` / `error` |
| `run_id` | string | 单次 Agent 执行链路的唯一标识（12 位），用于日志追踪与调试 |
| `thread_id` | string | 会话唯一标识（12 位），支持多轮对话隔离与并发处理 |
| `step` | string | 当前执行阶段：`llm`（LLM 推理）/ `tool`（工具调用）/ `rag`（查询改写）/ `server`（服务端错误） |
| `data` | object | 统一载荷容器，不同类型携带不同结构化数据（见下表） |

**各事件类型的 `data` 载荷：**

| type | data 字段 | 说明 |
|------|-----------|------|
| `message_chunk` | `{ text: string }` | LLM 输出的单个 token |
| `query_rewrite` | `{ original: string, rewritten: string }` | RAG 检索前的查询改写，含原始查询和改写后查询 |
| `tool_call` | `{ name: string, input: string }` | 工具开始调用，含工具名和输入参数 |
| `tool_result` | `{ name: string, output: string }` | 工具调用完成，含工具名和输出结果（截断 500 字符） |
| `review_start` | `{ round: number }` | 评审开始，含当前轮次号 |
| `review_result` | `{ round: number, verdict: "pass"\|"revise", feedback: string }` | 评审完成，含轮次号、判定结果和反馈详情 |
| `done` | `{ text: string }` | 流结束，含完整回复文本 |
| `error` | `{ message: string }` | 错误信息 |

**典型数据流示例：**

```
data: {"type":"query_rewrite","run_id":"a1b2c3","thread_id":"x9y8z7","step":"rag","data":{"original":"那个东西是什么","rewritten":"文档中关于XX功能的详细介绍"}}
data: {"type":"tool_call","run_id":"a1b2c3","thread_id":"x9y8z7","step":"tool","data":{"name":"search_knowledge_base","input":"{'query': '那个东西是什么'}"}}
data: {"type":"tool_result","run_id":"a1b2c3","thread_id":"x9y8z7","step":"tool","data":{"name":"search_knowledge_base","output":"检索结果..."}}
data: {"type":"message_chunk","run_id":"a1b2c3","thread_id":"x9y8z7","step":"llm","data":{"text":"根据"}}
data: {"type":"message_chunk","run_id":"a1b2c3","thread_id":"x9y8z7","step":"llm","data":{"text":"搜索"}}
data: {"type":"done","run_id":"a1b2c3","thread_id":"x9y8z7","step":"llm","data":{"text":"根据搜索..."}}
```

### 文件上传接口

```python
@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """接收 .docx 文件，写入临时文件后调用 rag.load_and_index()"""
    # 遍历上传文件 → 校验 .docx → 写入临时文件 → load_and_index → 清理
    return {"results": [...], "status": get_status()}
```

### 静态文件托管（生产部署）

```python
DIST_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="static")
```

Vue 打包后（`npm run build`），FastAPI 直接托管 `frontend/dist/` 目录，访问 `http://localhost:8000` 即可使用。

---

## `agent.py` — Agent 核心逻辑

### 1. 工具定义与装配

Agent 的 6 个工具分为两类：**本地轻量工具**（零依赖/本地状态）和 **MCP Server 工具**（按能力域拆分，通过 stdio 子进程运行）。

#### 本地工具（`LOCAL_TOOLS`）

使用 `@tool` + `@safe_tool` 装饰器声明。`@safe_tool` 统一封装错误处理和输出截断，避免裸 `try/except` 散落在各工具中：

```python
def safe_tool(error_map: dict[type, str] | None = None, max_len: int = 4000):
    """
    工具统一封装装饰器，替代裸 try/except。
    - error_map: 细粒度异常映射 {异常类型: 错误前缀}，按声明顺序匹配，未命中走兜底
    - max_len: 输出截断长度，0 表示不截断
    """
```

本地工具定义：

```python
@tool
@safe_tool()
def get_current_time() -> str:
    """获取当前日期和时间，当用户询问今天日期、现在几点等问题时使用。"""

@tool
@safe_tool(max_len=500)
def calculator(expression: str) -> str:
    """计算数学表达式，当用户需要进行数学运算时使用。"""
    # 白名单校验后直接 eval，异常由装饰器兜底

@tool
@safe_tool(error_map={Exception: "知识库检索出错"})
def search_knowledge_base(query: str) -> str:
    """在已上传的知识库文档中检索相关信息。"""
    from rag import search_text
    # Query Rewrite：优先使用 chat_stream 缓存的改写结果
    rewritten = _rewrite_cache.pop(query, None) or rewrite_query(query)
    return search_text(rewritten)

@tool
@safe_tool(max_len=0)  # 内部已做截断，装饰器不再二次截断
def python_executor(code: str) -> str:
    """执行 Python 代码并返回输出结果。"""
    # 安全黑名单校验 → 受限 __builtins__ 执行 → 捕获 stdout/stderr

LOCAL_TOOLS = [get_current_time, calculator, search_knowledge_base, python_executor]
```

各本地工具的安全设计与 `safe_tool` 配置：

| 工具 | 安全机制 | safe_tool 配置 |
|------|--------|---------------|
| `get_current_time` | 无特殊限制 | `@safe_tool()` 默认兜底 + 4000 字符截断 |
| `calculator` | 白名单字符校验，仅允许数字和 `+-*/%()` | `@safe_tool(max_len=500)` |
| `search_knowledge_base` | 依赖 rag 模块 + Query Rewrite | `@safe_tool(error_map={Exception: "知识库检索出错"})` |
| `python_executor` | 黑名单 + 受限 `__builtins__` + 3000 字符截断 | `@safe_tool(max_len=0)` 内部保留细粒度 except |

#### MCP Server 工具（`MCP_SERVERS`）

`web_search` 和 `url_reader` 已按**能力域拆分**为独立的 MCP Server，以 stdio 子进程方式运行。每个 Server 都是独立进程，内部拥有自己的 `safe_tool` 装饰器（与 agent.py 中的独立拷贝，避免 server 子进程拉起 Agent 的 LLM 初始化）。

MCP Server 配置与装配：

```python
MCP_SERVERS = {
    "search": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [os.path.join(_MCP_DIR, "search.py")],
        "env": {**os.environ, "PYTHONUTF8": "1"},  # Windows 下防止中文乱码
    },
    "browser": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [os.path.join(_MCP_DIR, "browser.py")],
        "env": {**os.environ, "PYTHONUTF8": "1"},
    },
}

async def load_mcp_tools() -> list:
    """从 MCP Server 装配工具。
    langchain-mcp-adapters 0.3+ 的 stdio 模式：每次工具调用临时拉起子进程，
    客户端不持有长连接，无需 AsyncExitStack 管理生命周期。
    装配失败时整体降级为空列表并打印警告，保证服务仍可启动。
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        print("⚠️ 未安装 langchain-mcp-adapters，跳过 MCP 工具")
        return []
    try:
        client = MultiServerMCPClient(MCP_SERVERS)
        tools = await client.get_tools()
        print(f"✅ MCP 工具装配成功：{[t.name for t in tools]}")
        return tools
    except Exception as e:
        print(f"⚠️ MCP 工具装配失败，Agent 降级为仅本地工具：{e}")
        return []
```

各 MCP Server 工具的架构：

| MCP Server | 工具 | 后端 | 错误文案 | safe_tool 配置 |
|------------|------|------|----------|---------------|
| `mcp_servers/search.py` | `web_search` | ddgs | `"搜索出错"` | `@safe_tool(error_map={Exception: "搜索出错"})` |
| `mcp_servers/browser.py` | `url_reader` | requests + bs4 | `"访问超时"` / `"HTTP 错误"` | `@safe_tool(max_len=0)` 内部 4000 字符截断 |

#### MCP Server 侧规范（Windows stdio）

- **严禁 `print()`**：stdout 是 JSON-RPC 协议通道，调试输出会污染协议
- **日志走 `logging`**：输出到 stderr，不影响协议
- **日志消息用英文**：Windows 默认 GBK 终端解码中文会乱码
- **`PYTHONUTF8=1`**：子进程必须显式设置，防止中文结果过协议通道时乱码或崩溃
- **`sys.executable`**：确保用当前 .venv 的 Python 解释器，避免 PATH 解析到未装依赖的系统 Python

#### MCP Server 架构特性

- **langchain-mcp-adapters 0.3+**：每次工具调用临时拉起子进程，客户端不持有长连接
- **无需 AsyncExitStack**：不存在进程泄漏、循环绑定、reload 干扰等生命周期问题
- **每次调用开销 ~1 秒**：子进程启动 + 模块导入，对秒级网络操作可接受
- **优雅降级**：MCP 装配失败时仅保留本地工具 + 醒目警告，服务仍可启动

### 2. Query Rewrite（查询改写）

在 RAG 检索前使用 LLM 将用户查询改写为更适合向量检索的形式，提升召回率。

```python
REWRITE_PROMPT = """你是一个查询改写助手。请将用户的原始查询改写为更适合在知识库中进行向量检索的查询。

改写原则：
1. 保持原始查询的核心意图
2. 展开缩写、补充上下文关键词
3. 使用更具体、更完整的表述
4. 如果查询已经足够清晰，只做轻微调整
5. 只输出改写后的查询，不要任何解释"""

def rewrite_query(original_query: str) -> str:
    """使用 LLM 改写用户查询，使其更适合知识库向量检索。"""
    if llm is None:
        return original_query
    try:
        response = llm.invoke([
            {"role": "system", "content": REWRITE_PROMPT},
            {"role": "user", "content": original_query},
        ])
        rewritten = _extract_text(response.content).strip()
        if not rewritten or len(rewritten) > 300:
            return original_query
        return rewritten
    except Exception:
        return original_query
```

**缓存机制**（避免重复调用 LLM）：

```python
_rewrite_cache: dict[str, str] = {}  # chat_stream 写入，search_knowledge_base 读取
```

- `chat_stream` 的 `on_tool_start` 中检测 `search_knowledge_base`，调用改写并写入缓存，同时发送 `query_rewrite` SSE 事件
- `search_knowledge_base` 工具函数 `pop` 消费缓存，避免重复调用 LLM
- 非 SSE 流式调用（`chat()`）走兜底路径自行改写

### 3. 构建 Agent（异步 + checkpointer）

```python
async def build_agent():
    llm = ChatAnthropic(
        model=os.getenv("ANTHROPIC_MODEL", "deepseek-v4-flash"),
        anthropic_api_url=os.getenv("ANTHROPIC_BASE_URL"),
        anthropic_api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
        temperature=0.7,
        timeout=120,
        max_retries=2,
    )

    # 创建 AsyncSqliteSaver checkpointer（持久化会话历史）
    conn = await aiosqlite.connect(CHECKPOINT_DB)
    checkpointer = AsyncSqliteSaver(conn)

    # 本地工具 + MCP Server 工具
    tools = list(LOCAL_TOOLS) + await load_mcp_tools()

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
        checkpointer=checkpointer,
    )
    return agent
```

**checkpointer 机制**：
- 使用 `AsyncSqliteSaver`（而非同步的 `SqliteSaver`），因为 `astream_events` 是异步 API
- 会话历史持久化存储在 `checkpoints.db`，服务重启后同一 `thread_id` 的上下文不丢失
- `build_agent()` 为 `async def`，通过 FastAPI lifespan 异步调用

**ReAct 模式**（Reasoning + Acting）工作流：

```
用户提问 → LLM 思考 → 决定是否调用工具 → 执行工具 → 读取结果 → 生成最终回复
```

### 4. Anthropic 内容格式适配

Anthropic 接口返回的 `content` 是**内容块列表**，而非纯字符串：

```python
# Anthropic 返回格式（包含思考块 + 文本块）
[
  {"type": "thinking", "thinking": "...内部推理过程..."},
  {"type": "text",     "text":     "Hi! 这是最终回复内容"}
]
```

`_extract_text()` 函数只提取 `type="text"` 的块，丢弃 `thinking` 块：

```python
def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)
```

### 5. 异步 chat_async 函数

MCP Server 工具在 langchain-core 内部被封装为 coroutine-only，同步调用会报 `NotImplementedError`，因此所有对话均走异步入口：

```python
async def chat_async(agent, user_input: str, thread_id: str = "default") -> tuple[str, list]:
    """异步对话入口，包含评审循环。"""
    config = {"configurable": {"thread_id": thread_id}}
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_input)]}, config=config
    )
    reply_text = _extract_text(result["messages"][-1].content)
    return reply_text, result["messages"]
```

### 6. 异步 chat_stream 函数（SSE 流式）

供 `api.py` 调用，使用 LangGraph 的 `astream_events` API 逐 token 输出，采用统一 SSE 消息协议：

```python
async def chat_stream(agent, user_input: str, thread_id: str = "default"):
    """流式对话，async generator，yield 统一 SSE 事件字典。
    通过 checkpointer + thread_id 自动管理会话历史。
    内置评审 Agent 循环（最多 MAX_REVIEW_ROUNDS 轮）。"""
    config = {"configurable": {"thread_id": thread_id}}

    run_id = uuid.uuid4().hex[:12]
    original_input = user_input   # 评审始终使用原始问题

    for review_round in range(1, MAX_REVIEW_ROUNDS + 2):
        # ① 缓存本轮 Worker 的 message_chunk 和工具事件
        draft_chunks, worker_events = [], []
        async for event in agent.astream_events(...):
            # 收集事件，中间轮次不输出 message_chunk
            ...

        # ② 始终输出 tool_call / tool_result / query_rewrite 事件
        for ev in worker_events:
            yield ev

        # ③ 提取工具调用证据，调用评审 Agent
        evidence = "\n".join(tool_output 文本)
        review = await _review_draft(original_input, full_text, evidence)
        yield {"type": "review_start", "data": {"round": review_round}}
        yield {"type": "review_result", "data": {"round": review_round, **review}}

        # ④ 判断是否通过
        if review["verdict"] == "pass" or review_round > MAX_REVIEW_ROUNDS:
            # 输出缓存的 message_chunk + done
            for chunk in draft_chunks: yield chunk
            yield {"type": "done", "data": {"text": full_text}}
            break

        # ⑤ 不通过，构造反馈注入下一轮
        user_input = f"[评审修正请求] 请根据以下反馈修正你的回复：{review['feedback']}"
```

**关键设计：**
- `run_id` 每次调用自动生成，用于追踪单次 Agent 执行链路
- `thread_id` 由前端传入或自动生成，checkpointer 自动按 thread_id 加载/保存历史
- `config={"configurable": {"thread_id": ...}}` 是 LangGraph checkpointer 的标准用法
- `tool_result.output` 截断 500 字符，避免 SSE 单条消息过大
- **中间轮次不输出 `message_chunk`**：草稿被缓存，仅评审通过后才发送，避免用户看到不完整回复
- **评审始终使用 `original_input`**：修正轮次的 `user_input` 被替换为反馈提示，但评审仍对照原始问题

### 7. 评审 Agent（多 Agent 协作循环）

Worker（ReAct Agent）和 Reviewer（纯 LLM）组成内循环，对用户透明，最多运行 `MAX_REVIEW_ROUNDS`（默认 3）轮。

```python
MAX_REVIEW_ROUNDS = 3
```

#### 评审提示词（`REVIEW_PROMPT`）

```python
REVIEW_PROMPT = """你是一个严格的质量评审员。请审查 AI 助手对用户问题的回复。

## 用户原始问题
{question}

## AI 助手的回复
{draft}

## 工具调用证据
{evidence}

## 评审维度
1. 事实准确性：回复中引用的数据/事实是否与工具返回的证据一致
2. 幻觉检测：是否编造了工具未返回的内容（如虚构的新闻、数据、链接）
3. 完整性：是否充分回答了用户的问题

## 输出格式
必须输出合法 JSON，不要包含任何其他文字：
{{"verdict": "pass", "feedback": ""}}
或
{{"verdict": "revise", "feedback": "具体需要修正的问题"}}

判定标准：
- pass：回复事实准确、无幻觉、完整回答了用户问题
- revise：回复中存在事实错误、幻觉或不完整，需要修正"""
```

> ⚠️ 注意：模板中字面量 JSON 的花括号必须用 `{{` `}}` 转义，否则 `.format()` 会报 `KeyError: '"verdict"'`。

#### 评审函数（`_review_draft`）

```python
async def _review_draft(question: str, draft: str, evidence: str) -> dict:
    """异步调用 LLM 进行评审，返回 {"verdict": "pass"/"revise", "feedback": "..."}。
    采用三重容错解析策略，任何异常均默认放行（verdict=pass）。"""
    if llm is None:
        return {"verdict": "pass", "feedback": ""}
    try:
        review_msg = REVIEW_PROMPT.format(question=question, draft=draft, evidence=evidence)
        response = await llm.ainvoke([{"role": "user", "content": review_msg}])
        text = _extract_text(response.content).strip()

        # 策略 1：剥离 markdown 代码块包裹后直接 json.loads
        cleaned = text
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned).strip()

        # 策略 2：正则提取最后一个 {...} JSON 对象
        result = None
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            for m in reversed(list(re.finditer(r'\{[^{}]*\}', text))):
                try:
                    result = json.loads(m.group())
                    break
                except json.JSONDecodeError:
                    continue

        if result and isinstance(result, dict):
            verdict = result.get("verdict", "pass")
            if verdict not in ("pass", "revise"):
                verdict = "pass"
            return {"verdict": verdict, "feedback": result.get("feedback", "")}

        return {"verdict": "pass", "feedback": ""}  # 无法解析，默认放行
    except Exception as e:
        return {"verdict": "pass", "feedback": f"评审出错: {type(e).__name__}: {e}"}
```

**设计要点：**

| 机制 | 说明 |
|------|------|
| 三重容错解析 | 剥离 markdown → `json.loads` → 正则提取 → 兜底 pass，防止 LLM 输出格式不稳定 |
| 异常默认放行 | 所有异常均捕获，保证评审故障不阻塞正常回复 |
| 证据对齐 | 评审的核心是比对草稿与工具返回的证据，确保没有编造工具未返回的内容 |
| 反馈闭环 | 修正轮次通过 `[评审修正请求]` 前缀注入下一轮 messages，Worker 根据反馈改进回复 |
| 原始问题保留 | 评审始终使用 `original_input`（原始用户问题），避免反馈替换后失去评审基准 |

#### 前端评审展示

`ReviewBlock.vue` 组件以折叠面板形式展示评审过程：

- **输入**：`reviews: Array` — 包含 `{ round, verdict, feedback }` 对象的数组
- **verdict 视觉化**：pass 显示绿色 ✓，revise 显示黄色 ✗
- **默认折叠**：不影响阅读流，点击展开查看完整评审过程
- **事件驱动更新**：`useChat.js` 监听 `review_start`（追加新轮次）和 `review_result`（更新 verdict + feedback）实时渲染

---

## `rag.py` — RAG 知识库模块

负责文档加载、文本分块、向量化存储与相似度检索的完整 RAG 流程。

---

## LangSmith 可观测性集成

通过环境变量零代码接入，LangChain 自动将所有 LLM /工具 / Agent 调用上报到 LangSmith 平台。

### 接入方式

仅在 `.env` 中配置环境变量，无需修改任何业务代码：

```ini
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_xxxxxxxx
LANGCHAIN_PROJECT=my-agent
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

`python-dotenv` 加载后，LangChain 的 callback 系统自动检测 `LANGCHAIN_TRACING_V2=true` 并启用追踪。

### 自动追踪范围

| 组件 | 追踪内容 |
|--------|----------|
| ChatAnthropic | 每次 LLM 调用（invoke/ainvoke/astream）的输入输出、token 用量、延迟 |
| 本地工具 | `get_current_time`、`calculator`、`search_knowledge_base`、`python_executor` 的调用参数和返回值 |
| MCP Server 工具 | `web_search`、`url_reader` 的跨进程调用 |
| 评审 Agent | 每轮评审的输入（草稿 + 证据）和输出（verdict + feedback） |
| Query Rewrite | RAG 检索前的查询改写调用 |
| LangGraph | ReAct Agent 的完整执行链路（思考→工具调用→观察→回复） |

### 查看 Trace

访问 https://smith.langchain.com → **Projects → my-agent**，可看到每次对话的完整执行链路，支持按时间、run_id、工具名称筛选，并可对比不同 Prompt 版本的输出质量。

### 全局状态

```python
STORE_DIR = os.path.join(os.path.dirname(__file__), "vectorstore")
_embedding = None      # 延迟加载 Embedding 模型
_vectorstore = None    # FAISS 向量库
_doc_count = 0         # 已导入文档块数量
_loaded_files = []     # 已加载的文件名列表
```

### 1. HuggingFace 镜像 + 离线优先配置

```python
# 【必须在 import huggingface/sentence-transformers 之前设置】
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
```

**关键**：
- `HF_ENDPOINT` 必须在 `import` HuggingFace 相关库之前设置，否则无法连接国内镜像。
- `HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1` 使已缓存的模型直接离线加载，首次需联网下载模型，后续均走本地缓存。

### 2. Embedding 模型（懒加载）

```python
def _get_embedding():
    """懒加载 Embedding 模型（首次调用时下载并缓存，约 100MB）"""
    global _embedding
    if _embedding is None:
        _embedding = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedding
```

### 3. 文本分割器（中文优化）

```python
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=60,
    separators=["\n\n", "\n", "。", ".", "，", ",", " ", ""],
    length_function=len,
)
```

### 4. 文档加载与索引

```python
def load_and_index(file_path: str) -> dict:
    """加载 .docx 文件并加入 FAISS 向量库。"""
    loader = Docx2txtLoader(file_path)
    docs = loader.load()
    chunks = _splitter.split_documents(docs)
    chunks = [c for c in chunks if c.page_content.strip()]
    embedding = _get_embedding()

    if _vectorstore is None:
        _vectorstore = FAISS.from_documents(chunks, embedding)
    else:
        _vectorstore.add_documents(chunks)

    _save_vectorstore()
    _doc_count += len(chunks)
    return {"chunks": len(chunks), "file": file_name}
```

### 5. 向量库持久化

```python
def _save_vectorstore():
    if _vectorstore is None: return
    os.makedirs(STORE_DIR, exist_ok=True)
    _vectorstore.save_local(STORE_DIR)

def load_vectorstore():
    if os.path.exists(os.path.join(STORE_DIR, "index.faiss")):
        embedding = _get_embedding()
        _vectorstore = FAISS.load_local(STORE_DIR, embedding,
                                         allow_dangerous_deserialization=True)
        _doc_count = _vectorstore.index.ntotal
```

### 6. 相似度检索

```python
def search(query: str, top_k: int = 3) -> tuple[str, list[dict]]:
    """返回 (text, sources) 元组，text 供 LLM 阅读，sources 供前端引用溯源。"""
    if _vectorstore is None:
        return "（知识库为空，请先上传文档。）", []
    results = _vectorstore.similarity_search(query, k=top_k)
    # 拼接带来源标注的检索结果，sources = [{title, snippet}]
    return "\n\n".join(output_parts), sources

def search_text(query: str, top_k: int = 3) -> str:
    """search() 的纯文本包装，引用元数据通过 _last_sources 模块变量暂存。"""
    text, sources = search(query, top_k)
    _last_sources = sources
    return text
```

### 7. 知识库状态查询

```python
def get_status() -> dict:
    """返回结构化状态：doc_count / files / message。"""
    if _vectorstore is None:
        return {"doc_count": 0, "files": [], "message": "知识库为空，请上传 .docx 文档"}
    return {
        "doc_count": _doc_count,
        "files": unique_files,
        "message": f"已导入 {_doc_count} 个文档块，共 {len(unique_files)} 个文件",
    }
```
