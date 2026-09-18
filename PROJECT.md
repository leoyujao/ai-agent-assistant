# AI Agent 对话助手 — 项目文档

> 实现细节（各核心文件的代码解析）请参阅 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 项目概述

基于 **LangChain + DeepSeek-v4** 构建的智能对话 Agent，通过 **FastAPI** 提供 REST API + SSE 流式对话接口。  
Agent 具备 **6 大工具调用能力**（实时时钟、数学计算器、RAG 知识库检索、**联网搜索**、**网页阅读**、**Python 代码执行**），采用 ReAct 推理模式自主决策何时使用工具。  
内置 **多 Agent 协作评审机制**：Worker 生成回复后，Reviewer 自动从事实准确性、幻觉检测、完整性三个维度审查，不通过则驱动修正，最多 3 轮，对用户透明。  
联网搜索（`web_search`）和网页阅读（`url_reader`）已按 **能力域拆分**为独立的 **MCP Server**（`mcp_servers/` 目录），通过 stdio 子进程通信，Agent 仅负责编排。  
支持 **Query Rewrite（查询改写）**：在 RAG 检索前使用 LLM 将用户原始查询改写为更适合向量检索的形式，提升召回率。  
使用 **AsyncSqliteSaver** 作为 LangGraph checkpointer，实现会话历史的 SQLite 持久化。  
集成 **LangSmith** 可观测性平台，自动追踪所有 LLM 调用、工具执行和评审循环，无需修改业务代码。
支持上传 **.docx** Word 文档构建知识库，Agent 可基于文档内容进行检索增强问答（RAG）。

前端为独立的 Vue3 项目，会话状态（`threadId` + `messages`）通过 `localStorage` 持久化，AI 回复采用**组件化渲染**（工具卡片、引用来源、推理过程时间线），**评审过程**通过折叠面板实时展示评审轮次与反馈详情，详见 [`frontend/README.md`](frontend/README.md)。

---

## 整体架构

```
Vue3 前端 (localhost:5173)
   │  POST /api/chat  ←→  SSE 统一协议 {type, run_id, thread_id, step, data}
   │  POST /api/upload      （前端通过 localStorage 持久化 threadId + messages）
   │  GET  /api/kb/status
   ↓
[api.py] FastAPI 后端 (localhost:8000)
   │  lifespan 异步初始化 Agent
   │  仅传 thread_id，checkpointer 自动管理历史
   ↓
[agent.py] LangGraph ReAct Agent + AsyncSqliteSaver
   │  checkpointer: AsyncSqliteSaver → checkpoints.db（SQLite 持久化）
   │  rewrite_query(): RAG 检索前用 LLM 改写查询（提升召回率）
   │  load_mcp_tools(): 动态装配 MCP Server 工具（每次调用临时拉起子进程）
   │  ┌─ 多 Agent 协作循环（最多 3 轮）───────────────────────────────────┐
   │  │ Worker (ReAct Agent) 生成草稿 ─→ Reviewer (纯 LLM) 审查  │
   │  │   不通过（revise）→ 注入反馈，Worker 重新生成             │
   │  │   通过（pass）/ 达到上限 → 输出最终回复                   │
   │  └────────────────────────────────────────────────────────────┘
   ↓ 判断是否需要调用工具
[本地工具] get_current_time / calculator / search_knowledge_base / python_executor
[MCP 工具] web_search / url_reader （通过 stdio 子进程调用）
   ↓                              ↓
   ↓                    [rag.py] FAISS 向量检索
   ↓                    [mcp_servers/search.py]  ← stdio 子进程 (ddgs)
   ↓                    [mcp_servers/browser.py] ← stdio 子进程 (requests + bs4)
   ↓                              ↓
   ↓ 返回工具结果
[agent.py] LLM 生成最终回复（评审通过后输出）
   ↓
[api.py] SSE 流式推送到前端
```

---

## 项目结构

