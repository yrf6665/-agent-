"""
离线模拟大模型服务器（应急 / 无 Key 时使用）
------------------------------------------------------------
用途：
  · 机房断网、Key 没申请下来时，照样可以演示 00~03 的完整流程；
  · 服务器窗口会打印每次收到的请求：消息条数、请求大小 ——
    可以直观看到"Agent 每走一步，发出去的上下文就变长一点"。

注意：它不是真的大模型，只会按固定剧本回复，仅适合演示推荐任务。

用法：
  1. 新开一个终端运行：python mock_server.py
  2. 把 .env 改成：LLM_API_KEY=mock / LLM_BASE_URL=http://127.0.0.1:8000/v1 / LLM_MODEL=mock-model
  3. 在另一个终端照常运行 00~03 的脚本
"""
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

REVIEW = """# grade_stats.py 代码审查（模拟模式生成）

1. average()：没有记录时 len(records) 为 0，会触发 ZeroDivisionError。
2. pass_rate()：条件写成了 > 60，60 分被算作不及格，应为 >=。
3. top_n()：sorted 默认升序，取到的是最低的 n 名，应加 reverse=True。
4. load_scores()：遇到"缺考"等非数字分数时 float() 会抛 ValueError。
5. grade_level()：尚未实现。
"""

FIX_OLD = 'r["score"] > PASS_LINE'
FIX_NEW = 'r["score"] >= PASS_LINE'


def tool_call(name, args):
    return {"id": "call_" + uuid.uuid4().hex[:8], "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def decide(req):
    """按剧本决定回复：返回 (content, tool_calls)。"""
    messages = req.get("messages", [])
    tools = {t["function"]["name"] for t in req.get("tools", [])}
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
    since = messages[last_user + 1:]                       # 本轮任务开始后的消息
    steps = sum(1 for m in since if m["role"] == "assistant" and m.get("tool_calls"))
    last_tool = next((m["content"] for m in reversed(since) if m["role"] == "tool"), "")

    if not tools:
        if "上一个" in messages[last_user]["content"]:
            return "（模拟模式）抱歉，我看不到你之前的对话，这是我们的第一条消息。", None
        return "（模拟模式）AI Agent 是能自主调用工具、循环完成任务的大模型程序。", None

    if "拒绝" in last_tool:
        return "（模拟模式）好的，你拒绝了这次操作，我先停下来。需要换个做法请告诉我。", None

    if "git_status" in tools:                           # Git 助手的离线只读演示
        if steps == 0:
            return "我先只读检查当前仓库状态。", [tool_call("git_status", {})]
        return ("（模拟模式）已检查仓库状态。本演示只调用 git_status，不会暂存、提交或推送。\n"
                + last_tool), None
    if "get_weather" in tools:
        if steps == 0:
            return None, [tool_call("get_weather", {"city": "北京"})]
        return f"（模拟模式）北京今天{last_tool}，很适合去操场跑步，注意热身。", None

    if "run_tests" in tools:                               # 03 的剧本
        script = [
            ("我先运行测试，看看现在有哪些失败。", tool_call("run_tests", {})),
            ("有多个测试失败，我先读一下源码。", tool_call("read_file", {"path": "grade_stats.py"})),
            ("pass_rate 用了 > 60，导致 60 分不算及格，我先修这一处。",
             tool_call("edit_file", {"path": "grade_stats.py", "old": FIX_OLD, "new": FIX_NEW})),
            ("修改完成，重新运行测试验证。", tool_call("run_tests", {})),
        ]
        if steps < len(script):
            content, call = script[steps]
            return content, [call]
        return ("（模拟模式）已修复 pass_rate 的边界条件（> 改为 >=），test_pass_rate_includes_60 已通过。"
                "其余失败（average 空列表、top_n 排序、load_scores 缺考、grade_level 未实现）可以继续让我处理。"), None

    script = [                                             # 02 的剧本
        tool_call("list_files", {"path": "."}),
        tool_call("read_file", {"path": "grade_stats.py"}),
        tool_call("write_file", {"path": "review.md", "content": REVIEW}),
    ]
    if steps < len(script):
        return ("我先看看工作区里有什么文件。" if steps == 0 else None), [script[steps]]
    return "（模拟模式）我阅读了 grade_stats.py，发现 4 个 bug 和 1 个未实现函数，分析已写入 review.md。", None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        req = json.loads(body)
        print(f"📨 收到请求：{len(req.get('messages', []))} 条消息，{len(body)} 字节，"
              f"{len(req.get('tools', []))} 个工具", flush=True)
        content, calls = decide(req)
        time.sleep(0.6)                                    # 假装在思考
        message = {"role": "assistant", "content": content}
        if calls:
            message["tool_calls"] = calls
        prompt_tokens = len(body) // 3
        data = {
            "id": "mock-" + uuid.uuid4().hex[:8], "object": "chat.completion",
            "created": int(time.time()), "model": req.get("model", "mock-model"),
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 50,
                      "total_tokens": prompt_tokens + 50},
        }
        out = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):                          # 关掉默认的访问日志，只看上面的打印
        pass


if __name__ == "__main__":
    print("模拟大模型已启动：http://127.0.0.1:8000/v1   （Ctrl+C 退出）")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
