import functools
import io
import json
import os
import re
import subprocess
import sys
import textwrap
import uuid
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime

import aiosqlite
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

# 加载环境变量
load_dotenv()

# ──────────────────────────────────────────────
# 工具统一封装装饰器
# ──────────────────────────────────────────────

def safe_tool(error_map: dict[type, str] | None = None, max_len: int = 4000):
    """
    工具统一封装装饰器，替代裸 try/except。

    - error_map: 细粒度异常映射 {异常类型: 错误前缀}，按声明顺序匹配，未命中走兜底
    - max_len: 输出截断长度，0 表示不截断
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                if max_len and isinstance(result, str) and len(result) > max_len:
                    result = result[:max_len] + "\n…（输出过长，已截断）"
                return result
            except Exception as e:
                if error_map:
                    for exc_type, prefix in error_map.items():
                        if isinstance(e, exc_type):
                            return f"{prefix}：{e}"
                return f"工具执行出错：{type(e).__name__}: {e}"
        return wrapper
    return decorator


# ──────────────────────────────────────────────
# Query Rewrite（查询改写）
# ──────────────────────────────────────────────

REWRITE_PROMPT = """你是一个查询改写助手。请将用户的原始查询改写为更适合在知识库中进行向量检索的查询。

改写原则：
1. 保持原始查询的核心意图
2. 展开缩写、补充上下文关键词
3. 使用更具体、更完整的表述
4. 如果查询已经足够清晰，只做轻微调整
5. 只输出改写后的查询，不要任何解释

