import json
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from history import deployment_log_path, finish_deployment, interrupt_running, start_deployment

from deployer import gitops
from deployer.config import Project
from deployer.runner import run_update


class LockTimeout(Exception):
    pass


def read_state(path: Path) -> dict:
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else {}


@contextmanager
def deployment_lock(path: Path | None, timeout: float):
    if path is None:
        yield
        return

    deadline = time.monotonic() + timeout
    while True:
        try:
            path.mkdir()
            break
        except FileExistsError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LockTimeout
            time.sleep(min(1, remaining))
    try:
        yield
    finally:
        path.rmdir()


def in_blackout(window: tuple[str, str] | None, now: datetime) -> bool:
    if not window:
        return False
    t = now.strftime("%H:%M")
    start, end = window
    return start <= t < end if start <= end else t >= start or t < end


def clear_blocked(s: dict) -> bool:
    """清掉停住的原因；原本有停住才回 True。"""
    had = s.pop("blocked", None) is not None
    for key in ("blocked_kind", "blocked_sha", "blocked_since"):
        s.pop(key, None)
    return had


class Round:
    def __init__(self, state_path, log_path, history_path, ci_status, notify, now, timeout, lock_timeout):
        self.state_path = Path(state_path)
        self.log_path = Path(log_path)
        self.history_path = Path(history_path)
        self.ci_status = ci_status
        self.notify = notify
        self.now = now
        self.timeout = timeout
        self.lock_timeout = lock_timeout
        self.state = read_state(self.state_path)
        interrupt_running(self.history_path, self.now())

    def log(self, project: str, text: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(f"{self.now():%Y-%m-%d %H:%M:%S} [{project}] {text}\n")

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False))
        tmp.replace(self.state_path)

    def alert(self, project: str, text: str) -> None:
        try:
            if not self.notify(text):
                self.log(project, "沒設 LINE 權杖，不傳通知")
        except Exception as e:
            self.log(project, f"LINE 通知失敗：{e}")

    def stop(self, p: Project, reason: str, kind: str, sha: str | None = None, alert: bool = False) -> None:
        """停下來；同一個原因只在第一次寫記錄（和通知）。

        kind 是給網頁判斷燈號用的種類：ci_pending、ci_failed、blackout、attention（需要人處理）、remote_error。
        """
        s = self.state.setdefault(p.name, {})
        if s.get("blocked") == reason:
            return
        s.update(blocked=reason, blocked_kind=kind, blocked_sha=sha, blocked_since=self.now().isoformat())
        self.save()
        self.log(p.name, reason)
        if alert:
            self.alert(p.name, f"[mini-deploy] {p.name}：{reason}\n記錄檔：{self.log_path}")

    def handle(self, p: Project) -> None:
        s = self.state.get(p.name, {})
        if "deployed" not in s:  # 還沒成功讀過這個專案（第一次處理，或之前一直出錯）
            head = gitops.head(p.path)
            self.state[p.name] = {"deployed": head, "failed": None, "deployed_title": gitops.commit_title(p.path, head)}
            self.save()
            self.log(p.name, f"第一次處理，把目前的 {self.state[p.name]['deployed'][:7]} 當作已部署")
            return
        if "deployed_title" not in s:  # 加這個欄位之前寫的狀態檔
            s["deployed_title"] = gitops.commit_title(p.path, s["deployed"])
            self.save()
        try:
            sha = gitops.remote_head(p.path, p.branch)
        except gitops.GitError as e:
            return self.stop(p, f"查不到遠端分支：{e}", "remote_error")
        if sha in (s.get("deployed"), s.get("failed")):
            if clear_blocked(s):
                self.save()
            return
        if in_blackout(p.blackout, self.now()):
            return self.stop(p, f"{sha[:7]} 落在禁止時段 {p.blackout[0]}–{p.blackout[1]}，時段過後再部署", "blackout", sha)
        ci = self.ci_status(p.repo, sha)
        if ci == "pending":
            return self.stop(p, f"{sha[:7]} 的 CI 還沒有結果，下一輪再看", "ci_pending", sha)
        if ci != "success":
            return self.stop(p, f"{sha[:7]} 的 CI 沒過，不部署", "ci_failed", sha)
        if gitops.is_dirty(p.path):
            return self.stop(p, f"{p.path} 有未提交的改動，不部署", "attention", sha, alert=True)
        gitops.fetch(p.path, p.branch)
        if not gitops.can_fast_forward(p.path, sha):
            return self.stop(p, f"{p.path} 有遠端沒有的 commit，不能快轉，不部署", "attention", sha, alert=True)

        try:
            with deployment_lock(p.lock, self.lock_timeout):
                gitops.fast_forward(p.path, sha)
                clear_blocked(s)
                self.log(p.name, f"開始部署 {sha[:7]}")
                title = gitops.commit_title(p.path, sha)
                deployment_id = start_deployment(self.history_path, p.name, sha, title, self.now())
                error = run_update(
                    p.path,
                    deployment_log_path(self.history_path, deployment_id),
                    self.timeout,
                )
        except LockTimeout:
            return self.stop(p, f"等了 {self.lock_timeout:g} 秒仍拿不到鎖 {p.lock}，不部署", "attention", sha, alert=True)
        if error is None:
            finish_deployment(self.history_path, deployment_id, "成功", self.now())
            s.update(deployed=sha, deployed_title=title, failed=None)
            self.save()
            self.log(p.name, f"部署成功 {sha[:7]}")
        else:
            result = "逾時" if error.startswith("超過 ") else "失敗"
            finish_deployment(self.history_path, deployment_id, result, self.now(), error)
            s["failed"] = sha
            self.save()
            self.log(p.name, f"部署失敗 {sha[:7]}：{error}")
            self.alert(
                p.name,
                f"[mini-deploy] {p.name} 部署失敗\ncommit {sha[:7]}：{error}\n"
                f"https://liumac-mini.tail93fb54.ts.net:41200/deploys/{deployment_id}",
            )


def run_once(
    projects: list[Project],
    *,
    state_path: Path,
    log_path: Path,
    history_path: Path,
    ci_status: Callable[[str, str], str],
    notify: Callable[[str], bool],
    now: Callable[[], datetime] = datetime.now,
    timeout: float = 30 * 60,
    lock_timeout: float = 10 * 60,
) -> None:
    r = Round(state_path, log_path, history_path, ci_status, notify, now, timeout, lock_timeout)
    for p in projects:
        try:
            r.handle(p)
        except Exception as e:
            r.stop(p, f"出錯：{''.join(traceback.format_exception_only(e)).strip()}", "attention", alert=True)
