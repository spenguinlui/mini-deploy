import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from deployer import Project, main, run_once

NOON = datetime(2026, 10, 14, 12, 0)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Fake:
    def __init__(self):
        self.ci = {}  # sha -> "success" | "failure" | "pending"
        self.ci_calls = []
        self.messages = []
        self.on_ci = None

    def ci_status(self, repo, sha):
        self.ci_calls.append((repo, sha))
        if self.on_ci:
            self.on_ci()
        return self.ci.get(sha, "pending")

    def notify(self, text):
        self.messages.append(text)
        return True


class Env:
    def __init__(self, tmp: Path, name="app"):
        self.tmp = tmp
        self.name = name
        self.origin = tmp / f"{name}.git"
        self.work = tmp / f"{name}-work"
        self.clone = tmp / f"{name}-mini"
        self.marker = tmp / f"{name}-deployed.txt"
        git(tmp, "init", "--bare", "-b", "main", str(self.origin))
        git(tmp, "init", "-b", "main", str(self.work))
        git(self.work, "config", "user.email", "t@t")
        git(self.work, "config", "user.name", "t")
        git(self.work, "remote", "add", "origin", str(self.origin))
        self.commit(f'git rev-parse HEAD >> "{self.marker}"\n')
        git(tmp, "clone", "-q", str(self.origin), str(self.clone))
        git(self.clone, "config", "user.email", "t@t")
        git(self.clone, "config", "user.name", "t")

    def commit(self, script=None, msg="c"):
        if script is not None:
            (self.work / "deploy").mkdir(exist_ok=True)
            path = self.work / "deploy" / "update.sh"
            path.write_text("#!/bin/sh\nset -e\n" + script)
            path.chmod(0o755)
        (self.work / "n.txt").write_text(msg + str(datetime.now().timestamp()))
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", msg)
        git(self.work, "push", "-q", "origin", "main")
        return git(self.work, "rev-parse", "HEAD")

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def deployed(self):
        return self.marker.read_text().split() if self.marker.exists() else []

    def project(self, blackout=None):
        return Project(name=self.name, path=self.clone, branch="main", repo=f"me/{self.name}", blackout=blackout)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def fake():
    return Fake()


def run(env_or_projects, fake, tmp_path, now=NOON, timeout=1800):
    projects = env_or_projects if isinstance(env_or_projects, list) else [env_or_projects.project()]
    run_once(
        projects,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "deploy.log",
        ci_status=fake.ci_status,
        notify=fake.notify,
        now=lambda: now,
        timeout=timeout,
    )


def state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


def entries(tmp_path):
    import re
    return len(re.findall(r"^\d{4}-\d\d-\d\d ", log(tmp_path), re.M))


def log(tmp_path):
    p = tmp_path / "deploy.log"
    return p.read_text() if p.exists() else ""


def test_first_run_records_current_commit_without_deploying(env, fake, tmp_path):
    run(env, fake, tmp_path)
    assert state(tmp_path)["app"]["deployed"] == env.head()
    assert env.deployed() == []
    assert fake.ci_calls == []


def test_new_commit_ci_passed_deploys(env, fake, tmp_path):
    run(env, fake, tmp_path)
    sha = env.commit()
    fake.ci[sha] = "success"
    run(env, fake, tmp_path)
    assert env.head() == sha
    assert env.deployed() == [sha]
    assert state(tmp_path)["app"]["deployed"] == sha
    assert fake.ci_calls == [("me/app", sha)]
    assert "成功" in log(tmp_path)
    assert fake.messages == []


def test_unchanged_remote_skips_ci_and_writes_no_log(env, fake, tmp_path):
    run(env, fake, tmp_path)
    sha = env.commit()
    fake.ci[sha] = "success"
    run(env, fake, tmp_path)
    before = log(tmp_path)
    fake.ci_calls.clear()
    run(env, fake, tmp_path)
    run(env, fake, tmp_path)
    assert fake.ci_calls == []
    assert log(tmp_path) == before
    assert env.deployed() == [sha]


