"""
MCP Server 公共基础设施

safe_tool 装饰器：与 agent.py 同款逻辑的独立实现，供各 MCP Server 共用。
说明：MCP Server 以独立子进程运行，禁止 import agent.py（会触发 LLM 客户端、
向量库等模块级初始化），因此此处是独立拷贝而非共享引用——修改错误文案时
需同步 agent.py / eval_runner.py 的 TOOL_ERROR_PATTERNS 检测特征。
"""
import functools


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