```
d:\my_agent\
├── .venv/               # Python 虚拟环境
├── .env                 # 环境变量配置（API 密钥、网关地址、LangSmith，不入库）
├── .env.example         # 环境变量模板
├── requirements.txt     # 后端依赖清单（版本已锁定，pip install -r 安装）
├── vectorstore/         # FAISS 向量库持久化存储（不入库）
│   ├── index.faiss      # 向量索引文件
│   ├── index.pkl        # 向量元数据文件
│   └── loaded_files.json
├── checkpoints.db       # SqliteSaver 会话检查点数据库（运行时自动生成，不入库）
├── mcp_servers/         # MCP Server 子进程工具（按能力域拆分）
│   ├── _common.py       # safe_tool 兜底/截断装饰器（各 server 共用）
│   ├── search.py        # search MCP Server（web_search 工具，ddgs 后端）
│   └── browser.py       # browser MCP Server（url_reader 工具，requests+bs4 后端）
├── api.py               # FastAPI 后端入口（REST API + SSE 流式对话 + lifespan 异步初始化）
├── agent.py             # Agent 核心逻辑（工具装配、AsyncSqliteSaver、LLM 接入、推理）
├── rag.py               # RAG 知识库模块（文档加载、分块、向量化、检索）
├── start_backend.py     # 后端启动入口（Python 内部传参，绕过 PowerShell 通配符展开问题）
├── start_backend.ps1    # 后端启动脚本（PowerShell 版，等价写法）
├── eval_runner.py       # 评估集自动运行脚本（含 MCP 工具预检 + thread_id 隔离）
├── eval_scoring.py      # 评估结果自动评分脚本（工具成功率、幻觉率等指标）
├── eval_dataset.jsonl   # 评估数据集（每行一个测试用例）
├── eval_results.jsonl   # 评估运行原始输出（不入库，运行时生成）
├── eval_scores.jsonl    # 评估评分明细（不入库，运行时生成）
├── eval_report.txt      # 评估汇总报告（不入库，运行时生成）
├── assets/              # 文档截图资源（README 引用）
├── README.md            # 项目介绍与快速开始
├── PROJECT.md           # 项目概览（架构、API、技术栈、扩展指南）
├── ARCHITECTURE.md      # 后端实现详解（api.py / agent.py / rag.py 代码解析）
├── 评估体系工作报告.md  # 评估体系设计说明
└── frontend/            # Vue3 前端项目（详见 frontend/README.md）
    ├── src/
    │   ├── views/           # ChatView.vue / KnowledgeView.vue
    │   ├── components/      # ChatMessage / ToolCard / CitationList / ReasoningBlock / ReviewBlock
    │   └── composables/     # useChat.js
    ├── index.html
    ├── vite.config.js
    └── package.json
```

---

## 环境变量配置（.env）

```ini
# DeepSeek API 配置（公司网关 Anthropic 兼容接口）
ANTHROPIC_BASE_URL=http://your-api-gateway:4000
ANTHROPIC_AUTH_TOKEN=sk-xxxxxxxx
ANTHROPIC_MODEL=deepseek-flash

# HuggingFace 镜像（国内访问加速）
HF_ENDPOINT=https://hf-mirror.com

# LangSmith 可观测性追踪
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_xxxxxxxx
LANGCHAIN_PROJECT=my-agent
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

通过 `python-dotenv` 加载，密钥不硬编码在源码中，保障安全性。

---

## API 接口一览

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/health` | GET | 健康检查（含 Agent、LLM 连通性、向量库、MCP 工具状态） |
| `GET /api/kb/status` | GET | 获取知识库当前状态 |
| `POST /api/upload` | POST | 上传 .docx 文件到知识库（FormData） |
| `POST /api/chat` | POST | 流式对话（SSE text/event-stream） |

### SSE 统一消息协议

所有 SSE 事件均包含 5 个核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 事件类型：`message_chunk` / `query_rewrite` / `tool_call` / `tool_result` / `review_start` / `review_result` / `done` / `error` |
| `run_id` | string | 单次 Agent 执行链路的唯一标识（12 位），用于日志追踪与调试 |
| `thread_id` | string | 会话唯一标识（12 位），支持多轮对话隔离与并发处理 |
| `step` | string | 当前执行阶段：`llm`（LLM 推理）/ `tool`（工具调用）/ `rag`（查询改写）/ `server`（服务端错误） |
| `data` | object | 统一载荷容器，不同类型携带不同结构化数据 |

**各事件类型的 `data` 载荷：**

| type | data 字段 | 说明 |
|------|-----------|------|
| `message_chunk` | `{ text: string }` | LLM 输出的单个 token |
| `query_rewrite` | `{ original: string, rewritten: string }` | RAG 检索前的查询改写 |
| `tool_call` | `{ name: string, input: string }` | 工具开始调用 |
| `tool_result` | `{ name: string, output: string }` | 工具调用完成（截断 500 字符） |
| `review_start` | `{ round: number }` | 评审开始，含当前轮次号 |
| `review_result` | `{ round: number, verdict: "pass"\|"revise", feedback: string }` | 评审完成，含轮次号、判定结果和反馈详情 |
| `done` | `{ text: string }` | 流结束，含完整回复文本 |
| `error` | `{ message: string }` | 错误信息 |

> 典型数据流示例见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

---

## 后端技术栈

