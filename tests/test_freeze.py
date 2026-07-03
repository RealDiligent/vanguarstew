"""Tests for frozen-context construction from git history."""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze import _safe_extractall, export_tree, build_context  # noqa: E402


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", repo, *args], check=True, env=env)


def _commit_and_tag(repo: str, seq: int, tag: str) -> None:
    path = os.path.join(repo, f"f{seq}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{tag}\n")
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_DATE": f"2024-01-{seq:02d}T12:00:00+00:00",
        "GIT_COMMITTER_DATE": f"2024-01-{seq:02d}T12:00:00+00:00",
    })
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", f"commit {tag}", env=env)
    _git(repo, "tag", tag, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_build_context_sorts_releases_chronologically():
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        for seq, tag in enumerate(("v1.8.0", "v1.9.0", "v1.10.0", "v1.11.0"), start=1):
            _commit_and_tag(repo, seq, tag)

        ctx = build_context(repo, "HEAD")
        assert [r["tag"] for r in ctx["releases"]] == ["v1.8.0", "v1.9.0", "v1.10.0", "v1.11.0"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_build_context_keeps_ten_most_recent_releases():
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        tags = [f"v1.{i}.0" for i in range(1, 13)]
        for seq, tag in enumerate(tags, start=1):
            _commit_and_tag(repo, seq, tag)

        ctx = build_context(repo, "HEAD")
        assert [r["tag"] for r in ctx["releases"]] == tags[-10:]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_build_context_release_order_is_not_lexicographic():
    # Stronger #90 guard: the newest tag (v1.2.0) is created LAST, so it sorts to
    # the middle lexicographically — chronological creation order must still win.
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        creation = ["v1.8.0", "v1.9.0", "v1.10.0", "v1.11.0", "v1.2.0"]
        for seq, tag in enumerate(creation, start=1):
            _commit_and_tag(repo, seq, tag)

        tags = [r["tag"] for r in build_context(repo, "HEAD")["releases"]]
        assert tags == creation              # chronological (creation) order
        assert tags != sorted(creation)      # explicitly NOT lexicographic refname order
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _tar_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_safe_extractall_extracts_regular_files():
    dest = tempfile.mkdtemp()
    try:
        payload = _tar_bytes([("src/app.py", b"print('ok')\n"), ("README.md", b"hi\n")])
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tf:
            _safe_extractall(tf, dest)
        assert open(os.path.join(dest, "src", "app.py"), encoding="utf-8").read() == "print('ok')\n"
        assert open(os.path.join(dest, "README.md"), encoding="utf-8").read() == "hi\n"
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_rejects_path_traversal():
    dest = tempfile.mkdtemp()
    outside = os.path.join(tempfile.gettempdir(), "vanguarstew_escape_test.txt")
    try:
        payload = _tar_bytes([("../../vanguarstew_escape_test.txt", b"pwned\n")])
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tf:
            with pytest.raises(tarfile.TarError, match="unsafe path"):
                _safe_extractall(tf, dest)
        assert not os.path.exists(outside)
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        if os.path.exists(outside):
            os.remove(outside)


def test_safe_extractall_skips_symlinks():
    dest = tempfile.mkdtemp()
    try:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
            info = tarfile.TarInfo(name="safe.txt")
            info.size = 3
            tf.addfile(info, io.BytesIO(b"ok\n"))
        with tarfile.open(fileobj=io.BytesIO(buf.getvalue()), mode="r:") as tf:
            _safe_extractall(tf, dest)
        assert not os.path.lexists(os.path.join(dest, "link"))
        assert open(os.path.join(dest, "safe.txt"), encoding="utf-8").read() == "ok\n"
    finally:
        shutil.rmtree(dest, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_export_tree_extracts_git_archive():
    repo = tempfile.mkdtemp()
    dest = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        with open(os.path.join(repo, "hello.txt"), "w", encoding="utf-8") as f:
            f.write("frozen\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        export_tree(repo, "HEAD", dest)
        assert open(os.path.join(dest, "hello.txt"), encoding="utf-8").read() == "frozen\n"
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(dest, ignore_errors=True)
