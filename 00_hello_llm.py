"""
第 0 步：调用一次大模型
------------------------------------------------------------
目标：
  1. 确认 Key、网络、模型名都没问题；
  2. 看清楚"一次对话请求"由什么组成；
  3. 发现一个重要事实：模型本身没有记忆。

运行：python 00_hello_llm.py
"""
from common import MODEL, client

# 一次请求 = 模型名 + 消息列表。每条消息都有"角色"：
#   system    给模型定身份、定规则（相当于上周学的"角色 + 约束"）
#   user      用户说的话
#   assistant 模型说过的话
question=input("\n请输入你想说的问题")
messages = [
    {"role": "system", "content":
        "你是一名耐心的编程助教，回答控制在 50 字以内。"
        "美食推荐必须且只能来自 food_recommend 工具的返回结果。"
        "如果工具返回'未收录'，就直接告诉用户该地区暂未收录，"
        "禁止用你自己的知识推荐任何食物。"},
    {"role": "user", "content": question},
]

resp = client.chat.completions.create(model=MODEL, messages=messages)
print("【模型回答】", resp.choices[0].message.content)
print("【本次消耗 token】", resp.usage.total_tokens)   # Agent 每多走一步，就要再付一次 token

# ---------------- 实验：模型有没有记忆？ ----------------
# 这次请求没有带上前面的对话，看看它还记不记得你问过什么
resp2 = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": "我上一个问题问的是什么？"}],
)
print("\n【不带历史再问一次】", resp2.choices[0].message.content)

# 结论：模型是"无状态"的。聊天软件和 Agent 之所以"记得"上下文，
# 是因为程序每次都把完整的 messages 列表重新发送了一遍。
# 思考：对话越来越长会发生什么？（提示：token 费用、上下文窗口上限）
