"""Tests for replay orchestration resilience."""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

import benchmark.runner as runner  # noqa: E402
from benchmark.judge import pairwise_judge  # noqa: E402
from benchmark.runner import run_replay  # noqa: E402

AGENT = os.path.join(ROOT, "agent.py")


def _seed_repo(path: str, commits: int = 20) -> None:
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "t"], check=True)
    for i in range(commits):
        with open(os.path.join(path, f"f{i}.py"), "w", encoding="utf-8") as f:
            f.write(f"x = {i}\n")
        subprocess.run(["git", "-C", path, "add", "-A"], check=True)
        subprocess.run(["git", "-C", path, "commit", "-q", "-m", f"commit {i}"], check=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_replay_continues_after_task_failure(monkeypatch):
    """One bad LLM/judge failure must not abort the remaining replay tasks."""
    repo = tempfile.mkdtemp()
    calls = {"n": 0}

    def flaky_judge(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("inference proxy timed out")
        return pairwise_judge(*args, **kwargs)

    monkeypatch.setattr(runner, "pairwise_judge", flaky_judge)
    try:
        _seed_repo(repo)
        res = run_replay(repo, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert res["tasks"] == 2
        assert res["scored_tasks"] == 1
        assert res["task_errors"] == 1
        assert len(res["rows"]) == 2
        assert "error" in res["rows"][0]
        assert "winner" in res["rows"][1]
        assert sum(res["tally"].values()) == 1
    finally:
        shutil.rmtree(repo, ignore_errors=True)
