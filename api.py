"""
FastAPI 后端入口
提供 REST API + SSE 流式对话接口
"""
import os
import json
import asyncio
import tempfile
from contextlib import asynccontextmanager

# HuggingFace 国内镜像（必须在 import 之前设置）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import build_agent, chat_stream
import agent as agent_module
from rag import load_and_index, get_status, load_vectorstore

# ──────────────────────────────────────────────
# 异步初始化（FastAPI lifespan）
# ──────────────────────────────────────────────
agent = None

# 向量库就绪信号：后台加载完成后置位。请求侧据此等待，避免启动窗口内的
# 提问命中尚未加载的向量库、被误判为「知识库为空」。
_vectorstore_ready: asyncio.Event | None = None

# 等待向量库就绪的上限。超时也放行，由 RAG 工具如实报告检索不到内容。
VECTORSTORE_WAIT_TIMEOUT = 120.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent, _vectorstore_ready
    _vectorstore_ready = asyncio.Event()

    print("正在初始化 AI Agent ...")
    agent = await build_agent()

    async def _load_vectorstore_bg():
        """后台加载向量库，无论成败都置位就绪事件，避免请求被永久挂起。"""
        try:
            await asyncio.to_thread(load_vectorstore)
        except Exception as e:
            print(f"⚠️ 向量库加载失败：{type(e).__name__}: {e}")
        finally:
            _vectorstore_ready.set()

    # 向量库加载放入后台任务，不阻塞服务启动
    asyncio.create_task(_load_vectorstore_bg())
    print("Agent 初始化完成！（向量库后台加载中）")
    yield


def _vectorstore_loading() -> bool:
    """向量库是否仍在后台加载中。"""
    return _vectorstore_ready is not None and not _vectorstore_ready.is_set()


