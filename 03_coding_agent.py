"""
第 3 步：一个"像样"的编程 Agent
------------------------------------------------------------
在 02 的基础上增加真实编程 Agent 都有的四个能力：

  ① 读取项目规则文件 AGENTS.md，放进 system 提示词
     —— Cursor 的 .cursorrules、Claude Code 的 CLAUDE.md 都是这个原理；
  ② edit_file：只替换一小段文字，而不是整个文件重写
     —— 省 token，也不容易把别处的代码改坏；
  ③ run_tests：运行测试，让 Agent 自己验证改得对不对
     —— 有了"反馈信号"，Agent 才能自我纠错；
  ④ 多轮会话 + 日志：任务完成后可以继续追问，每一步都记录到 agent_log.txt。

运行：python 03_coding_agent.py
推荐任务：运行测试，找出失败原因并修复 grade_stats.py，直到测试全部通过
"""
import json
import os
import subprocess
import sys
import time

from common import MODEL, client, to_dict

WORKSPACE = os.path.abspath(os.getenv("AGENT_WORKSPACE", "demo_project"))
MAX_STEPS = 20
MAX_CHARS = 6000
LOG_FILE = "agent_log.txt"


def safe_path(path):
    full = os.path.abspath(os.path.join(WORKSPACE, path))
    if os.path.commonpath([full, WORKSPACE]) != WORKSPACE:
        raise PermissionError(f"禁止访问工作区以外的路径：{path}")
    return full


def clip(text, keep_tail=False):
    """统一截断工具输出，保护上下文窗口。测试结果的总结在末尾，所以可以选择保留尾部。"""
    if len(text) <= MAX_CHARS:
        return text
    if keep_tail:
        return "……（前面的输出过长已截断）\n" + text[-MAX_CHARS:]
    return text[:MAX_CHARS] + "\n……（输出过长已截断）"


def confirm(question):
    return input(f"   ⚠ {question} 允许吗？(y/n) ").strip().lower() == "y"


# ============================ 工具 ============================
def list_files(path="."):
    names = [n for n in sorted(os.listdir(safe_path(path))) if not n.startswith((".", "__"))]
    return "\n".join(names) or "（空目录）"


def read_file(path):
    with open(safe_path(path), encoding="utf-8") as f:
        # 带行号返回，方便模型定位代码（真实编程 Agent 也是这么做的）
        return clip("".join(f"{i:4d}| {line}" for i, line in enumerate(f, 1)))


def edit_file(path, old, new):
    """把文件中唯一出现的一段 old 文本替换成 new。"""
    full = safe_path(path)
    with open(full, encoding="utf-8") as f:
        text = f.read()
    count = text.count(old)
    if count != 1:   # 找不到或不唯一都拒绝，逼模型给出更精确的片段
        return f"替换失败：old 在文件中出现了 {count} 次，必须恰好 1 次。请先 read_file 确认原文。"
    print(f"   --- 原来 ---\n   {old!r}\n   +++ 改成 +++\n   {new!r}")
    if not confirm(f"修改 {path}"):
        return "用户拒绝了这次修改。请说明你的理由，或换一种改法。"
    with open(full, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))
    return f"已修改 {path}"


def write_file(path, content):
    if not confirm(f"写入/覆盖文件 {path}（{len(content)} 字）"):
        return "用户拒绝了这次写入。"
    with open(safe_path(path), "w", encoding="utf-8") as f:
        f.write(content)
    return f"已写入 {path}"


def run_tests():
    """在工作区运行 pytest。命令是写死的——绝不让模型执行任意命令。"""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "--tb=short", "-p", "no:cacheprovider"],
                           cwd=WORKSPACE, capture_output=True, timeout=60, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})   # 让子进程用 UTF-8 输出中文
    except subprocess.TimeoutExpired:
        return "测试运行超过 60 秒，被强制终止。"
    return clip(r.stdout + r.stderr, keep_tail=True)


TOOLS = {"list_files": list_files, "read_file": read_file, "edit_file": edit_file,
         "write_file": write_file, "run_tests": run_tests}


def schema(name, description, properties=None, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": list(required)}}}


STR = {"type": "string"}
SCHEMAS = [
    schema("list_files", "列出工作区某个目录下的文件", {"path": STR}),
    schema("read_file", "读取文件内容（带行号）", {"path": STR}, ["path"]),
    schema("edit_file", "精确修改文件：把文件中唯一的一段 old 文本替换为 new。修改已有代码时优先用它。",
           {"path": STR, "old": {"type": "string", "description": "要被替换的原文，必须与文件内容完全一致"},
            "new": {"type": "string", "description": "替换后的新文本"}}, ["path", "old", "new"]),
    schema("write_file", "新建文件或整体覆盖文件", {"path": STR, "content": STR}, ["path", "content"]),
    schema("run_tests", "在工作区运行全部 pytest 测试，返回测试结果"),
]


# ============================ 提示词 ============================
def build_system_prompt():
    prompt = (
        "你是一名严谨的 Python 编程助手，可以通过工具读写工作区内的文件、运行测试。\n"
        "工作流程：先观察 → 说明计划 → 小步修改 → 运行测试验证 → 总结。\n"
        "规则：不确定的地方先读代码，不要编造；每次修改后都要运行测试；"
        "完成后用中文说明改了哪里、为什么这么改。")
    rules = os.path.join(WORKSPACE, "AGENTS.md")
    if os.path.exists(rules):   # ① 把项目规则文件拼进 system 提示词
        with open(rules, encoding="utf-8") as f:
            prompt += "\n\n# 本项目的规则（来自 AGENTS.md，必须遵守）\n" + f.read()
    return prompt


def log(text):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%H:%M:%S] ") + text + "\n")


# ============================ Agent 循环 ============================
def run_turn(messages):
    """执行一轮用户任务：循环调用模型和工具，直到模型给出最终回答。"""
    for step in range(1, MAX_STEPS + 1):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=SCHEMAS)
        msg = resp.choices[0].message
        messages.append(to_dict(msg))
        tokens = resp.usage.total_tokens if resp.usage else "?"

        if msg.content:
            print(f"\n💭 [{step}] {msg.content}")
            log(f"模型: {msg.content}")
        if not msg.tool_calls:
            print(f"   （本次请求共 {tokens} token —— 注意它随对话变长而增长）")
            return

        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                print(f"🔧 [{step}] {name}({', '.join(f'{k}={str(v)[:30]!r}' for k, v in args.items())})")
                result = TOOLS[name](**args)
            except Exception as e:
                result = f"工具执行出错：{type(e).__name__}: {e}"
            short = str(result).strip().splitlines()[-1] if str(result).strip() else ""
            print(f"   👀 {short[:100]}")
            log(f"工具 {name} {call.function.arguments} -> {str(result)[:300]!r}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": str(result)})
    print(f"\n⛔ 已达到最大步数 {MAX_STEPS}，强制停止。")


if __name__ == "__main__":
    print(f"工作区：{WORKSPACE}  模型：{MODEL}  （输入 exit 退出）")
    messages = [{"role": "system", "content": build_system_prompt()}]
    while True:
        task = input("\n🧑 你：").strip()
        if task.lower() in ("exit", "quit", "q"):
            break
        if task:
            messages.append({"role": "user", "content": task})   # ④ 历史一直保留，所以能连续追问
            log(f"用户: {task}")
            run_turn(messages)
