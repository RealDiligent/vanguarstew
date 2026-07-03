"""Freeze a repo at commit T and build the leakage-safe, knowable-at-T context.

We export the working tree at T and write `.vanguarstew_context.json` alongside it, derived
only from history up to and including T (commits, tags-as-releases, README). The agent
reads that — it never sees anything after T.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile

from agent.context import CONTEXT_FILE
from benchmark.leakage import scrub_context


def _safe_relative_name(name: str) -> str:
    """Normalize a tar member name and reject path-traversal attempts."""
    clean = name.replace("\\", "/").lstrip("/")
    parts = [p for p in clean.split("/") if p and p != "."]
    if not parts or ".." in parts:
        raise tarfile.TarError(f"unsafe path in tar archive: {name!r}")
    return "/".join(parts)


def _safe_join(dest: str, name: str) -> str:
    """Resolve `name` under `dest`, raising if it escapes the destination root."""
    rel = _safe_relative_name(name)
    joined = os.path.join(dest, *rel.split("/"))
    abs_dest = os.path.abspath(dest)
    abs_joined = os.path.abspath(joined)
    if abs_joined != abs_dest and not abs_joined.startswith(abs_dest + os.sep):
        raise tarfile.TarError(f"path escapes destination: {name!r}")
    return abs_joined


def _safe_extractall(tf: tarfile.TarFile, dest: str) -> None:
    """Extract only regular files and directories (py<3.12 ``filter='data'`` equivalent).

    Skips symlinks, hard links, and special files; rejects absolute paths and ``..``
    components so untrusted repo archives cannot escape the sandbox destination.
    """
    os.makedirs(dest, exist_ok=True)
    for member in tf.getmembers():
        if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
            continue
        if not member.isdir() and not member.isreg():
            continue
        target = _safe_join(dest, member.name)
        if member.isdir():
            os.makedirs(target, exist_ok=True)
            continue
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)
        src = tf.extractfile(member)
        if src is None:
            continue
        with src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def origin_url(repo: str) -> str:
    return _git(repo, "remote", "get-url", "origin", check=False).strip()


def export_tree(repo: str, commit: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    proc = subprocess.Popen(
        ["git", "-C", repo, "archive", "--format=tar", commit],
        stdout=subprocess.PIPE,
    )
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
        try:
            tf.extractall(dest, filter="data")  # py>=3.12
        except TypeError:
            _safe_extractall(tf, dest)
    proc.wait()
    if proc.returncode not in (0, None):
        raise RuntimeError(f"git archive failed for {commit}")


def file_at(repo: str, commit: str, path: str) -> str:
    r = subprocess.run(
        ["git", "-C", repo, "show", f"{commit}:{path}"],
        capture_output=True, text=True,
    )
    return r.stdout if r.returncode == 0 else ""


def build_context(repo: str, commit: str, lookback: int = 50) -> dict:
    log = _git(repo, "log", "--pretty=format:%H%x09%cI%x09%s", "-n", str(lookback), commit)
    commits = []
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({"sha": parts[0][:10], "date": parts[1], "subject": parts[2]})
    # `git tag --merged` defaults to refname order, which is wrong for versions like
    # v1.10.0 vs v1.9.0. Sort by creation date so `tags[-10:]` is truly the recent window.
    tags = [
        t
        for t in _git(repo, "tag", "--sort=creatordate", "--merged", commit, check=False).splitlines()
        if t
    ]
    readme = ""
    for name in ("README.md", "README.rst", "README", "docs/README.md"):
        content = file_at(repo, commit, name)
        if content:
            readme = content[:4000]
            break
    return {
        "frozen_at": {"commit": commit[:10], "date": commits[0]["date"] if commits else None},
        "recent_commits": commits,
        "open_issues": [],   # populated from the GitHub API in M2
        "open_prs": [],
        "labels": [],
        "milestones": [],
        "releases": [{"tag": t} for t in tags[-10:]],
        "readme_excerpt": readme,
        "_source": "git-freeze",
    }


def write_frozen(repo: str, commit: str, dest: str, lookback: int = 50, scrub: bool = True) -> dict:
    export_tree(repo, commit, dest)
    ctx = build_context(repo, commit, lookback)
    if scrub:
        ctx = scrub_context(ctx)
    with open(os.path.join(dest, CONTEXT_FILE), "w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=1)
    return ctx
