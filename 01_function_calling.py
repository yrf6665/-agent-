"""
第 1 步：Function Calling（工具调用）
------------------------------------------------------------
核心认知：模型不会、也不能自己执行任何函数。
         它只会"说出"想调用哪个工具、传什么参数；
         真正执行的是你写的程序，执行完再把结果告诉模型。

流程：①发问题 + 工具说明书 → ②模型返回 tool_calls → ③程序执行函数
     → ④把结果发回模型 → ⑤模型组织最终回答

运行：python 01_function_calling.py
"""
import json

from common import MODEL, client, to_dict


# ---------- 工具本体：一个普通的 Python 函数 ----------
def get_weather(city):
    """假的天气接口。真实项目里，这里会去请求天气网站的 API。"""
    fake_data = {"北京": "晴，12℃，空气良", "上海": "小雨，16℃", "广州": "多云，24℃"}
    return fake_data.get(city, "暂无该城市数据")


# ---------- 工具说明书（JSON Schema）：写给模型看的 ----------
# 模型完全靠 name 和 description 判断"什么时候该用、怎么用"这个工具，
# 所以描述写得好不好，直接决定 Agent 聪不聪明 —— 这本质上也是提示词。
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询某个城市今天的天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名，例如：北京"}},
            "required": ["city"],
        },
    },
}]

messages = [{"role": "user", "content": "北京今天天气怎么样？适合去操场跑步吗？"}]

# ---------- 第一次请求：把问题和工具说明书一起发出去 ----------
msg = client.chat.completions.create(model=MODEL, messages=messages, tools=tools).choices[0].message
print("① 模型回复的文字 content   ：", msg.content)
print("② 模型请求调用的 tool_calls：")
for call in msg.tool_calls or []:
    print("     工具名:", call.function.name, "  参数(JSON字符串):", call.function.arguments)

if not msg.tool_calls:
    raise SystemExit("模型这次没有调用工具。换个问法再试试，或检查所用模型是否支持 Function Calling。")

# ---------- 由"我们的程序"执行工具 ----------
messages.append(to_dict(msg))                      # 先把模型这条"我要调用工具"的消息放进历史
for call in msg.tool_calls:
    args = json.loads(call.function.arguments)     # 参数是字符串，要先解析成字典
    result = get_weather(**args)
    print("③ 程序执行 get_weather，结果：", result)
    messages.append({                              # 再把结果以 tool 角色放进历史
        "role": "tool",
        "tool_call_id": call.id,                   # 用 id 对应"这是哪一次调用的结果"
        "content": result,
    })

# ---------- 第二次请求：带着工具结果，让模型给出最终回答 ----------
final = client.chat.completions.create(model=MODEL, messages=messages, tools=tools).choices[0].message
print("④ 模型的最终回答：", final.content)

# 思考：如果一个任务需要连续调用好几次工具（先查文件列表、再读文件、再写报告），
#      代码该怎么改？—— 把"请求 → 执行工具 → 再请求"放进一个循环，就是 Agent。见 02。