def test_only_switches_to_confirmed_commit_when_remote_moves(env, fake, tmp_path):
    run(env, fake, tmp_path)
    sha = env.commit()
    fake.ci[sha] = "success"
    newer = []
    fake.on_ci = lambda: newer.append(env.commit(msg="newer")) if not newer else None
    run(env, fake, tmp_path)
    assert env.head() == sha
    assert env.deployed() == [sha]
    assert newer and newer[0] != sha


@pytest.mark.parametrize("status", ["pending", "failure"])
def test_ci_not_passed_does_nothing(env, fake, tmp_path, status):
    run(env, fake, tmp_path)
    old = env.head()
    sha = env.commit()
    fake.ci[sha] = status
    run(env, fake, tmp_path)
    run(env, fake, tmp_path)
    assert env.head() == old
    assert env.deployed() == []
    assert fake.messages == []
    assert len(fake.ci_calls) == 2  # 下一輪再看
    assert log(tmp_path).count(sha[:7]) == 1  # 只記第一次停下


def test_pending_then_success_deploys_next_round(env, fake, tmp_path):
    run(env, fake, tmp_path)
    sha = env.commit()
    run(env, fake, tmp_path)
    fake.ci[sha] = "success"
    run(env, fake, tmp_path)
    assert env.deployed() == [sha]


@pytest.mark.parametrize("window,now", [
    (("11:00", "13:00"), datetime(2026, 10, 14, 12, 0)),
    (("23:00", "01:00"), datetime(2026, 10, 14, 23, 30)),
    (("23:00", "01:00"), datetime(2026, 10, 15, 0, 30)),
])
def test_blackout_blocks_then_deploys_after(env, fake, tmp_path, window, now):
    p = [env.project(blackout=window)]
    run(p, fake, tmp_path, now=now)
    sha = env.commit()
    fake.ci[sha] = "success"
    run(p, fake, tmp_path, now=now)
    assert env.deployed() == []
    run(p, fake, tmp_path, now=datetime(2026, 10, 15, 6, 0))
    assert env.deployed() == [sha]


@pytest.mark.parametrize("script", ["exit 3\n", "sleep 5\n"])
def test_update_failure_or_timeout_notifies_once_and_retries_only_new_commit(env, fake, tmp_path, script):
    run(env, fake, tmp_path)
    bad = env.commit(script)
    fake.ci[bad] = "success"
    run(env, fake, tmp_path, timeout=1)
    assert state(tmp_path)["app"]["failed"] == bad
    assert len(fake.messages) == 1
    msg = fake.messages[0]
    assert "app" in msg and bad[:7] in msg and str(tmp_path / "deploy.log") in msg
    run(env, fake, tmp_path, timeout=1)
    run(env, fake, tmp_path, timeout=1)
    assert len(fake.messages) == 1
    good = env.commit(f'git rev-parse HEAD >> "{env.marker}"\n')
    fake.ci[good] = "success"
    run(env, fake, tmp_path, timeout=1)
    assert env.deployed() == [good]
    assert state(tmp_path)["app"]["deployed"] == good


def test_dirty_clone_not_touched_and_notifies_once(env, fake, tmp_path):
    run(env, fake, tmp_path)
    old = env.head()
    (env.clone / "n.txt").write_text("local edit")
    sha = env.commit()
    fake.ci[sha] = "success"
    run(env, fake, tmp_path)
    run(env, fake, tmp_path)
    assert env.head() == old
    assert (env.clone / "n.txt").read_text() == "local edit"
    assert env.deployed() == []
    assert len(fake.messages) == 1


