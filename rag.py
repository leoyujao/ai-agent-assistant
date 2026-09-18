"""
RAG 知识库模块
- 加载 .docx 文档
- 按段落分块
- 使用本地 Embedding 模型向量化
- FAISS 本地向量存储与检索
"""

import os
import json

# 【必须在 import huggingface/sentence-transformers 之前设置】
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 优先使用本地缓存，避免每次启动都尝试联网验证
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from dotenv import load_dotenv
load_dotenv()  # 加载 .env 中的其他配置

from langchain_community.document_loaders import Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# ──────────────────────────────────────────────
# 全局状态
# ──────────────────────────────────────────────
STORE_DIR = os.path.join(os.path.dirname(__file__), "vectorstore")  # 向量库持久化目录
_FILES_META_PATH = os.path.join(STORE_DIR, "loaded_files.json")      # 文件列表持久化路径
_embedding = None      # 延迟加载 Embedding 模型
_vectorstore = None    # FAISS 向量库
_doc_count = 0         # 已导入文档块数量
_loaded_files = []     # 已加载的文件名列表
_loading = False       # 向量库是否正在后台加载


def _get_embedding():
    """懒加载 Embedding 模型（首次调用时下载并缓存，约 100MB）"""
    global _embedding
    if _embedding is None:
        print("正在加载 Embedding 模型 (BAAI/bge-small-zh-v1.5) ...")
        _embedding = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        print("Embedding 模型加载完成！")
    return _embedding


# ──────────────────────────────────────────────
# 文本分割器（中文优化）
# ──────────────────────────────────────────────
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=60,
    separators=["\n\n", "\n", "。", ".", "，", ",", " ", ""],
    length_function=len,
)


def load_and_index(file_path: str, original_name: str = None) -> dict:
    """
    加载 .docx 文件并加入 FAISS 向量库。
    original_name: 原始文件名（上传时传入，避免临时文件名）
    返回: {"chunks": 块数, "file": 文件名}
    """
    global _vectorstore, _doc_count, _loaded_files

    loader = Docx2txtLoader(file_path)
    docs = loader.load()

    # 按段落分块
    chunks = _splitter.split_documents(docs)

    # 过滤空文档块
    chunks = [c for c in chunks if c.page_content.strip()]

    # 统一来源标识：把原始文件名写进元数据。
    # Docx2txtLoader 默认将 source 设为传入路径，而上传流程传的是临时文件路径，
    # 若不覆盖，引用溯源会显示 tmpXXXX.docx 这类无意义的临时名。
    file_name = original_name or file_path.replace("\\", "/").split("/")[-1]
    for c in chunks:
        c.metadata["source"] = file_name

    embedding = _get_embedding()

    if _vectorstore is None:
        # 首次：创建新向量库
        print(f"正在创建 FAISS 向量库（{len(chunks)} 个文档块）...")
        _vectorstore = FAISS.from_documents(chunks, embedding)
        print("FAISS 向量库创建完成！")
    else:
        # 后续：追加文档
        print(f"正在追加 {len(chunks)} 个文档块到 FAISS 向量库...")
        _vectorstore.add_documents(chunks)
        print("追加完成！")

    # 持久化到磁盘
    _save_vectorstore()

    _doc_count += len(chunks)

    _loaded_files.append(file_name)

    return {"chunks": len(chunks), "file": file_name}


def _save_vectorstore():
    """将 FAISS 向量库持久化到磁盘。"""
    global _vectorstore
    if _vectorstore is None:
        return
    os.makedirs(STORE_DIR, exist_ok=True)
    _vectorstore.save_local(STORE_DIR)
    # 同时保存已加载文件列表
    with open(_FILES_META_PATH, "w", encoding="utf-8") as f:
        json.dump(_loaded_files, f, ensure_ascii=False)
    print(f"向量库已保存到：{STORE_DIR}")


