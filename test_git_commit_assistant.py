import os
import subprocess
from pathlib import Path

import pytest

# common.py needs a configured key to construct the client; these tests never call the model.
os.environ["LLM_API_KEY"] = "unit-test-key"

import git_commit_assistant as assistant
from mock_server import decide


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "branch", "-M", "main")
    (root / "base.txt").write_text("initial\n", encoding="utf-8")
    git(root, "add", "base.txt")
    git(root, "commit", "-m", "initial")
    monkeypatch.setattr(assistant, "REPO_ROOT", root)
    return root


def test_status_reports_branch_and_untracked_file(repo):
    (repo / "new note.md").write_text("draft\n", encoding="utf-8")

    result = assistant.git_status()

    assert "## main" in result
    assert "new note.md" in result


def test_stage_only_explicit_file(repo, monkeypatch):
    (repo / "first.txt").write_text("one\n", encoding="utf-8")
    (repo / "second.txt").write_text("two\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    result = assistant.git_stage(["first.txt"])

    assert "已暂存" in result
    assert git(repo, "diff", "--cached", "--name-only") == "first.txt"
    assert "second.txt" in git(repo, "status", "--short")


def test_declining_stage_leaves_index_unchanged(repo, monkeypatch):
    (repo / "new.txt").write_text("draft\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    result = assistant.git_stage(["new.txt"])

    assert "拒绝" in result
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_stage_refuses_to_mix_with_existing_staged_files(repo, monkeypatch):
    (repo / "already-staged.txt").write_text("one\n", encoding="utf-8")
    (repo / "new.txt").write_text("two\n", encoding="utf-8")
    git(repo, "add", "already-staged.txt")
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    result = assistant.git_stage(["new.txt"])

    assert "暂存区已有内容" in result
    assert git(repo, "diff", "--cached", "--name-only") == "already-staged.txt"


def test_stage_rejects_path_outside_repository(repo, monkeypatch):
    prompt_called = False

    def unexpected_prompt(_prompt):
        nonlocal prompt_called
        prompt_called = True
        return "y"

    monkeypatch.setattr("builtins.input", unexpected_prompt)
    result = assistant.git_stage(["../outside.txt"])

    assert "不能跳出仓库" in result
    assert not prompt_called
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_commit_requires_confirmation_and_keeps_stage_when_declined(repo, monkeypatch):
    (repo / "new.txt").write_text("draft\n", encoding="utf-8")
    git(repo, "add", "new.txt")
    old_head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    result = assistant.git_commit("test commit")

    assert "拒绝提交" in result
    assert git(repo, "rev-parse", "HEAD") == old_head
    assert git(repo, "diff", "--cached", "--name-only") == "new.txt"


def test_commit_creates_local_commit_after_confirmation(repo, monkeypatch):
    (repo / "new.txt").write_text("draft\n", encoding="utf-8")
    git(repo, "add", "new.txt")
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    result = assistant.git_commit("add new file")

    assert "add new file" in git(repo, "log", "-1", "--format=%s")
    assert "new.txt" in result


def test_push_requires_upstream(repo, monkeypatch):
    prompt_called = False

    def unexpected_prompt(_prompt):
        nonlocal prompt_called
        prompt_called = True
        return "y"

    monkeypatch.setattr("builtins.input", unexpected_prompt)
    result = assistant.git_push()

    assert "没有配置 upstream" in result
    assert not prompt_called


def configure_local_remote(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    return remote


def create_outgoing_commit(repo):
    (repo / "outgoing.txt").write_text("outgoing\n", encoding="utf-8")
    git(repo, "add", "outgoing.txt")
    git(repo, "commit", "-m", "outgoing commit")


def test_declining_push_does_not_update_remote(repo, tmp_path, monkeypatch):
    remote = configure_local_remote(repo, tmp_path)
    create_outgoing_commit(repo)
    old_remote = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    result = assistant.git_push()

    new_remote = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert "拒绝推送" in result
    assert new_remote == old_remote


def test_confirmed_push_updates_only_local_bare_remote(repo, tmp_path, monkeypatch):
    remote = configure_local_remote(repo, tmp_path)
    create_outgoing_commit(repo)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    result = assistant.git_push()

    remote_head = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert "main -> main" in result
    assert remote_head == git(repo, "rev-parse", "HEAD")


def test_mock_server_demo_only_calls_read_only_status_tool():
    request = {
        "messages": [
            {"role": "system", "content": ""},
            {"role": "user", "content": "检查仓库状态，不要提交或推送"},
        ],
        "tools": assistant.SCHEMAS,
    }

    first_content, calls = decide(request)
    assert "只读" in first_content
    assert calls[0]["function"]["name"] == "git_status"

    request["messages"].extend([
        {"role": "assistant", "content": first_content, "tool_calls": calls},
        {"role": "tool", "tool_call_id": calls[0]["id"], "content": "## main\\n?? sample.md"},
    ])
    final_content, follow_up_calls = decide(request)

    assert follow_up_calls is None
    assert "不会暂存、提交或推送" in final_content