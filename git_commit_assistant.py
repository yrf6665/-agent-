"""
Git 提交助手：检查仓库状态，按用户确认暂存、提交和推送。
运行：python git_commit_assistant.py
"""
import json
import re
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

from common import MODEL, client, to_dict

REPO_ROOT = Path(__file__).resolve().parent
MAX_STEPS = 10
MAX_CHARS = 4000
GIT_TIMEOUT = 30
PUSH_TIMEOUT = 120


def _clip(text):
    text = str(text).strip()
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + "\n……（输出过长，已截断）"
    return text or "（无输出）"


def _redact(text):
    """隐藏远程 URL 中可能意外包含的用户名和凭据。"""
    return re.sub(r"(https?://)[^/@\s]+@", r"\1[已隐藏]@", str(text))


def _run_git(args, timeout=GIT_TIMEOUT):
    command = ["git", "-c", "core.quotepath=false", "-C", str(REPO_ROOT), *args]
    try:
        return subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, "", "系统中没有找到 Git。请先安装 Git。")
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(command, 124, stdout, stderr or "Git 命令超时。")


def _failure(result):
    detail = (result.stderr or result.stdout or "Git 命令失败。").strip()
    return _clip(_redact(detail))


def _repo_check():
    result = _run_git(["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return _failure(result)
    actual_root = Path(result.stdout.strip()).resolve()
    if actual_root != REPO_ROOT.resolve():
        return "安全检查失败：脚本所在目录不是 Git 仓库根目录，已停止。"
    return None


def _staged_paths():
    result = _run_git(["diff", "--cached", "--name-only", "-z"])
    if result.returncode != 0:
        raise RuntimeError(_failure(result))
    return [path for path in result.stdout.split("\0") if path]


def _validate_path(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("文件路径必须是非空字符串。")
    normalized = path.strip().replace("\\", "/")
    windows_path = PureWindowsPath(path)
    pure_path = PurePosixPath(normalized)
    if windows_path.is_absolute() or pure_path.is_absolute() or ":" in normalized:
        raise ValueError(f"只接受仓库内的相对文件路径：{path}")
    if any(part == ".." for part in pure_path.parts):
        raise ValueError(f"路径不能跳出仓库：{path}")
    if any(char in normalized for char in "*?[]"):
        raise ValueError(f"不接受通配符，请逐个写出文件路径：{path}")
    if not pure_path.parts or pure_path.as_posix() == ".":
        raise ValueError("请指定具体文件，不能暂存整个目录。")

    candidate = REPO_ROOT.joinpath(*pure_path.parts).resolve()
    try:
        relative = candidate.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"路径不能跳出仓库：{path}") from exc
    if candidate == REPO_ROOT.resolve() or candidate.is_dir():
        raise ValueError(f"请指定具体文件，不能暂存目录：{path}")

    status = _run_git(["status", "--short", "--", relative])
    if status.returncode != 0:
        raise RuntimeError(_failure(status))
    if not status.stdout.strip():
        raise ValueError(f"文件没有 Git 改动，或已被忽略：{relative}")
    return relative


def _confirm(question):
    return input(f"\n⚠ {question}\n允许吗？(y/n) ").strip().lower() == "y"


def git_status():
    """只读显示当前仓库分支和工作区、暂存区状态。"""
    problem = _repo_check()
    if problem:
        return problem
    result = _run_git(["status", "--short", "--branch"])
    if result.returncode != 0:
        return _failure(result)
    return _clip(result.stdout or "工作区干净，没有待提交的改动。")


def git_diff(paths=None):
    """只读显示暂存、未暂存和未跟踪文件的改动，不修改 Git 状态。"""
    problem = _repo_check()
    if problem:
        return problem

    selected = None
    if paths is not None:
        if not isinstance(paths, list) or not paths:
            return "paths 必须是非空的仓库相对文件路径列表，或省略以查看全部改动。"
        try:
            selected = list(dict.fromkeys(_validate_path(path) for path in paths))
        except (ValueError, RuntimeError) as exc:
            return _clip(str(exc))

    path_args = ["--", *selected] if selected else []
    status = _run_git(["status", "--short", "--branch", *path_args])
    if status.returncode != 0:
        return _failure(status)
    staged = _run_git(["diff", "--cached", "--no-ext-diff", "--no-color", "--unified=3", *path_args])
    if staged.returncode != 0:
        return _failure(staged)
    unstaged = _run_git(["diff", "--no-ext-diff", "--no-color", "--unified=3", *path_args])
    if unstaged.returncode != 0:
        return _failure(unstaged)
    untracked = _run_git(["ls-files", "--others", "--exclude-standard", "-z", *path_args])
    if untracked.returncode != 0:
        return _failure(untracked)

    untracked_previews = []
    for relative in filter(None, untracked.stdout.split("\0")):
        try:
            safe_relative = _validate_path(relative)
            file_path = REPO_ROOT.joinpath(*PurePosixPath(safe_relative).parts)
            with file_path.open("rb") as file:
                content = file.read(MAX_CHARS + 1)
        except (OSError, ValueError, RuntimeError) as exc:
            untracked_previews.append(f"--- {relative}\n（无法读取：{exc}）")
            continue
        if b"\0" in content:
            detail = "（二进制文件，不显示内容）"
        else:
            text = content.decode("utf-8", errors="replace")
            if len(content) > MAX_CHARS:
                text += "\n……（新文件内容过长，预览已截断）"
            detail = "\n" + "\n".join(f"+ {line}" for line in text.splitlines())
        untracked_previews.append(f"--- 新文件：{safe_relative}{detail}")

    if not staged.stdout and not unstaged.stdout and not untracked_previews:
        return _clip(f"没有待提交的文件改动。\n{status.stdout.strip()}")

    sections = [f"当前状态：\n{status.stdout.strip()}"]
    if staged.stdout.strip():
        sections.append(f"已暂存的差异：\n{staged.stdout.strip()}")
    if unstaged.stdout.strip():
        sections.append(f"未暂存的差异：\n{unstaged.stdout.strip()}")
    if untracked_previews:
        sections.append("未跟踪的新文件：\n" + "\n\n".join(untracked_previews))
    return _clip("\n\n".join(sections))


def git_stage(paths):
    """在暂存区为空时，经用户确认后暂存明确列出的仓库相对文件。"""
    problem = _repo_check()
    if problem:
        return problem
    if not isinstance(paths, list) or not paths:
        return "请提供至少一个明确的仓库相对文件路径。"

    try:
        already_staged = _staged_paths()
        if already_staged:
            listing = "、".join(already_staged)
            return _clip(
                f"暂存区已有内容：{listing}。为避免混入其他改动，我没有暂存新文件。"
                "请先检查或提交现有暂存内容，再重试。"
            )
        selected = []
        for path in paths:
            relative = _validate_path(path)
            if relative not in selected:
                selected.append(relative)
    except (ValueError, RuntimeError) as exc:
        return _clip(str(exc))

    preview = "\n".join(f"  - {path}" for path in selected)
    if not _confirm(f"将只暂存以下文件：\n{preview}"):
        return "用户拒绝暂存；Git 暂存区未被修改。"

    result = _run_git(["add", "--", *selected])
    if result.returncode != 0:
        return _failure(result)
    try:
        staged = _staged_paths()
    except RuntimeError as exc:
        return str(exc)
    if set(staged) != set(selected):
        return _clip(
            "暂存后的文件列表与选择不一致，请运行 git status 检查；"
            f"当前暂存文件：{', '.join(staged) or '无'}。"
        )
    stat = _run_git(["diff", "--cached", "--stat"])
    detail = stat.stdout.strip() if stat.returncode == 0 else ""
    return _clip(f"已暂存：{', '.join(staged)}\n{detail}")


def git_commit(message):
    """显示暂存文件、改动统计和完整差异，经用户确认后创建本地提交。"""
    problem = _repo_check()
    if problem:
        return problem
    if not isinstance(message, str) or not message.strip():
        return "提交说明不能为空。"
    try:
        staged = _staged_paths()
    except RuntimeError as exc:
        return str(exc)
    if not staged:
        return "暂存区为空，没有创建提交。先用 git_stage 暂存明确选择的文件。"

    stat = _run_git(["diff", "--cached", "--stat"])
    if stat.returncode != 0:
        return _failure(stat)
    diff = _run_git(["diff", "--cached", "--no-ext-diff", "--no-color", "--unified=3", "--"])
    if diff.returncode != 0:
        return _failure(diff)

    branch = _run_git(["branch", "--show-current"])
    branch_name = branch.stdout.strip() if branch.returncode == 0 else "当前分支"
    listing = "\n".join(f"  - {path}" for path in staged)
    change_summary = stat.stdout.strip() or "（没有文本改动统计，可能是二进制或仅文件属性变化）"
    change_diff = diff.stdout.strip() or "（没有可显示的文本差异）"
    commit_message = message.strip()
    if not _confirm(
        f"将在分支 {branch_name} 创建本地提交。\n"
        f"暂存文件：\n{listing}\n\n"
        f"改动统计：\n{change_summary}\n\n"
        f"具体差异（Git diff）：\n{change_diff}\n\n"
        f"提交说明：{commit_message}"
    ):
        return "用户拒绝提交；暂存内容保留，没有创建提交。"

    result = _run_git(["commit", "-m", commit_message], timeout=60)
    if result.returncode != 0:
        return _failure(result) + "\n提交未成功；暂存内容仍保留。"
    return _clip(_redact(result.stdout + result.stderr))


def git_push():
    """显示当前分支的 upstream 和待推送提交数，单独确认后执行普通 git push。"""
    problem = _repo_check()
    if problem:
        return problem
    branch = _run_git(["branch", "--show-current"])
    branch_name = branch.stdout.strip() if branch.returncode == 0 else ""
    if branch.returncode != 0 or not branch_name:
        return "当前处于 detached HEAD 状态，不能安全推送。"

    upstream = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    if upstream.returncode != 0:
        return "当前分支没有配置 upstream；我没有添加远程仓库，也没有推送。"
    destination = upstream.stdout.strip()

    ahead = _run_git(["rev-list", "--count", "@{upstream}..HEAD"])
    behind = _run_git(["rev-list", "--count", "HEAD..@{upstream}"])
    if ahead.returncode != 0 or behind.returncode != 0:
        return _failure(ahead if ahead.returncode != 0 else behind)
    ahead_count = int(ahead.stdout.strip() or "0")
    behind_count = int(behind.stdout.strip() or "0")
    if ahead_count == 0:
        return f"分支 {branch_name} 没有待推送的提交。"
    if behind_count:
        return f"远程分支 {destination} 领先本地 {behind_count} 个提交；为避免非快进推送，已停止。请先手动同步并检查改动。"

    status = _run_git(["status", "--short"])
    dirty_note = "工作区还有未提交改动；它们不会被此次推送包含。" if status.stdout.strip() else "工作区干净。"
    if not _confirm(
        f"将把 {ahead_count} 个已提交的提交从 {branch_name} 推送到 {destination}。"
        f"\n{dirty_note}\n不会使用 force push。"
    ):
        return "用户拒绝推送；远程仓库未被修改。"

    result = _run_git(["push"], timeout=PUSH_TIMEOUT)
    if result.returncode != 0:
        return _failure(result)
    return _clip(_redact(result.stdout + result.stderr) or "推送成功。")


def schema(name, description, properties=None, required=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": list(required),
            },
        },
    }