def _scan_files_from_docstore() -> list[str]:
    """从 FAISS docstore 提取已索引的文件名（去重、保持顺序）。

    以实际入库内容为准，避免 loaded_files.json 与实际向量库不同步时漏报文件。
    """
    if _vectorstore is None:
        return []
    try:
        names, seen = [], set()
        for doc_id in _vectorstore.docstore._dict:
            src = _vectorstore.docstore._dict[doc_id].metadata.get("source", "")
            if not src:
                continue
            name = src.replace("\\", "/").split("/")[-1]
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names
    except Exception:
        return []


def load_vectorstore():
    """从磁盘加载已有的 FAISS 向量库（服务启动时调用）。"""
    global _vectorstore, _doc_count, _loaded_files, _loading
    _loading = True
    try:
        if os.path.exists(os.path.join(STORE_DIR, "index.faiss")):
            embedding = _get_embedding()
            _vectorstore = FAISS.load_local(STORE_DIR, embedding, allow_dangerous_deserialization=True)
            _doc_count = _vectorstore.index.ntotal
            # 恢复已加载文件列表：以 docstore 实际内容为准（loaded_files.json 可能滞后），
            # 扫描不到时再回退到持久化文件
            _loaded_files = _scan_files_from_docstore()
            if not _loaded_files and os.path.exists(_FILES_META_PATH):
                with open(_FILES_META_PATH, "r", encoding="utf-8") as f:
                    _loaded_files = json.load(f)
            print(f"从磁盘加载向量库：{STORE_DIR}（{_doc_count} 个向量，{len(_loaded_files)} 个文件）")
        else:
            print("未发现已有向量库，等待上传文档...")
    finally:
        _loading = False


def search(query: str, top_k: int = 3) -> tuple[str, list[dict]]:
    """
    在知识库中检索最相关的文本段落。
    返回 (text, sources) 元组：
      - text:    拼接后的检索结果字符串（供 LLM 阅读）
      - sources: 结构化引用列表 [{title, snippet}]（供前端引用溯源）
    若知识库为空则返回提示信息，sources 为空列表。
    """
    if _vectorstore is None:
        return "（知识库为空，请先上传文档。）", []

    results = _vectorstore.similarity_search(query, k=top_k)

    if not results:
        return "（未在知识库中找到相关内容。）", []

    output_parts = []
    sources = []
    for i, doc in enumerate(results, 1):
        raw_source = doc.metadata.get("source", "")
        # 提取纯文件名（去除路径前缀）
        title = raw_source.split("\\")[-1].split("/")[-1] if raw_source else "未知来源"
        content = doc.page_content.strip()
        output_parts.append(f"【来源 {i}】{title}\n{content}")
        sources.append({
            "title": title,
            "snippet": content[:150] + ("…" if len(content) > 150 else ""),
        })

    return "\n\n".join(output_parts), sources


def search_text(query: str, top_k: int = 3) -> str:
    """
    search() 的纯文本包装，供 Agent 工具直接返回。
    引用元数据通过 _last_sources 模块变量暂存，由 chat_stream 在 on_tool_end 时取出。
    """
    global _last_sources
    text, sources = search(query, top_k)
    _last_sources = sources
    return text


# 模块级暂存变量，search_text() 写入，chat_stream() 读取后清空
_last_sources: list[dict] = []


def get_status() -> dict:
    """返回知识库当前状态（结构化数据）。"""
    if _loading:
        return {"doc_count": 0, "files": [], "message": "知识库正在加载中，请稍候刷新..."}
    if _vectorstore is None:
        return {"doc_count": 0, "files": [], "message": "知识库为空，请上传 .docx 文档"}
    # 去重并保持顺序，返回全部文件列表
    seen = set()
    unique_files = []
    for f in _loaded_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    return {
        "doc_count": _doc_count,
        "files": unique_files,
        "message": f"已导入 {_doc_count} 个文档块，共 {len(unique_files)} 个文件",
    }
