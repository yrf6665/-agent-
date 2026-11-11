# 第 3 周 · 从提示词到 Agent：AI 辅助编码入门（学生教程）

> 本周目标：**看懂 Agent 的原理 → 亲手写一个最小 Agent → 用编程 Agent 规范地完成一个小功能。**
> 本周交付：① 一个 AI 辅助完成的小功能模块（`grade_level` + 修好全部 bug，测试全绿）
> 　　　　　② 个人提示词模板库（本周至少新增 3 条，参考 `提示词模板库_示例.md`）

---

## 目录结构

```
课堂代码/
├── README.md               ← 你正在看的教程
├── requirements.txt        ← 依赖
├── .env.example            ← 配置模板（复制为 .env 后填 Key）
├── common.py               ← 公共配置：创建 client
├── 00_hello_llm.py         ← 第0步：调用一次大模型，发现"模型没有记忆"
├── 01_function_calling.py  ← 第1步：工具调用——模型只"说"，程序来"做"
├── 02_mini_agent.py        ← 第2步：最小 Agent = 大模型 + 工具 + 循环
├── 03_coding_agent.py      ← 第3步：带规则文件、精确编辑、跑测试的编程 Agent
├── mock_server.py          ← 应急：断网/没 Key 时的模拟大模型
├── 提示词模板库_示例.md     ← 本周模板库范例
└── demo_project/           ← 演示项目（藏了 4 个 bug + 1 个没写完的函数）
    ├── AGENTS.md           ← 写给 Agent 的项目说明书
    ├── grade_stats.py      ← 成绩统计模块（要修的就是它）
    ├── report.py           ← 成绩报告脚本（第一次运行会报错）
    ├── students.csv        ← 示例数据
    └── test_grade_stats.py ← 测试 = 写成代码的验收标准
```

---

## 第 1 步：准备环境（5 分钟）

```bash
# 1. 进入课堂代码目录
cd 课堂代码

# 2.（推荐）建一个虚拟环境，避免和别的项目冲突
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 初始化 Git（后面每完成一步就提交一次，改坏了可以回退）
git init
git add .
git commit -m "chore: 初始化第3周课堂代码"
```

## 第 2 步：配置大模型 Key

1. 把 `.env.example` **复制**一份，改名为 `.env`；
2. 把 `LLM_API_KEY=` 后面换成你自己的 Key（DeepSeek / 通义千问 / 智谱 / Kimi 等 OpenAI 兼容接口都可以）；
3. **`.env` 已经写进 `.gitignore`，永远不要把 Key 提交到 Git、发到群里或截图外传。**

> 没有 Key 或者机房断网？新开一个终端运行 `python mock_server.py`，再把 `.env` 改成文件末尾注释里的三行"模拟模式"配置即可。模拟模式只会按固定剧本回复，用来理解流程足够了。

---

## 第 3 步：00 —— 调用一次大模型

```bash
python 00_hello_llm.py
```

**要看懂的点**
- 一次请求 = `model` + `messages`；消息有 `system / user / assistant` 三种角色（上周学的"角色 + 约束"就写在 system 里）。
- 第二次提问没带历史，模型就"忘了"——**模型本身是无状态的**，所谓"记忆"是程序每次把整个对话重新发一遍。
- 每次调用都消耗 token：Agent 每多走一步，就要再付一次钱。

## 第 4 步：01 —— Function Calling

```bash
python 01_function_calling.py
```

**要看懂的点**
- 第一次请求后，模型返回的不是答案，而是 `tool_calls`：「我想调用 get_weather，参数是 {"city": "北京"}」。
- **执行函数的是我们的程序，不是模型。** 结果以 `role: "tool"` 放回对话，再请求一次，模型才给出最终回答。
- 模型靠 `description` 决定用不用、怎么用工具——**工具描述就是提示词**。

## 第 5 步：02 —— 最小 Agent

```bash
python 02_mini_agent.py
# 任务直接回车，使用默认任务：阅读 grade_stats.py，找出 bug，把分析写入 review.md
```

观察终端里每一轮的 💭 思考 → 🔧 调用 → 👀 结果。这就是 **ReAct 循环**。

**代码里的四道安全阀**（面试和做项目都会被问到）

| 安全阀 | 代码位置 | 防的是什么 |
|---|---|---|
| 工作区沙箱 `safe_path` | 只能访问 `demo_project/` | Agent 读写你电脑上的其他文件 |
| 最大步数 `MAX_STEPS` | `for step in range(...)` | 死循环、烧光 token |
| 输出截断 `MAX_CHARS` | `read_file` | 大文件撑爆上下文窗口 |
| 人在回路 `input("允许吗？")` | `write_file` | 未经同意就改文件 |