STR = {"type": "string"}
SCHEMAS = [
    schema("git_status", "只读检查当前课堂代码仓库的分支和改动状态。开始 Git 操作前先调用。"),
    schema(
        "git_diff",
        "只读查看工作区的已暂存、未暂存和新文件改动；用户询问改了什么时调用。不会暂存、提交或推送。可传明确文件列表缩小范围，也可省略查看全部。",
        {"paths": {"type": "array", "items": STR}},
    ),
    schema(
        "git_stage",
        "经用户确认后暂存明确列出的仓库相对文件路径；不能传目录、通配符或 '.'。暂存区已有内容时会停止。",
        {"paths": {"type": "array", "items": STR}},
        ["paths"],
    ),
    schema(
        "git_commit",
        "先向用户展示当前暂存文件、改动统计和完整 Git diff，再经确认提交暂存区内容。",
        {"message": STR},
        ["message"],
    ),
    schema(
        "git_push",
        "仅在用户明确要求推送时调用；会显示 upstream 和待推送数量，并再次征求确认。不会 force push。",
    ),
]

TOOLS = {
    "git_status": git_status,
    "git_diff": git_diff,
    "git_stage": git_stage,
    "git_commit": git_commit,
    "git_push": git_push,
}

SYSTEM_PROMPT = (
    "你是一个专门帮助用户检查、提交和推送当前课堂代码仓库的 Git 助手。\n"
    "用户询问改了什么时，调用只读 git_diff 查看具体差异；绝不能为了展示差异而暂存、提交或推送。\n"
    "提交或推送任务开始时先调用 git_status；根据用户明确指定的文件调用 git_stage；"
    "再调用 git_commit；只有用户明确要求上传时，才调用 git_push。\n"
    "git_stage、git_commit 和 git_push 都会在程序侧显示具体操作并要求用户确认。"
    "不要尝试绕过确认，不要调用未提供的命令，不要声称失败的操作已成功。\n"
    "只管理本脚本所在的 Git 仓库。不要自动选择所有文件，不要使用 git add .，不要配置 remote、重置或强制推送。"
)


