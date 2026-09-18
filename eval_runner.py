"""
评估集自动运行脚本
读取 eval_dataset.jsonl，逐条调用 /api/chat SSE 接口，收集结果写入 eval_results.jsonl
"""
import json
import time
import argparse
import requests

API_URL = "http://localhost:8000/api/chat"
HEALTH_URL = "http://localhost:8000/api/health"
DATASET_PATH = "eval_dataset.jsonl"
RESULTS_PATH = "eval_results.jsonl"

# 评估依赖的 MCP 工具（缺失时相关用例的工具成功率/匹配率必失真）
REQUIRED_MCP_TOOLS = {"web_search", "url_reader"}

# 工具执行错误特征（启发式检测，与 mcp_servers/ 内工具实现的错误返回文案对应）
TOOL_ERROR_PATTERNS = [
    "工具执行出错",                      # safe_tool 兜底异常（mcp_servers/_common.py）
    "安全限制：",                        # python_executor 黑名单拒绝
    "错误：表达式包含不允许的字符",      # calculator 非法字符拒绝
    "搜索出错",                          # web_search 异常（mcp_servers/search.py）
    "知识库检索出错",                    # search_knowledge_base 异常
    "访问超时",                          # url_reader 超时（mcp_servers/browser.py）
    "HTTP 错误",                         # url_reader HTTP 错误（mcp_servers/browser.py）
]


def is_tool_output_error(output: str) -> bool:
    """启发式判断工具输出是否为错误/拒绝信息"""
    return any(p in output for p in TOOL_ERROR_PATTERNS)


def load_dataset(path: str, skip_rag: bool = False) -> list[dict]:
    """加载评估集"""
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if skip_rag and case.get("rag_required"):
                continue
            cases.append(case)
    return cases


def call_chat_api(message: str, thread_id: str, timeout: int = 180) -> dict:
    """
    调用 /api/chat SSE 接口，收集所有事件。
    返回: {
        "events": [...],
        "full_text": "完整回复",
        "tools_called": ["工具名列表"],
        "tool_results": [{"name": "...", "output": "..."}],
        "error": "错误信息或None",
        "latency_ms": 毫秒数,
    }
    """
    payload = {"message": message, "thread_id": thread_id}
    tools_called = []
    tool_results = []
    full_text = ""
    events = []
    error = None

    t0 = time.time()
    try:
        resp = requests.post(API_URL, json=payload, stream=True, timeout=timeout)
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]  # 去掉 "data: " 前缀
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            events.append(event)

            evt_type = event.get("type", "")
            if evt_type == "tool_call":
                tool_name = event["data"].get("name", "")
                if tool_name not in tools_called:
                    tools_called.append(tool_name)
            elif evt_type == "tool_result":
                tool_results.append({
                    "name": event["data"].get("name", ""),
                    "output": event["data"].get("output", ""),
                    "citations": event["data"].get("citations", []),
                })
            elif evt_type == "done":
                full_text = event["data"].get("text", "")
            elif evt_type == "error":
                error = event["data"].get("message", "")

    except requests.exceptions.Timeout:
        error = "请求超时"
    except requests.exceptions.ConnectionError:
        error = "无法连接到后端服务，请确认服务已启动"
    except Exception as e:
        error = f"请求异常：{e}"

    latency_ms = round((time.time() - t0) * 1000)

    return {
        "events": events,
        "full_text": full_text,
        "tools_called": tools_called,
        "tool_results": tool_results,
        "error": error,
        "latency_ms": latency_ms,
    }


def preflight_check() -> bool:
    """评估前预检：后端可达 + Agent 就绪 + MCP 工具（web_search/url_reader）已装配。

    评估集通过后端 HTTP 接口调用 Agent，MCP 生命周期由后端 lifespan 管理，
    本脚本无需自行拉起 MCP Server；但若后端装配了降级（MCP 工具缺失），
    相关用例的工具成功率/选择匹配率会失真，必须在此显式暴露。
    """
    try:
        resp = requests.get(HEALTH_URL, timeout=10)
        resp.raise_for_status()
        health = resp.json()
    except Exception as e:
        print(f"❌ 预检失败：无法获取后端健康状态（{e}）")
        print("   请先启动后端服务：python start_backend.py")
        return False

    checks = health.get("checks", {})
    if checks.get("agent") != "ok":
        print(f"❌ 预检失败：Agent 未就绪（{checks.get('agent')}）")
        return False

    mcp_loaded = set(checks.get("mcp_tools", {}).get("loaded", []))
    missing = REQUIRED_MCP_TOOLS - mcp_loaded
    if missing:
        print(f"⚠️ 预检警告：MCP 工具缺失 {sorted(missing)}，相关用例的工具指标将失真")
        print(f"   已装配工具：{sorted(mcp_loaded) or '无'}（检查 mcp_servers/ 目录与 langchain-mcp-adapters 依赖）")
    else:
        print(f"✅ 预检通过：后端就绪，MCP 工具已装配 {sorted(mcp_loaded)}")
    return True


