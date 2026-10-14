import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _git(path: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        raise GitError(str(e)) from e
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def remote_head(path: Path, branch: str) -> str:
    out = _git(path, "ls-remote", "origin", f"refs/heads/{branch}")
    if not out:
        raise GitError(f"遠端沒有分支 {branch}")
    return out.split()[0]


def head(path: Path) -> str:
    return _git(path, "rev-parse", "HEAD")


def is_dirty(path: Path) -> bool:
    # 沒被追蹤的檔案（執行時產生的檔案）不算，快轉不會動到它們
    return bool(_git(path, "status", "--porcelain", "--untracked-files=no"))


def fetch(path: Path, branch: str) -> None:
    _git(path, "fetch", "--quiet", "origin", branch)


def can_fast_forward(path: Path, sha: str) -> bool:
    try:
        _git(path, "merge-base", "--is-ancestor", "HEAD", sha)
        return True
    except GitError:
        return False


def fast_forward(path: Path, sha: str) -> None:
    _git(path, "merge", "--ff-only", "--quiet", sha)