直接输出改写后的查询文本："""


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
        # 过滤无效改写
        if not rewritten or len(rewritten) > 300:
            return original_query
        return rewritten
    except Exception:
        return original_query


# 查询改写缓存：chat_stream 写入，search_knowledge_base 读取
_rewrite_cache: dict[str, str] = {}


# ──────────────────────────────────────────────
# 评审 Agent（Reviewer）
# ──────────────────────────────────────────────

MAX_REVIEW_ROUNDS = 3  # 最大评审轮次

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


async def _review_draft(question: str, draft: str, evidence: str) -> dict:
    """调用评审 Agent 审查回复草稿。返回 {"verdict": "pass"/"revise", "feedback": "..."}。"""
    if llm is None:
        return {"verdict": "pass", "feedback": ""}
    try:
        review_msg = REVIEW_PROMPT.format(
            question=question,
            draft=draft,
            evidence=evidence or "（无工具调用）",
        )
        response = await llm.ainvoke([
            {"role": "user", "content": review_msg},
        ])
        text = _extract_text(response.content).strip()

        # 策略 1：剥离 markdown 代码块包裹后尝试解析
        cleaned = text
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            cleaned = cleaned.strip()

        # 策略 2：尝试提取 JSON（兼容被其他文字包裹的情况）
        result = None
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            # 正则提取最后一个 JSON 对象
            matches = list(re.finditer(r'\{[^{}]*\}', text))
            for m in reversed(matches):
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

        # 解析失败，默认放行
        return {"verdict": "pass", "feedback": ""}
    except Exception as e:
        # 评审出错时默认放行，避免阻塞正常回复
        return {"verdict": "pass", "feedback": f"评审出错: {type(e).__name__}: {e}"}


# ──────────────────────────────────────────────
# 工具定义
# ──────────────────────────────────────────────

@tool
@safe_tool()
def get_current_time() -> str:
    """获取当前日期和时间，当用户询问今天日期、现在几点等问题时使用。"""
    now = datetime.now()
    return now.strftime("%Y年%m月%d日 %H:%M:%S")


@tool
@safe_tool(max_len=500)
def calculator(expression: str) -> str:
    """
    计算数学表达式，当用户需要进行数学运算时使用。
    支持的运算：+、-、*、/、**（幂）、%（取余）等。
    示例输入："2 + 3 * 4"、"100 / 7"、"2 ** 10"
    """
    # 仅允许安全的数学运算字符
    allowed = set("0123456789+-*/%(). ")
    if not all(ch in allowed for ch in expression):
        return "错误：表达式包含不允许的字符，仅支持数字和 +-*/%() 运算符。"
    result = eval(expression, {"__builtins__": {}})
    return str(result)


@tool
@safe_tool(error_map={Exception: "知识库检索出错"})
def search_knowledge_base(query: str) -> str:
    """
    在已上传的知识库文档中检索相关信息。
    当用户的问题涉及已上传的 Word 文档内容、公司内部资料、
    或者需要查找文档中的具体信息时使用此工具。
    参数 query 应为具体的检索问题。
    """
    from rag import search_text
    # Query Rewrite：优先使用 chat_stream 缓存的改写结果，避免重复调用 LLM
    global _rewrite_cache
    rewritten = _rewrite_cache.pop(query, None)
    if rewritten is None:
        # 兜底：非 SSE 流式调用（如 chat()）时自行改写
        rewritten = rewrite_query(query)
    return search_text(rewritten)


# 说明：web_search / url_reader 已迁移至 MCP Server（按能力域拆分）：
#   - mcp_servers/search.py  → web_search（联网搜索）
#   - mcp_servers/browser.py → url_reader（网页阅读）
# 由下方 MCP_SERVERS 配置 + load_mcp_tools() 在 build_agent() 时动态装配。


@tool
@safe_tool(max_len=0)  # 内部已做截断，装饰器不再二次截断
def python_executor(code: str) -> str:
    """
    执行 Python 代码并返回输出结果。
    当用户需要数据分析、文本处理、生成图表描述、复杂逻辑运算，
    或 calculator 无法满足的编程需求时使用此工具。
    参数 code 应为合法的 Python 代码字符串。
    注意：代码中可使用 print() 输出结果，返回值将作为 stdout 返回。
    """
    # 安全黑名单：禁止危险操作
    forbidden = [
        "import os", "import subprocess", "import shutil",
        "import socket", "import http", "import urllib",
        "import requests", "import ctypes",
        "open(", "exec(", "eval(", "compile(",
        "__import__", "globals(", "locals(",
        "os.system", "os.remove", "os.rmdir",
        "subprocess.", "shutil.",
    ]
    code_lower = code.lower()
    for keyword in forbidden:
        if keyword.lower() in code_lower:
            return f"安全限制：代码中包含不允许的操作「{keyword}」，请移除后重试。"

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        # 在受限的全局命名空间中执行
        # 提供安全的 __import__：只允许白名单模块，防止加载危险模块
        _allowed_modules = {
            "math", "json", "re", "collections", "itertools",
            "functools", "statistics", "datetime", "random",
            "string", "textwrap", "decimal", "fractions",
            "copy", "types", "dataclasses", "typing",
            "sys", "os", "pathlib", "platform", "struct",
            "hashlib", "base64", "urllib", "operator", "time",
        }

        def _safe_import(name, *args, **kwargs):
            top_level = name.split(".")[0]
            if top_level not in _allowed_modules:
                raise ImportError(
                    f"安全限制：不允许导入模块「{name}」，仅允许：{', '.join(sorted(_allowed_modules))}"
                )
            return __import__(name, *args, **kwargs)

        safe_builtins = {
            k: v for k, v in (__builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)).items()
            if k not in ("exec", "eval", "compile", "__import__",
                         "open", "input", "globals", "locals")
        }
        safe_builtins["__import__"] = _safe_import

        safe_globals = {
            "__builtins__": safe_builtins,
            "__name__": "__main__",
        }
        # 预注入常用标准库（避免代码中 import 时再走 __import__ 查找）
        import math, json, re, collections, itertools, functools, statistics, sys, os, platform, time
        safe_globals.update({
            "math": math, "json": json, "re": re,
            "collections": collections, "itertools": itertools,
            "functools": functools, "statistics": statistics,
            "sys": sys, "os": os, "platform": platform, "time": time,
        })
        exec(code, safe_globals)

    output = stdout_buf.getvalue()
    err = stderr_buf.getvalue()

    result_parts = []
    if output:
        result_parts.append(output.rstrip())
    if err:
        result_parts.append(f"[stderr]\n{err.rstrip()}")
    if not result_parts:
        return "（代码执行成功，但无输出。请使用 print() 输出结果。）"

    result = "\n".join(result_parts)
    if len(result) > 3000:
        result = result[:3000] + "\n…（输出过长，已截断）"
    return result


# 本地工具列表（纯函数/依赖本地状态，无需跨进程，避免子进程开销）
LOCAL_TOOLS = [get_current_time, calculator, search_knowledge_base, python_executor]

# ──────────────────────────────────────────────
# MCP Server 配置（stdio 子进程，按能力域拆分：search / browser）
# ──────────────────────────────────────────────

_MCP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_servers")

# Windows stdio 两个必备项：
# 1. PYTHONUTF8=1：子进程默认 GBK 会导致中文结果过协议通道时乱码甚至崩协议
# 2. command 用 sys.executable：确保用当前 .venv 的 Python，避免 PATH 解析到未装 mcp 依赖的解释器
# 注：env 指定后会整体替换默认环境，必须传入完整环境副本
MCP_SERVERS = {
    "search": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [os.path.join(_MCP_DIR, "search.py")],
        "env": {**os.environ, "PYTHONUTF8": "1"},
    },
    "browser": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [os.path.join(_MCP_DIR, "browser.py")],
        "env": {**os.environ, "PYTHONUTF8": "1"},
    },
}

# 成功装配进 Agent 的 MCP 工具名（供 /api/health 与评估预检使用）
mcp_tools_loaded: list[str] = []

# ──────────────────────────────────────────────
# Agent 构建
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个友好、专业的 AI 助手。
你可以使用以下工具来帮助用户：
- get_current_time：获取当前日期和时间
- calculator：进行数学计算
- search_knowledge_base：在已上传的知识库文档中检索信息
- web_search：在互联网上搜索最新信息和公开内容
- url_reader：读取指定网页的正文内容
- python_executor：执行 Python 代码，用于数据分析、复杂运算、文本处理等

使用原则：
1. 如果用户的问题可能涉及已上传的文档内容，优先使用 search_knowledge_base 检索
2. 如果用户询问实时信息、最新新闻或知识库中没有的内容，使用 web_search 搜索
3. 如果用户提供了一个 URL 并要求阅读/总结网页内容，使用 url_reader
4. 如果需要数学运算，优先使用 calculator；复杂运算或数据分析用 python_executor
5. 当需要处理复杂逻辑、数据分析、文本处理时，使用 python_executor
6. 如果不需要工具，直接回答即可
7. 请用中文回答，回答要简洁清晰

防幻觉规则（重要）：
- 当 search_knowledge_base 返回"知识库为空"或"未找到相关内容"时，必须诚实告知用户"当前知识库中没有找到与您问题相关的信息"，严禁编造文档名称、内容或数据
- 当 web_search 返回"未找到相关搜索结果"时，应如实说明，不要编造搜索结果
- 当任何工具返回"访问超时"、"搜索出错"、"HTTP 错误"、"工具执行出错"等错误信息时，必须如实告知用户工具调用失败，严禁编造该工具本应返回的内容（如编造网页内容、新闻细节、汇率数据等）
- 回复中引用的数据、事实必须来自工具返回的实际内容，不得凭空捏造
- 如果工具返回的信息不足以回答用户问题，或工具调用失败无法获取信息，应明确说明并建议用户稍后重试或提供其他信息来源

评审修正规则：
- 如果收到以"[评审修正请求]"开头的消息，请认真根据反馈中的具体问题改进你之前的回复
- 修正时只调整有问题的部分，保持回复的整体结构和风格
- 修正后的回复要直接呈现给用户，不要提及“修正”“反馈”“评审”等字眼
- 不要重复用户最初的问题，直接给出修正后的完整回复
"""


