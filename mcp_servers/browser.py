"""
Browser MCP Server —— 网页阅读能力域

工具清单：
- url_reader：抓取指定网页并提取正文文本

运行方式（stdio 传输，由 Agent 进程作为子进程拉起）：
    python mcp_servers/browser.py

Server 侧规范（Windows stdio）：
- 严禁 print()：stdout 是 JSON-RPC 协议通道，任何调试输出都会污染协议
- 日志一律走 logging（本文件已配置输出到 stderr）
"""
import logging
import sys

from mcp.server.fastmcp import FastMCP

# 兼容两种启动方式：直接运行（python mcp_servers/browser.py）
# 与模块方式（python -m mcp_servers.browser）
try:
    from ._common import ERR_FETCH_TIMEOUT, ERR_HTTP, safe_tool
except ImportError:
    from _common import ERR_FETCH_TIMEOUT, ERR_HTTP, safe_tool

# 日志输出到 stderr（stdout 为协议通道，严禁占用）
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("browser-server")

mcp = FastMCP("browser")


@mcp.tool()
@safe_tool(max_len=0)  # 内部已按 4000 字符截断，装饰器不再二次截断
def url_reader(url: str) -> str:
    """
    读取指定网页的正文内容。
    当用户提供一个 URL 并要求阅读、总结、分析网页内容时使用此工具。
    参数 url 应为完整的网页地址（以 http:// 或 https:// 开头）。
    """
    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=25)
        resp.encoding = resp.apparent_encoding
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return f"{ERR_FETCH_TIMEOUT}，网页响应时间过长。"
    except requests.exceptions.HTTPError as e:
        return f"{ERR_HTTP}：{e}"

    soup = BeautifulSoup(resp.text, "html.parser")

    # 移除无关标签
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # 提取正文文本
    text = soup.get_text(separator="\n", strip=True)

    # 去除连续空行
    lines = [line for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    # 截断过长内容（最多返回 4000 字符）
    if len(text) > 4000:
        text = text[:4000] + "\n\n…（内容过长，已截断）"

    return text if text else "（网页内容为空）"


if __name__ == "__main__":
    # 日志用英文：stderr 可能被 GBK 终端解码，中文会出现乱码
    logger.info("browser MCP server started (stdio)")
    mcp.run()