async def _wait_vectorstore(timeout: float = VECTORSTORE_WAIT_TIMEOUT) -> bool:
    """等向量库加载完成再继续，避免启动窗口内的请求读到空向量库。

    返回是否在超时前就绪；超时也放行，由 RAG 工具如实报告检索不到内容。
    """
    if not _vectorstore_loading():
        return True
    try:
        await asyncio.wait_for(_vectorstore_ready.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        print(f"⚠️ 等待向量库就绪超时（{timeout:.0f}s），本次请求按未就绪放行")
        return False


app = FastAPI(title="AI Agent API", lifespan=lifespan)

# 开发环境允许跨域（Vite 代理时可关闭，但直连时需要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None  # 会话 ID，前端传入以保持会话连续性


# ──────────────────────────────────────────────
# API 接口
# ──────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """健康检查：检测 Agent、LLM 连通性、向量库状态"""
    import time
    checks: dict = {}

    # 1. Agent 状态
    checks["agent"] = "ok" if agent is not None else "uninitialized"

    # 2. 向量库状态（「加载中」与「确实为空」是两回事，需区分）
    kb = get_status()
    if _vectorstore_loading():
        vs_status = "loading"
    elif kb.get("doc_count", 0) > 0:
        vs_status = "ok"
    else:
        vs_status = "empty"
    checks["vectorstore"] = {
        "status": vs_status,
        "doc_count": kb.get("doc_count", 0),
        "files": len(kb.get("files", [])),
    }

    # 2.5 MCP 工具（web_search / url_reader，stdio 子进程装配）
    mcp_loaded = getattr(agent_module, "mcp_tools_loaded", [])
    mcp_ok = {"web_search", "url_reader"}.issubset(set(mcp_loaded))
    checks["mcp_tools"] = {
        "status": "ok" if mcp_ok else "degraded",
        "loaded": mcp_loaded,
    }

    # 3. LLM 连通性探测（发一个极轻量请求）
    agent_llm = agent_module.llm
    if agent_llm is not None:
        try:
            t0 = time.time()
            resp = await agent_llm.ainvoke("ping")
            latency = round((time.time() - t0) * 1000)
            checks["llm"] = {
                "status": "ok",
                "model": agent_llm.model,
                "latency_ms": latency,
            }
        except Exception as e:
            checks["llm"] = {"status": "error", "detail": str(e)[:200]}
    else:
        checks["llm"] = {"status": "uninitialized"}

    overall = "ok" if all(
        (v if isinstance(v, str) else v.get("status", "")) == "ok"
        for v in checks.values()
    ) else "degraded"

    return {"status": overall, "checks": checks}


@app.get("/api/kb/status")
async def kb_status():
    """获取知识库状态"""
    return {"status": get_status()}


@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """
    上传 .docx 文件到知识库
    前端用 FormData 发送 files 字段
    """
    # 等向量库加载完成：否则首次上传会与后台加载并发写同一个向量库
    await _wait_vectorstore()

    results = []
    for upload in files:
        if not upload.filename.lower().endswith(".docx"):
            results.append(f"⚠️ 跳过非 Word 文件：{upload.filename}")
            continue

        # 将上传内容写入临时文件，供 rag 处理
        try:
            content = await upload.read()
            with tempfile.NamedTemporaryFile(
                suffix=".docx", delete=False
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            info = load_and_index(tmp_path, original_name=upload.filename)
            results.append(f"✅ {info['file']} — 导入 {info['chunks']} 个文档块")

            # 清理临时文件
            os.unlink(tmp_path)
        except Exception as e:
            results.append(f"❌ {upload.filename} 导入失败：{e}")

    return {
        "results": results,
        "status": get_status(),
    }


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """
    流式对话接口（SSE）
    返回 text/event-stream，逐步推送 AI 回复 token
    通过 SqliteSaver checkpointer 自动管理会话历史，前端只需传 thread_id。

    统一 SSE 事件格式：
      data: {"type": "message_chunk",  "run_id": "xxx", "thread_id": "xxx", "step": "llm",    "data": {"text": "..."}}
      data: {"type": "query_rewrite", "run_id": "xxx", "thread_id": "xxx", "step": "rag",    "data": {"original": "...", "rewritten": "..."}}
      data: {"type": "tool_call",     "run_id": "xxx", "thread_id": "xxx", "step": "tool",   "data": {"name": "...", "input": "..."}}
      data: {"type": "tool_result",   "run_id": "xxx", "thread_id": "xxx", "step": "tool",   "data": {"name": "...", "output": "...", "citations": [...]}}
      data: {"type": "review_start",  "run_id": "xxx", "thread_id": "xxx", "step": "review", "data": {"round": 1}}
      data: {"type": "review_result", "run_id": "xxx", "thread_id": "xxx", "step": "review", "data": {"round": 1, "verdict": "pass"/"revise", "feedback": "..."}}
      data: {"type": "done",          "run_id": "xxx", "thread_id": "xxx", "step": "llm",    "data": {"text": "完整回复"}}
      data: {"type": "error",         "run_id": "xxx", "thread_id": "xxx", "step": "server", "data": {"message": "..."}}
    """
    import uuid

    # 等向量库加载完成，避免启动窗口内的检索命中空向量库、
    # 让 Agent 如实回答「知识库为空」——那是错误信息而非真实检索结果
    await _wait_vectorstore()

    # 会话 ID：前端传入或自动生成
    thread_id = req.thread_id or uuid.uuid4().hex[:12]

    async def event_generator():
        try:
            async for event in chat_stream(agent, req.message, thread_id=thread_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_event = {
                "type": "error",
                "run_id": "server",
                "thread_id": thread_id,
                "step": "server",
                "data": {"message": f"调用出错：{e}"},
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx 不缓冲
        },
    )


# ──────────────────────────────────────────────
# 静态文件托管（生产环境：Vue 打包后的 dist）
# ──────────────────────────────────────────────
DIST_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="static")


# ──────────────────────────────────────────────
# 启动
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    # 同 start_backend.py：默认只监听本机，避免无鉴权接口暴露给同网段
    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