def run_turn(messages):
    """处理一项用户请求；每轮最多调用 MAX_STEPS 次模型。"""
    for step in range(1, MAX_STEPS + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=SCHEMAS,
        )
        message = response.choices[0].message
        messages.append(to_dict(message))

        if message.content:
            print(f"\n💭 {message.content}")
        if not message.tool_calls:
            if not message.content:
                print("\n✅ 完成。")
            return

        for call in message.tool_calls:
            name = call.function.name
            try:
                arguments = json.loads(call.function.arguments or "{}")
                if name not in TOOLS:
                    result = f"不允许调用未知工具：{name}"
                else:
                    print(f"🔧 调用 {name}({arguments})")
                    result = TOOLS[name](**arguments)
            except Exception as exc:
                result = f"工具执行出错：{type(exc).__name__}: {exc}"
            print(f"👀 {_clip(result)[:240]}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": _clip(result)})
    print(f"\n⛔ 已达到最大步数 {MAX_STEPS}，本轮停止。")


def main():
    print(f"Git 仓库：{REPO_ROOT}\n模型：{MODEL}（输入 exit 退出）")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        try:
            task = input("\n🧑 你：").strip()
        except EOFError:
            break
        if task.lower() in ("exit", "quit", "q"):
            break
        if task:
            messages.append({"role": "user", "content": task})
            run_turn(messages)


if __name__ == "__main__":
    main()