| 包 | 版本 | 用途 |
|---|---|---|
| `fastapi` | 0.141.x | Web API 框架 |
| `uvicorn` | 0.52.x | ASGI 服务器 |
| `python-multipart` | 0.0.32 | 文件上传支持 |
| `langchain` | 1.3.14 | LLM 编排框架 |
| `langchain-anthropic` | 1.5.4 | Anthropic 兼容接口适配 |
| `langchain-community` | — | 文档加载器、Embedding、FAISS 向量库 |
| `langchain-text-splitters` | — | 文本分块（RecursiveCharacterTextSplitter） |
| `langchain-mcp-adapters` | 0.3.2 | LangChain 与 MCP Server 通信适配器（`MultiServerMCPClient`，stdio 子进程） |
| `mcp` | 1.x | MCP 协议官方 SDK（FastMCP 装饰器式服务器） |
| `langgraph` | 1.2.10 | ReAct Agent 推理循环 |
| `langgraph-checkpoint-sqlite` | 3.1.1 | AsyncSqliteSaver 会话持久化 checkpointer |
| `aiosqlite` | 0.22.x | 异步 SQLite 连接（AsyncSqliteSaver 依赖） |
| `watchfiles` | 1.2.x | uvicorn --reload 文件监控（排除 .db 文件） |
| `sentence-transformers` | — | HuggingFace Embedding 模型（bge-small-zh-v1.5） |
| `faiss-cpu` | — | 本地向量索引与检索 |
| `docx2txt` | — | Word 文档解析 |
| `langsmith` | 0.10.x | LangSmith 可观测性追踪（自动上报 LLM/工具/Agent 调用链） |
| `python-dotenv` | 1.2.2 | 环境变量加载 |
| `ddgs` | 9.x | DuckDuckGo 联网搜索（`web_search` MCP Server 后端） |
| `requests` | 2.x | HTTP 请求（`url_reader` MCP Server 后端） |
| `beautifulsoup4` | 4.x | HTML 解析，提取网页正文（`url_reader` MCP Server 后端） |

> 完整依赖清单与锁定版本见 [`requirements.txt`](requirements.txt)，安装：`pip install -r requirements.txt`。

---

## 启动方式

### 开发环境

```powershell
# 终端 1：启动后端（推荐用 start_backend.py，已内置 --reload-exclude 配置）
cd d:\my_agent
.\.venv\Scripts\python.exe -X utf8 start_backend.py
# 后端运行在 http://localhost:8000，API 文档：http://localhost:8000/docs
# ⚠️ 不要直接用 uvicorn --reload，PowerShell 5.1 会将 "*.db*" 通配符展开为实际文件名导致报错

# 终端 2：启动前端
cd d:\my_agent\frontend
npm run dev
# 前端运行在 http://localhost:5173
```

### 生产部署

```powershell
# 1. 构建前端
cd frontend; npm run build     # 产出 dist/ 目录

# 2. 启动后端（自动托管前端静态文件，不带 --reload）
cd d:\my_agent
.\.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8000
# 访问 http://localhost:8000 即可使用
```

---

## 工具能力总览

| 工具 | 类型 | 能力 | 适用场景 |
|------|------|------|--------|
| `get_current_time` | 本地 | 获取当前日期时间 | "现在几点"、"今天几号" |
| `calculator` | 本地 | 数学表达式计算 | 加减乘除、幂运算、取余 |
| `search_knowledge_base` | 本地 | RAG 知识库检索 | 涉及已上传 Word 文档的问题 |
| `python_executor` | 本地 | 执行 Python 代码 | 数据分析、复杂运算、文本处理 |
| `web_search` | MCP (search) | DuckDuckGo 联网搜索 | 实时新闻、汇率、知识库外的公开信息 |
| `url_reader` | MCP (browser) | 读取网页正文 | 用户提供 URL 要求阅读/总结/分析 |

> 各工具的实现细节见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

### 如何继续扩展

#### 新增本地工具

在 `agent.py` 中用 `@tool` + `@safe_tool` 装饰器添加新函数，加入 `LOCAL_TOOLS` 列表：

```python
@tool
@safe_tool(error_map={Exception: "天气查询出错"})
def weather_query(city: str) -> str:
    """查询指定城市的天气信息。"""
    return f"{city}今天晴，25°C"

LOCAL_TOOLS = [..., weather_query]
```

#### 新增 MCP Server 工具

**1.** 在 `mcp_servers/` 下创建新 server 文件（如 `weather.py`），使用 FastMCP 装饰器：

```python
from mcp.server.fastmcp import FastMCP
from _common import safe_tool

mcp = FastMCP("weather")

@mcp.tool()
@safe_tool(error_map={Exception: "天气查询出错"})
def weather_query(city: str) -> str:
    """查询指定城市的天气信息。"""
    ...

if __name__ == "__main__":
    mcp.run()
```

**2.** 在 `agent.py` 的 `MCP_SERVERS` 字典中添加配置：

```python
MCP_SERVERS = {
    ...,
    "weather": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [os.path.join(_MCP_DIR, "weather.py")],
        "env": {**os.environ, "PYTHONUTF8": "1"},
    },
}
```