# 模块级引用，供外部使用
llm: ChatAnthropic | None = None
checkpointer: AsyncSqliteSaver | None = None

# Checkpoint 数据库路径
CHECKPOINT_DB = os.path.join(os.path.dirname(__file__), "checkpoints.db")


async def load_mcp_tools() -> list:
    """从 MCP Server（stdio 子进程）装配工具。

    langchain-mcp-adapters 0.3+ 的 stdio 模式：每次工具调用临时拉起子进程，
    客户端不持有长连接，无需 AsyncExitStack 管理生命周期。
    任一 server 装配失败时整体降级为空列表并打印警告，保证服务仍可启动。
    """
    global mcp_tools_loaded
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        print("⚠️ 未安装 langchain-mcp-adapters，跳过 MCP 工具（pip install langchain-mcp-adapters）")
        mcp_tools_loaded = []
        return []

    try:
        client = MultiServerMCPClient(MCP_SERVERS)
        tools = await client.get_tools()
        mcp_tools_loaded = [t.name for t in tools]
        print(f"✅ MCP 工具装配成功：{mcp_tools_loaded}")
        return tools
    except Exception as e:
        mcp_tools_loaded = []
        print(f"⚠️ MCP 工具装配失败，Agent 降级为仅本地工具：{e}")
        return []