### ✍ 实操 3：给 Agent 加一个工具（选一个做）

加工具只需要三处改动：①写函数 ②在 `TOOLS` 字典里登记 ③在 `SCHEMAS` 里写说明书。

| 方向 | 工具 | 提示 |
|---|---|---|
| 计算机 | `run_python(path)` 运行脚本 | 有副作用，**必须先问人**；用 `subprocess.run(..., timeout=30)` |
| 大数据 | `csv_summary(path)` 数据概览 | 统计行数、每列数值范围、均值、非数值个数 |
| 人工智能 | `search_text(keyword)` 全文搜索 | 返回 `文件:行号: 内容`，让 Agent 不必逐个读文件 |
| 挑战 | `review_code(path)` 二次审查 | 工具内部再调用一次大模型当"审查员"——最朴素的多 Agent |

加完后给 Agent 一个**必须用到新工具**的任务，看它会不会主动调用。如果它不用，先改 `description`。

---

## 第 6 步：03 —— 编程 Agent

```bash
python 03_coding_agent.py
# 你：运行测试，找出失败原因，一次修一个问题，直到测试全部通过
```

比 02 多了什么：
1. 启动时读取 `demo_project/AGENTS.md`，拼进 system 提示词（Cursor 的 `.cursorrules`、Claude Code 的 `CLAUDE.md` 都是这个原理）；
2. `edit_file` 只替换一小段，而不是整个文件重写；
3. `run_tests` 让 Agent 能自己验证——**有反馈信号，Agent 才能自我纠错**；
4. 多轮对话：完成后可以继续追问"为什么这样改？"；每一步都记在 `agent_log.txt`。

---

## 第 7 步：用真正的编程 Agent 完成本周小功能（核心实操）

用你装好的编程 Agent（Trae / 通义灵码 / Cursor / Claude Code 等均可，也可以继续用 03），完成：
1. 修好 `grade_stats.py` 里的全部 bug；
2. 实现 `grade_level()`；
3. `python -m pytest -q` 全部通过，`python report.py students.csv` 正常输出。

**按这个流程做，不要一句话"帮我全改了"：**

```
① 交代任务：让 Agent 先读 AGENTS.md 和代码
② 要计划：  "先不要改代码，列出你发现的问题和修改计划"
③ 人审计划：哪条不同意就直接说
④ 小步执行："先修第 1 个问题，然后运行测试"
⑤ 看测试：  失败就把报错原样交给它
⑥ 审代码：  逐行看懂 diff（见下方清单）
⑦ 提交：    git commit -m "fix: 修正 pass_rate 及格线边界"
```

### "看得懂才敢用"代码验收清单

- [ ] 我能用自己的话讲出这段改动在做什么
- [ ] 边界情况想过了吗？（空列表、60 分、100 分、负数、缺考）
- [ ] 它有没有偷偷改测试、删数据、改函数名？
- [ ] 有没有引入不需要的第三方库？
- [ ] 测试全部通过，并且我知道每个测试在测什么
- [ ] 有一处是我自己发现并纠正的 AI 问题（写进反思）

---

## 常见报错速查

| 报错 | 原因 | 解决 |
|---|---|---|
| `没有找到可用的 LLM_API_KEY` | 没建 `.env` 或没填 Key | 按第 2 步操作 |
| `AuthenticationError` / 401 | Key 错误或已失效 | 重新复制 Key，注意别多复制空格 |
| `NotFoundError` / 404 model | 模型名写错 | 对照平台文档改 `LLM_MODEL` |
| `APIConnectionError` | 网络 / `LLM_BASE_URL` 不对 | 检查网址；机房断网就用模拟模式 |
| `RateLimitError` / 429 | 请求太频繁或余额不足 | 等一会儿；检查账户余额 |
| 模型从不调用工具 | 模型不支持 Function Calling 或描述不清 | 换支持工具调用的模型；改 `description` |
| `UnicodeDecodeError` | 文件不是 UTF-8 | 用编辑器另存为 UTF-8 |
| `ModuleNotFoundError: openai` | 依赖没装在当前环境 | 激活虚拟环境后重新 `pip install` |

## 课后作业

- **基础（必做）**：完成第 7 步并提交 Git 记录截图；本周模板库至少新增 3 条模板。
- **进阶（选做）**：完成实操 3 的一个工具，写一段 200 字说明：工具做什么、为什么要（或不要）人工确认。
- **挑战（选做）**：了解 MCP（Model Context Protocol），说说它和我们手写的 `SCHEMAS` 是什么关系。
- **反思（必做）**：写下"AI 这次哪里做错了 / 我是怎么发现并纠正的"。