`@safe_tool` 会自动处理：
- **异常兜底**：未捕获的异常统一返回 `"工具执行出错：{类型}: {e}"`
- **输出截断**：默认 4000 字符，可通过 `max_len` 参数调整
- **细粒度错误映射**：通过 `error_map` 参数声明 `{异常类型: 错误前缀}` 映射

---

## RAG 知识库使用流程

1. 启动服务后，在前端 **📚 知识库** 页面上传 `.docx` 格式的 Word 文档
2. 文档将被自动分块（500 字符/块）并使用 `bge-small-zh-v1.5` 模型向量化
3. 向量索引持久化存储在 `vectorstore/` 目录，重启服务后自动加载
4. 在 **💬 智能对话** 页面，提问涉及文档内容时 Agent 会自动调用 `search_knowledge_base` 检索

---

## 已知注意事项

**通用**
- **safe_tool 装饰器**：所有工具均使用 `@safe_tool` 统一封装，添加新工具时务必加上 `@safe_tool` 装饰器（放在 `@tool` 下方），避免裸 `try/except`
- **AsyncSqliteSaver**：必须使用异步版本（`from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver`），同步的 `SqliteSaver` 不支持 `astream_events` 等异步 API
- **异步初始化**：`build_agent()` 为 `async def`，api.py 通过 FastAPI `lifespan` 异步调用
- **uvicorn --reload**：开发模式需加 `--reload-exclude "*.db*"` 排除 checkpoints.db，否则写入时会触发无限重载（需安装 `watchfiles` 包）
- **Anthropic 接口**：`AIMessage.content` 为内容块列表格式，需通过 `_extract_text()` 提取纯文本
- **超时配置**：公司网关响应较慢时，需将 `timeout` 设置较大（当前为 120 秒）
- **HuggingFace 镜像**：`HF_ENDPOINT` 环境变量必须在 `import` HuggingFace 相关库之前设置
- **HuggingFace 离线模式**：`HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` 可避免每次启动时因网络超时导致卡顿
- **FAISS 反序列化**：`FAISS.load_local()` 需传入 `allow_dangerous_deserialization=True`
- **python_executor 安全**：通过黑名单关键字 + 受限 `__builtins__` 双重机制防止危险操作，生产环境建议 Docker 隔离
- **评审 Prompt 花括号转义**：`REVIEW_PROMPT` 模板内包含字面量 JSON 示例（`{"verdict": "pass", ...}`），使用 `.format()` 时必须将花括号转义为 `{{` `}}`，否则会触发 `KeyError: '"verdict"'`，被 except 捕获后默认放行，评审静默失效
- **评审出错默认放行**：`_review_draft` 中任何异常均会捕获并返回 `{"verdict": "pass"}`，保证评审故障不阻塞正常回复
- **ddgs 包名变更**：原 `duckduckgo-search` 包已更名为 `ddgs`，安装和导入均使用 `ddgs`
- **CORS 配置**：开发环境已允许 `localhost:5173` 跨域，生产环境同域无需配置

**MCP Server 相关**
- **MCP 工具仅支持异步调用**：`langchain-mcp-adapters` 将 MCP 工具封装为 coroutine-only，同步调用（`chat()` 的 `agent.invoke()`）会报 `NotImplementedError`，必须使用 `chat_async()` 或 `astream_events()`
- **MCP Server 禁止 `print()`**：Server 子进程的 stdout 是 JSON-RPC 协议通道，任何 `print()` 输出都会污染协议导致调用失败，日志输出必须走 `logging` 写入 stderr
- **MCP Server 环境变量完全替换**：`env` 参数传入后会完全替换子进程环境（而非合并），必须传完整副本 `{**os.environ, ...}`，避免 PATH 等关键变量丢失
- **Windows 终端中文乱码**：MCP Server 日志建议用英文（如 `"search MCP server started (stdio)"`），避免 Windows 默认 GBK 终端解码中文时乱码
- **MCP 装配失败降级**：`load_mcp_tools()` 装配失败时返回空列表并打印警告，服务仍可启动（仅本地工具可用）；`/api/health` 接口会报告 `mcp_tools: degraded` 状态
- **eval_runner 预检**：评估脚本启动时会检查 `/api/health` 的 `mcp_tools` 状态，若 MCP 工具缺失会警告相关用例的工具调用指标可能失真

**LangSmith 相关**
- **零代码接入**：只需设置 `LANGCHAIN_TRACING_V2=true` 和 `LANGCHAIN_API_KEY`，LangChain 自动追踪所有 LLM、工具、Agent 调用，无需修改业务代码
- **追踪范围**：自动捕获 ChatAnthropic 调用、工具调用（含 MCP Server）、评审 Agent 循环、Query Rewrite 等全链路
- **数据区域**：注册时仅支持 US / EU 区域，国内使用选 US 即可
- **免费额度**：Developer Plan 每月 5000 条 trace，开发调试足够