async def build_agent():
    """构建并返回 LangChain ReAct Agent，集成 AsyncSqliteSaver checkpointer。"""
    global llm, checkpointer

    llm = ChatAnthropic(
        model=os.getenv("ANTHROPIC_MODEL", "deepseek-v4-flash"),
        anthropic_api_url=os.getenv("ANTHROPIC_BASE_URL"),
        anthropic_api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
        temperature=0.7,
        timeout=120,          # 请求超时时间（秒）
        max_retries=2,        # 失败后重试次数
    )

    # 创建 AsyncSqliteSaver checkpointer（持久化会话历史）
    conn = await aiosqlite.connect(CHECKPOINT_DB)
    checkpointer = AsyncSqliteSaver(conn)

    # 工具装配：本地轻量工具 + MCP Server 工具（web_search / url_reader）
    tools = list(LOCAL_TOOLS) + await load_mcp_tools()

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
        checkpointer=checkpointer,
    )
    return agent


def _extract_text(content) -> str:
    """从 AI 消息的 content 中提取纯文本。
    content 可能是 str，也可能是列表（Anthropic 内容块格式）。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Anthropic 格式：[{"type": "text", "text": "..."}, ...]
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


async def chat_async(agent, user_input: str, thread_id: str = "default") -> tuple[str, list]:
    """
    与 Agent 进行一轮异步对话（chat 的 async 版本），包含评审循环。
    Worker 生成回复 → Reviewer 审查 → 不通过则 Worker 修正，最多 MAX_REVIEW_ROUNDS 轮。
    MCP 工具（web_search / url_reader）必须经由此异步入口调用。
    """
    from langchain_core.messages import HumanMessage, AIMessage

    config = {"configurable": {"thread_id": thread_id}}

    # 第一轮：正常工作
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_input)]}, config=config
    )

    messages = result["messages"]
    reply_text = _extract_text(messages[-1].content)

    # 收集工具证据
    evidence_parts = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                evidence_parts.append(f"工具调用: {tc['name']}({tc.get('args', {})})")
        if hasattr(msg, "name") and msg.name:  # ToolMessage
            content = _extract_text(msg.content)
            evidence_parts.append(f"工具结果 [{msg.name}]: {content[:500]}")
    evidence = "\n".join(evidence_parts)

    # 评审循环
    for _round in range(MAX_REVIEW_ROUNDS):
        review = await _review_draft(user_input, reply_text, evidence)
        if review["verdict"] == "pass":
            break

        # 评审不通过，将反馈注入对话让 Worker 修正
        messages.append(AIMessage(
            content=f"[内部评审反馈，请根据以下意见修正回复，不要暴露评审机制的存在]\n{review['feedback']}"
        ))
        result = await agent.ainvoke(
            {"messages": messages}, config=config
        )
        messages = result["messages"]
        reply_text = _extract_text(messages[-1].content)

        # 更新证据
        evidence_parts = []
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    evidence_parts.append(f"工具调用: {tc['name']}({tc.get('args', {})})")
            if hasattr(msg, "name") and msg.name:
                content = _extract_text(msg.content)
                evidence_parts.append(f"工具结果 [{msg.name}]: {content[:500]}")
        evidence = "\n".join(evidence_parts)

    return reply_text, messages


async def chat_stream(agent, user_input: str, thread_id: str = "default"):
    """
    流式对话，async generator，yield 统一 SSE 事件字典。
    包含评审循环：Worker 生成回复 → Reviewer 审查 → 不通过则修正。
    中间轮次仅输出 tool_call/tool_result 事件，最终轮输出 message_chunk 和评审事件。

    统一协议格式：
      {"type": "message_chunk",  "run_id": "xxx", "thread_id": "xxx", "step": "llm",    "data": {"text": "..."}}
      {"type": "query_rewrite",  "run_id": "xxx", "thread_id": "xxx", "step": "rag",    "data": {"original": "...", "rewritten": "..."}}
      {"type": "tool_call",      "run_id": "xxx", "thread_id": "xxx", "step": "tool",   "data": {"name": "...", "input": "..."}}
      {"type": "tool_result",    "run_id": "xxx", "thread_id": "xxx", "step": "tool",   "data": {"name": "...", "output": "..."}}
      {"type": "review_start",   "run_id": "xxx", "thread_id": "xxx", "step": "review", "data": {"round": 1}}
      {"type": "review_result",  "run_id": "xxx", "thread_id": "xxx", "step": "review", "data": {"round": 1, "verdict": "pass"/"revise", "feedback": "..."}}
      {"type": "done",           "run_id": "xxx", "thread_id": "xxx", "step": "llm",    "data": {"text": "完整回复"}}
      {"type": "error",          "run_id": "xxx", "thread_id": "xxx", "step": "server", "data": {"message": "..."}}
    """
    from langchain_core.messages import HumanMessage

    config = {"configurable": {"thread_id": thread_id}}

    run_id = uuid.uuid4().hex[:12]
    original_input = user_input  # 保留原始问题供评审使用

    def _event(event_type: str, step: str, data: dict) -> dict:
        return {
            "type": event_type,
            "run_id": run_id,
            "thread_id": thread_id,
            "step": step,
            "data": data,
        }

    for review_round in range(MAX_REVIEW_ROUNDS + 1):

        # ── Worker 阶段：调用 react agent 生成回复草稿 ──
        full_text = ""
        draft_chunks: list[dict] = []   # 缓存本轮 message_chunk 事件
        tool_events: list[str] = []     # 收集工具证据供评审
        worker_events: list[dict] = []  # 缓存本轮工具相关事件

        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            version="v2",
        ):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                text = _extract_text(chunk.content)
                if text:
                    full_text += text
                    chunk_event = _event("message_chunk", "llm", {"text": text})
                    draft_chunks.append(chunk_event)
                    worker_events.append(chunk_event)

            elif kind == "on_tool_start":
                tool_input = event.get("data", {}).get("input", {})
                if event["name"] == "search_knowledge_base":
                    original_q = tool_input.get("query", "") if isinstance(tool_input, dict) else str(tool_input)
                    rewritten_q = rewrite_query(original_q)
                    _rewrite_cache[original_q] = rewritten_q
                    qr_event = _event("query_rewrite", "rag", {
                        "original": original_q,
                        "rewritten": rewritten_q,
                    })
                    worker_events.append(qr_event)
                tc_event = _event("tool_call", "tool", {
                    "name": event["name"],
                    "input": str(tool_input) if tool_input else "",
                })
                worker_events.append(tc_event)
                tool_events.append(f"工具调用: {event['name']}({tool_input})")

            elif kind == "on_tool_end":
                tool_output = event.get("data", {}).get("output", "")
                output_text = _extract_text(tool_output) if tool_output else ""
                result_data: dict = {
                    "name": event["name"],
                    "output": output_text[:500] if len(output_text) > 500 else output_text,
                }
                if event["name"] == "search_knowledge_base":
                    import rag as _rag
                    if getattr(_rag, "_last_sources", None):
                        result_data["citations"] = _rag._last_sources
                        _rag._last_sources = []
                tr_event = _event("tool_result", "tool", result_data)
                worker_events.append(tr_event)
                tool_events.append(f"工具结果 [{event['name']}]: {output_text[:500]}")

        # ── 输出工具事件（所有轮次都输出，用户能看到执行过程） ──
        for ev in worker_events:
            if ev["type"] in ("tool_call", "tool_result", "query_rewrite"):
                yield ev

        # ── 评审阶段 ──
        evidence = "\n".join(tool_events) if tool_events else ""

        yield _event("review_start", "review", {"round": review_round + 1})

        review = await _review_draft(original_input, full_text, evidence)
        verdict = review["verdict"]
        feedback = review.get("feedback", "")

        yield _event("review_result", "review", {
            "round": review_round + 1,
            "verdict": verdict,
            "feedback": feedback,
        })

        if verdict == "pass" or review_round >= MAX_REVIEW_ROUNDS - 1:
            # 评审通过或达到最大轮次：输出最终回复的 message_chunk
            for chunk_ev in draft_chunks:
                yield chunk_ev
            yield _event("done", "llm", {"text": full_text})
            return

        # ── 评审不通过：将反馈作为新的用户消息注入，让 Worker 修正 ──
        user_input = f"[评审修正请求] 请根据以下反馈修正你的回复：{feedback}"

    # 安全兑底（理论上不会到达）
    yield _event("done", "llm", {"text": full_text})
