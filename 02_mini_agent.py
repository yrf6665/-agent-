"""
第 2 步：最小 Agent —— 大模型 + 工具 + 循环
------------------------------------------------------------
Agent 的全部秘密就是下面这个循环：

    while 任务没完成:
        模型思考，决定下一步（回答 or 调用工具）
        如果调用工具 → 程序执行 → 把结果(观察)放回对话 → 继续循环
        如果直接回答 → 任务完成，退出

这就是 ReAct：Reason（思考）→ Act（行动）→ Observe（观察）。
Cursor、Trae、Claude Code 这些编程 Agent 的骨架也是这个循环，
区别只在于：工具更多、上下文管理更精细、安全措施更完善。

运行：python 02_mini_agent.py
推荐任务：阅读 grade_stats.py，找出其中的 bug，把分析写入 review.md
"""
import json
import os
import random

from common import MODEL, client, to_dict

# 安全措施①：Agent 只能在这个"工作区"文件夹里活动，碰不到你电脑上的其他文件
WORKSPACE = os.path.abspath(os.getenv("AGENT_WORKSPACE", "demo_project"))
MAX_STEPS = 10           # 安全措施②：最多走 10 步，防止模型陷入死循环、烧光 token
MAX_CHARS = 4000         # 安全措施③：读文件最多返回 4000 字，防止撑爆上下文窗口


def safe_path(path):
    """把相对路径转成工作区内的绝对路径；想跳出工作区（如 ../../）就报错。"""
    full = os.path.abspath(os.path.join(WORKSPACE, path))
    if os.path.commonpath([full, WORKSPACE]) != WORKSPACE:
        raise PermissionError(f"禁止访问工作区以外的路径：{path}")
    return full


# ======================== ① 工具：就是普通函数 ========================
def list_files(path="."):
    names = [n for n in sorted(os.listdir(safe_path(path))) if not n.startswith((".", "__"))]   # 隐藏 .git、__pycache__ 等
    return "\n".join(names) or "（空目录）"


def read_file(path):
    with open(safe_path(path), encoding="utf-8") as f:
        text = f.read()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n……（文件太长，只显示前 {MAX_CHARS} 字）"
    return text


def write_file(path, content):
    # 安全措施④：人在回路（Human-in-the-loop）——有副作用的操作必须先问人
    print(f"\n   ⚠ Agent 想写入文件 {path}（{len(content)} 字），内容预览：\n   {content[:200]!r}")
    if input("   允许吗？(y/n) ").strip().lower() != "y":
        return "用户拒绝了这次写入，请不要再尝试写这个文件。"
    with open(safe_path(path), "w", encoding="utf-8") as f:
        f.write(content)
    return f"已写入 {path}"

FOODS_BY_REGION = {
    "河南": ["烩面", "胡辣汤", "洛阳水席", "开封灌汤包"],
    "四川": ["火锅", "麻辣香锅", "担担面", "串串香"],
    "广东": ["肠粉", "煲仔饭", "烧鹅", "虾饺"],
    "东北": ["锅包肉", "铁锅炖", "酸菜白肉", "饺子"],
    "陕西": ["肉夹馍", "羊肉泡馍", "凉皮", "油泼面"],
    "湖南": ["臭豆腐", "剁椒鱼头", "长沙米粉", "口味虾"],
}
def food_recommend(region):
    """按地域随机推荐一道当地美食。region 填省份或地区名，如 河南、四川。"""
    foods = FOODS_BY_REGION.get(region)         # 查字典；没有这个键返回 None
    if not foods:
        known = "、".join(FOODS_BY_REGION)      # 把收录的地域拼成一句话
        return f"美食库里没有收录 {region}，目前有：{known}。换一个地区试试？"
    return f"今天推荐你吃{region}的：" + random.choice(foods) + "！"

TOOLS = {"list_files": list_files, "read_file": read_file, "write_file": write_file,"food_recommend": food_recommend}


# ======================== ② 工具说明书：写给模型看 ========================
def schema(name, description, properties, required=()):
    """生成一份 Function Calling 格式的工具说明，省得每个都手写一大段 JSON。"""
    return {"type": "function", "function": {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)},
    }}


STR = {"type": "string"}
SCHEMAS = [
    schema("list_files", "列出工作区某个目录下的文件和文件夹", {"path": STR}),
    schema("read_file", "读取工作区内一个文本文件的内容", {"path": STR}, ["path"]),
    schema("write_file", "把内容写入工作区内的文件（会覆盖原文件）", {"path": STR, "content": STR}, ["path", "content"]),
    schema(
        "food_recommend",
        "按地域随机推荐一道当地美食。当用户想吃某地风味、问当地特色、"
        "或提到自己家乡/所在地想知道吃什么时用；与吃无关的事不要用它。",
        {
            "region": {
                "type": "string",
                "description": "省份或地区名，如：河南、四川、广东、东北、陕西、湖南。"
                               "用户提到具体城市（如洛阳）就填它所属的省份",
            }
        },
    ),
]


# ======================== ③ 循环：Agent 的心脏 ========================
def run_agent(task):
    messages = [
        {"role": "system", "content": (
            "你是一个能操作本地文件的编程助手。工作原则：\n"
            "1. 先观察（列目录、读文件）再下结论，不要凭空猜测文件内容；\n"
            "2. 每次只做一小步，根据工具返回的结果决定下一步；\n"
            "3. 任务完成后，用中文简要总结你做了什么。"
            "4.美食推荐必须且只能来自 food_recommend 工具的返回结果。"
            "5.如果工具返回'未收录'，就直接告诉用户该地区暂未收录，"
            "6.禁止用你自己的知识推荐任何食物。")},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        # 思考：把完整对话历史 + 工具说明书发给模型
        msg = client.chat.completions.create(model=MODEL, messages=messages, tools=SCHEMAS).choices[0].message
        messages.append(to_dict(msg))

        # 模型不再调用工具 → 说明它认为任务完成了
        if not msg.tool_calls:
            print(f"\n✅ 完成（共 {step} 轮）：\n{msg.content}")
            return

        if msg.content:                            # 有些模型会在调用工具前说出自己的想法
            print(f"\n💭 思考：{msg.content}")

        # 行动 + 观察：逐个执行模型要求的工具调用
        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments)
                print(f"🔧 第 {step} 轮 调用 {name}({', '.join(f'{k}={str(v)[:40]!r}' for k, v in args.items())})")
                result = TOOLS[name](**args)
            except Exception as e:
                # 关键设计：出错不让程序崩溃，而是把错误当作"观察"告诉模型，让它自己调整
                result = f"工具执行出错：{type(e).__name__}: {e}"
            print(f"   👀 结果：{str(result)[:120]!r}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": str(result)})

    print(f"\n⛔ 已达到最大步数 {MAX_STEPS}，强制停止。")


if __name__ == "__main__":
    print(f"工作区：{WORKSPACE}\n模型：{MODEL}")
    run_agent(input("请输入任务：").strip() or "阅读 grade_stats.py，找出其中的 bug，把分析写入 review.md")
