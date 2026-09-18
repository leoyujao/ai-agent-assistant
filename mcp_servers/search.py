"""
Search MCP Server —— 联网搜索能力域

工具清单：
- web_search：基于 ddgs 的联网搜索

运行方式（stdio 传输，由 Agent 进程作为子进程拉起）：
    python mcp_servers/search.py

Server 侧规范（Windows stdio）：
- 严禁 print()：stdout 是 JSON-RPC 协议通道，任何调试输出都会污染协议
- 日志一律走 logging（本文件已配置输出到 stderr）
"""
import logging
import sys

from mcp.server.fastmcp import FastMCP

# 兼容两种启动方式：直接运行（python mcp_servers/search.py）
# 与模块方式（python -m mcp_servers.search）
try:
    from ._common import safe_tool
except ImportError:
    from _common import safe_tool

# 日志输出到 stderr（stdout 为协议通道，严禁占用）
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("search-server")

mcp = FastMCP("search")


@mcp.tool()
@safe_tool(error_map={Exception: "搜索出错"})
def web_search(query: str) -> str:
    """
    在互联网上搜索信息。
    当用户询问最新新闻、实时信息、网络上的公开内容，
    或知识库中没有答案的问题时使用此工具。
    参数 query 应为搜索关键词或问题。
    """
    from ddgs import DDGS
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "未找到相关搜索结果。"
    parts = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        parts.append(f"【结果 {i}】{title}\n{body}\n链接：{href}")
    return "\n\n".join(parts)


if __name__ == "__main__":
    # 日志用英文：stderr 可能被 GBK 终端解码，中文会出现乱码
    logger.info("search MCP server started (stdio)")
    mcp.run()