def test_diverged_clone_not_touched_and_notifies_once(env, fake, tmp_path):
    run(env, fake, tmp_path)
    (env.clone / "local.txt").write_text("x")
    git(env.clone, "add", "-A")
    git(env.clone, "commit", "-q", "-m", "local only")
    local = env.head()
    run(env, fake, tmp_path)  # 已有紀錄，不受影響
    sha = env.commit()
    fake.ci[sha] = "success"
    run(env, fake, tmp_path)
    run(env, fake, tmp_path)
    assert env.head() == local
    assert env.deployed() == []
    assert len(fake.messages) == 1


def test_one_project_failing_does_not_block_another(tmp_path, fake):
    a = Env(tmp_path, "a")
    b = Env(tmp_path, "b")
    projects = [a.project(), Project(name="ghost", path=tmp_path / "nope", branch="main", repo="me/ghost"), b.project()]
    run(projects, fake, tmp_path)
    sa = a.commit("exit 1\n")
    sb = b.commit()
    fake.ci[sa] = fake.ci[sb] = "success"
    run(projects, fake, tmp_path)
    assert b.deployed() == [sb]
    assert state(tmp_path)["a"]["failed"] == sa


def test_main_without_line_token_only_logs(tmp_path, monkeypatch, capsys):
    from deployer import line
    monkeypatch.setattr(line, "ENV_FILE", tmp_path / "missing-env")
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_USER_ID", raising=False)
    line.send("hello")  # 不出錯


def test_test_notify_sends_one_message(tmp_path, monkeypatch):
    from deployer import line
    sent = []
    monkeypatch.setattr(line, "send", lambda text: sent.append(text) or True)
    assert main(["--test-notify"]) == 0
    assert len(sent) == 1


def test_line_push_uses_token_and_user(tmp_path, monkeypatch):
    from deployer import line
    env_file = tmp_path / "env"
    env_file.write_text("LINE_CHANNEL_ACCESS_TOKEN=tok\nLINE_USER_ID=U123\n")
    monkeypatch.setattr(line, "ENV_FILE", env_file)
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"{}"

    def fake_urlopen(req, timeout):
        seen["auth"] = req.get_header("Authorization")
        seen["body"] = json.loads(req.data)
        return Resp()

    monkeypatch.setattr(line.urllib.request, "urlopen", fake_urlopen)
    assert line.send("hi") is True
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"to": "U123", "messages": [{"type": "text", "text": "hi"}]}


def test_ci_evaluate_rules():
    from deployer import ci
    done = lambda c: {"status": "completed", "conclusion": c}
    assert ci.evaluate([]) == "pending"
    assert ci.evaluate([done("success"), {"status": "in_progress", "conclusion": None}]) == "pending"
    assert ci.evaluate([done("success"), done("skipped"), done("neutral")]) == "success"
    assert ci.evaluate([done("success"), done("failure")]) == "failure"


def test_ci_status_gh_error_is_pending(monkeypatch):
    from deployer import ci
    monkeypatch.setenv("PATH", "/nonexistent")
    assert ci.ci_status("me/app", "abc") == "pending"


def test_error_on_first_handling_logs_and_notifies_once_then_recovers(env, fake, tmp_path):
    real = env.clone
    hidden = tmp_path / "hidden"
    real.rename(hidden)
    for _ in range(3):
        run(env, fake, tmp_path)
    assert entries(tmp_path) == 1
    assert len(fake.messages) == 1
    hidden.rename(real)
    run(env, fake, tmp_path)
    assert state(tmp_path)["app"]["deployed"] == env.head()
    assert env.deployed() == []


def test_error_after_recorded_logs_and_notifies_once(env, fake, tmp_path):
    run(env, fake, tmp_path)
    before = entries(tmp_path)
    sha = env.commit()
    fake.ci[sha] = "success"
    (env.clone / ".git" / "index.lock").write_text("")  # 快轉會一直失敗
    for _ in range(3):
        run(env, fake, tmp_path)
    assert entries(tmp_path) - before == 1
    assert len(fake.messages) == 1
