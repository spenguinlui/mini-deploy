import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from deployer import gitops
from deployer.config import Project
from deployer.runner import run_update


def in_blackout(window: tuple[str, str] | None, now: datetime) -> bool:
    if not window:
        return False
    t = now.strftime("%H:%M")
    start, end = window
    return start <= t < end if start <= end else t >= start or t < end


class Round:
    def __init__(self, state_path, log_path, ci_status, notify, now, timeout):
        self.state_path = Path(state_path)
        self.log_path = Path(log_path)
        self.ci_status = ci_status
        self.notify = notify
        self.now = now
        self.timeout = timeout
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}

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

    def stop(self, p: Project, reason: str, alert: bool = False) -> None:
        """停下來；同一個原因只在第一次寫記錄（和通知）。"""
        s = self.state[p.name]
        if s.get("blocked") == reason:
            return
        s["blocked"] = reason
        self.save()
        self.log(p.name, reason)
        if alert:
            self.alert(p.name, f"[mini-deploy] {p.name}：{reason}\n記錄檔：{self.log_path}")

    def handle(self, p: Project) -> None:
        if p.name not in self.state:
            self.state[p.name] = {"deployed": gitops.head(p.path), "failed": None}
            self.save()
            self.log(p.name, f"第一次處理，把目前的 {self.state[p.name]['deployed'][:7]} 當作已部署")
            return
        s = self.state[p.name]
        try:
            sha = gitops.remote_head(p.path, p.branch)
        except gitops.GitError as e:
            return self.stop(p, f"查不到遠端分支：{e}")
        if sha in (s.get("deployed"), s.get("failed")):
            if s.pop("blocked", None) is not None:
                self.save()
            return
        if in_blackout(p.blackout, self.now()):
            return self.stop(p, f"{sha[:7]} 落在禁止時段 {p.blackout[0]}–{p.blackout[1]}，時段過後再部署")
        ci = self.ci_status(p.repo, sha)
        if ci == "pending":
            return self.stop(p, f"{sha[:7]} 的 CI 還沒有結果，下一輪再看")
        if ci != "success":
            return self.stop(p, f"{sha[:7]} 的 CI 沒過，不部署")
        if gitops.is_dirty(p.path):
            return self.stop(p, f"{p.path} 有未提交的改動，不部署", alert=True)
        gitops.fetch(p.path, p.branch)
        if not gitops.can_fast_forward(p.path, sha):
            return self.stop(p, f"{p.path} 有遠端沒有的 commit，不能快轉，不部署", alert=True)

        s.pop("blocked", None)
        self.log(p.name, f"開始部署 {sha[:7]}")
        gitops.fast_forward(p.path, sha)
        error = run_update(p.path, self.log_path, self.timeout)
        if error is None:
            s.update(deployed=sha, failed=None)
            self.save()
            self.log(p.name, f"部署成功 {sha[:7]}")
        else:
            s["failed"] = sha
            self.save()
            self.log(p.name, f"部署失敗 {sha[:7]}：{error}")
            self.alert(p.name, f"[mini-deploy] {p.name} 部署失敗\ncommit {sha[:7]}：{error}\n記錄檔：{self.log_path}")


def run_once(
    projects: list[Project],
    *,
    state_path: Path,
    log_path: Path,
    ci_status: Callable[[str, str], str],
    notify: Callable[[str], bool],
    now: Callable[[], datetime] = datetime.now,
    timeout: float = 30 * 60,
) -> None:
    r = Round(state_path, log_path, ci_status, notify, now, timeout)
    for p in projects:
        try:
            r.handle(p)
        except Exception as e:
            r.log(p.name, "".join(traceback.format_exception_only(e)).strip())
            if p.name in r.state:
                r.stop(p, f"出錯：{e}", alert=True)