def run_evaluation(dataset_path: str, results_path: str, skip_rag: bool = False):
    """运行评估集"""
    if not preflight_check():
        return
    cases = load_dataset(dataset_path, skip_rag=skip_rag)
    total = len(cases)
    # 每次运行生成唯一 run_id 后缀，避免 checkpoint 历史跨轮评估累积污染
    # （同一轮内共享相同 thread_id 的多轮对话用例仍保持上下文连续）
    run_id = time.strftime("%Y%m%d_%H%M%S")
    print(f"📋 加载了 {total} 条评估用例" + ("（已跳过 RAG 用例）" if skip_rag else ""))
    print(f"🌐 API 地址：{API_URL}")
    print(f"🆔 本次运行 run_id：{run_id}（thread_id 附加后缀，确保每轮评估对话历史隔离）")
    print("-" * 60)

    results = []
    for i, case in enumerate(cases, 1):
        case_id = case["id"]
        category = case["category"]
        query = case["query"]
        thread_id = f"{case['thread_id']}_{run_id}"

        print(f"[{i}/{total}] [{category}] #{case_id}: {query[:50]}...", end=" ", flush=True)

        result = call_chat_api(query, thread_id)

        # 工具执行状态标记（启发式）
        # - 普通用例：输出含错误特征 = 执行失败
        # - expected_rejection 用例（安全用例）：出现拒绝/错误特征 = 工具正确工作 = 执行成功
        expected_rejection = case.get("expected_rejection", False)
        for tr in result["tool_results"]:
            is_error = is_tool_output_error(tr.get("output", ""))
            tr["exec_ok"] = is_error if expected_rejection else not is_error

        # 记录结果
        record = {
            **case,
            "actual_tools_called": result["tools_called"],
            "actual_tool_results": result["tool_results"],
            "actual_full_text": result["full_text"],
            "actual_error": result["error"],
            "latency_ms": result["latency_ms"],
            "event_count": len(result["events"]),
        }
        results.append(record)

        # 打印状态
        if result["error"]:
            print(f"❌ 错误: {result['error'][:60]}")
        else:
            tools = ", ".join(result["tools_called"]) or "无工具"
            print(f"✅ 工具=[{tools}] 耗时={result['latency_ms']}ms")

    # 写入结果文件
    with open(results_path, "w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 统计摘要
    print("\n" + "=" * 60)
    print("📊 运行摘要")
    print(f"  总用例数：{total}")
    errors = sum(1 for r in results if r["actual_error"])
    print(f"  成功：{total - errors}  失败：{errors}")

    # 按类别统计工具调用正确率（简单检查）
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "tool_match": 0}
        categories[cat]["total"] += 1
        expected = set(r.get("expected_tools", []))
        actual = set(r.get("actual_tools_called", []))
        # 工具匹配：expected 是 actual 的子集即算正确
        if expected and expected.issubset(actual):
            categories[cat]["tool_match"] += 1
        elif not expected and not actual:
            categories[cat]["tool_match"] += 1

    # 工具调用执行成功率（启发式：工具执行未报错的比例，安全用例的正确拒绝计为成功）
    total_calls = 0
    ok_calls = 0
    for r in results:
        for tr in r.get("actual_tool_results", []):
            total_calls += 1
            if tr.get("exec_ok"):
                ok_calls += 1
    if total_calls:
        print(f"\n🔧 工具调用执行成功率（启发式）：{ok_calls}/{total_calls} ({ok_calls/total_calls*100:.0f}%)")

    print("\n📈 工具选择匹配率（按类别）：")
    for cat, stats in categories.items():
        rate = stats["tool_match"] / stats["total"] * 100 if stats["total"] else 0
        print(f"  {cat}: {stats['tool_match']}/{stats['total']} ({rate:.0f}%)")

    print(f"\n💾 结果已保存到：{results_path}")
    print("📝 接下来运行 eval_scoring.py 进行 LLM-as-Judge 评分")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行评估集")
    parser.add_argument("--dataset", default=DATASET_PATH, help="评估集文件路径")
    parser.add_argument("--output", default=RESULTS_PATH, help="结果输出文件路径")
    parser.add_argument("--skip-rag", action="store_true", help="跳过需要知识库的用例")
    args = parser.parse_args()

    run_evaluation(args.dataset, args.output, skip_rag=args.skip_rag)
