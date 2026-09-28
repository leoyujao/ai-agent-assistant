"""
MCP Server 公共基础设施

safe_tool 装饰器与工具错误文案的唯一来源，供各 MCP Server 与 agent.py 共用。

说明：MCP Server 以独立子进程运行，禁止 import agent.py（会触发 LLM 客户端、
向量库等模块级初始化）；反过来 agent.py 引用本模块是安全的（本模块只依赖
标准库），所以实现放在这里、由 agent.py 反向引用，避免同一份逻辑维护两份。

错误文案提成常量的原因：eval_runner.py 靠字符串匹配这些文案来判断工具是否
执行失败，散落成字面量时改一个字就会让评测指标静默失真。
"""
import functools

# ── 工具错误文案（改动会同时影响前端展示与 eval_runner 的失败判定）──
ERR_TOOL_FAILED = "工具执行出错"   # safe_tool 兜底前缀
ERR_SEARCH_FAILED = "搜索出错"     # web_search 全部异常统一文案
ERR_FETCH_TIMEOUT = "访问超时"     # url_reader 请求超时
ERR_HTTP = "HTTP 错误"             # url_reader 非 2xx
TRUNCATED_SUFFIX = "…（输出过长，已截断）"


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
                    result = result[:max_len] + "\n" + TRUNCATED_SUFFIX
                return result
            except Exception as e:
                if error_map:
                    for exc_type, prefix in error_map.items():
                        if isinstance(e, exc_type):
                            return f"{prefix}：{e}"
                return f"{ERR_TOOL_FAILED}：{type(e).__name__}: {e}"
        return wrapper
    return decorator
