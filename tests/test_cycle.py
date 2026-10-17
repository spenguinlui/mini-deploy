import json
import shlex
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from deployer import Project, load_projects, main, run_once

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

    def project(self, blackout=None, lock=None):
        return Project(
            name=self.name,
            path=self.clone,
            branch="main",
            repo=f"me/{self.name}",
            blackout=blackout,
            lock=lock,
        )


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def fake():
    return Fake()


def run(env_or_projects, fake, tmp_path, now=NOON, timeout=1800, lock_timeout=600):
    projects = env_or_projects if isinstance(env_or_projects, list) else [env_or_projects.project()]
    run_once(
        projects,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "deploy.log",
        history_path=tmp_path / "deploys",
        ci_status=fake.ci_status,
        notify=fake.notify,
        now=lambda: now,
        timeout=timeout,
        lock_timeout=lock_timeout,
    )


def state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


def entries(tmp_path):
    import re
    return len(re.findall(r"^\d{4}-\d\d-\d\d ", log(tmp_path), re.M))


def log(tmp_path):
    p = tmp_path / "deploy.log"
    return p.read_text() if p.exists() else ""


def test_projects_config_includes_knowledge_garden_lock():
    projects = load_projects(Path(__file__).parent.parent / "projects.toml")
    assert [project.name for project in projects] == ["rent_house", "knowledge-garden", "stock_commentary", "self-profile", "pikmin"]
    assert projects[0].lock is None
    assert projects[1].lock == Path("/tmp/kb-inbox.lock")


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


def test_lock_is_held_while_updating_and_released_afterwards(env, fake, tmp_path):
    lock = tmp_path / "app.lock"
    project = env.project(lock=lock)
    run([project], fake, tmp_path)
    script = (
        f'test -d {shlex.quote(str(lock))}\n'
        f'git rev-parse HEAD >> {shlex.quote(str(env.marker))}\n'
    )
    sha = env.commit(script)
    fake.ci[sha] = "success"

    run([project], fake, tmp_path)

    assert env.head() == sha
    assert env.deployed() == [sha]
    assert not lock.exists()


def test_waits_for_an_existing_lock_before_fast_forwarding(env, fake, tmp_path):
    lock = tmp_path / "app.lock"
    project = env.project(lock=lock)
    run([project], fake, tmp_path)
    old = env.head()
    sha = env.commit()
    fake.ci[sha] = "success"
    lock.mkdir()

    thread = threading.Thread(
        target=run,
        args=([project], fake, tmp_path),
        kwargs={"lock_timeout": 0.3},
    )
    thread.start()
    threading.Event().wait(0.05)
    assert thread.is_alive()
    assert env.head() == old
    assert env.deployed() == []

    lock.rmdir()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert env.head() == sha
    assert env.deployed() == [sha]
    assert not lock.exists()


def test_lock_timeout_stops_once_without_touching_someone_elses_lock(env, fake, tmp_path):
    lock = tmp_path / "app.lock"
    owner_file = lock / "owner"
    project = env.project(lock=lock)
    run([project], fake, tmp_path)
    old = env.head()
    before = entries(tmp_path)
    sha = env.commit()
    fake.ci[sha] = "success"
    lock.mkdir()
    owner_file.write_text("keep me")

    run([project], fake, tmp_path, lock_timeout=0.01)
    run([project], fake, tmp_path, lock_timeout=0.01)

    assert env.head() == old
    assert env.deployed() == []
    assert entries(tmp_path) - before == 1
    assert len(fake.messages) == 1
    assert "鎖" in fake.messages[0]
    assert owner_file.read_text() == "keep me"

    owner_file.unlink()
    lock.rmdir()
    run([project], fake, tmp_path, lock_timeout=0.01)
    assert env.head() == sha
    assert env.deployed() == [sha]
    assert not lock.exists()


# 失敗那組用預設的 30 分鐘上限：腳本自己結束，結果不受筆電快慢影響；
# 逾時那組的腳本永遠不寫標記檔，什麼時候被中止都一樣
@pytest.mark.parametrize("script,timeout,expects_marker", [
    ('test -d "$LOCK" && echo locked > "$MARKER"; exit 3\n', 1800, True),
    ('sleep 30\n', 0.1, False),
])
def test_update_failure_or_timeout_releases_lock(env, fake, tmp_path, script, timeout, expects_marker):
    lock = tmp_path / "app.lock"
    project = env.project(lock=lock)
    run([project], fake, tmp_path)
    script = script.replace("$LOCK", str(lock)).replace("$MARKER", str(env.marker))
    sha = env.commit(script)
    fake.ci[sha] = "success"

    run([project], fake, tmp_path, timeout=timeout)

    assert env.marker.exists() is expects_marker
    assert state(tmp_path)["app"]["failed"] == sha
    assert not lock.exists()


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
    assert "app" in msg and bad[:7] in msg
    assert "https://liumac-mini.tail93fb54.ts.net:41200/deploys/1" in msg
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


def deployment_records(tmp_path):
    from history import get_deployment, list_deployments
    root = tmp_path / "deploys"
    return [get_deployment(root, record["id"]) for record in list_deployments(root)]


def test_deployment_list_leaves_out_log_and_single_record_reads_it(env, fake, tmp_path):
    from history import get_deployment, list_deployments
    run(env, fake, tmp_path)
    sha = env.commit('echo "output"\n')
    fake.ci[sha] = "success"

    run(env, fake, tmp_path)

    listed = list_deployments(tmp_path / "deploys")
    assert len(listed) == 1
    assert "log" not in listed[0]
    assert get_deployment(tmp_path / "deploys", listed[0]["id"])["log"] == "output\n"


def test_successful_deployment_has_own_complete_record_and_log(env, fake, tmp_path):
    run(env, fake, tmp_path)
    sha = env.commit('echo "first line"\necho "last line"\n', msg="ship feature")
    fake.ci[sha] = "success"

    run(env, fake, tmp_path)

    records = deployment_records(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record["project"] == "app"
    assert record["commit"] == sha
    assert record["title"] == "ship feature"
    assert record["started_at"]
    assert record["ended_at"]
    assert record["result"] == "成功"
    assert record["error"] is None
    assert record["log"] == "first line\nlast line\n"
    assert "first line" not in log(tmp_path)
    assert "last line" not in log(tmp_path)


@pytest.mark.parametrize(
    "script,timeout,result,error_text,output",
    [
        ('echo "before failure"; exit 7\n', 1, "失敗", "結束代碼 7", "before failure\n"),
        ('echo "before timeout"; sleep 5\n', 2, "逾時", "超過", "before timeout\n"),
    ],
)
def test_failed_and_timed_out_deployments_keep_output(
    env, fake, tmp_path, script, timeout, result, error_text, output
):
    run(env, fake, tmp_path)
    sha = env.commit(script)
    fake.ci[sha] = "success"

    run(env, fake, tmp_path, timeout=timeout)

    record = deployment_records(tmp_path)[0]
    assert record["result"] == result
    assert error_text in record["error"]
    assert record["log"] == output


def test_running_deployment_is_visible_with_current_output(env, fake, tmp_path):
    run(env, fake, tmp_path)
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    sha = env.commit(
        f'echo "working"\ntouch {shlex.quote(str(ready))}\n'
        f'while test ! -e {shlex.quote(str(release))}; do sleep 0.05; done\n'
    )
    fake.ci[sha] = "success"
    thread = threading.Thread(target=run, args=(env, fake, tmp_path), kwargs={"timeout": 10})
    thread.start()
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        threading.Event().wait(0.01)

    record = deployment_records(tmp_path)[0]
    assert record["result"] == "部署中"
    assert record["ended_at"] is None
    assert record["log"] == "working\n"

    release.touch()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_next_round_marks_leftover_running_deployment_interrupted(env, fake, tmp_path):
    from history import start_deployment

    start_deployment(
        tmp_path / "deploys",
        project="app",
        commit="a" * 40,
        title="unfinished",
        started_at=NOON,
    )

    run(env, fake, tmp_path)

    record = deployment_records(tmp_path)[0]
    assert record["result"] == "中斷"
    assert record["ended_at"]
    assert record["error"] == "mini-deploy 在部署完成前結束"


def blocked_fields(tmp_path):
    s = state(tmp_path)["app"]
    return s.get("blocked_kind"), s.get("blocked_sha"), s.get("blocked_since")


def test_waiting_for_ci_records_kind_commit_and_since_until_deployed(env, fake, tmp_path):
    from datetime import timedelta
    run(env, fake, tmp_path)
    sha = env.commit()

    run(env, fake, tmp_path)
    assert blocked_fields(tmp_path) == ("ci_pending", sha, NOON.isoformat())
    run(env, fake, tmp_path, now=NOON + timedelta(minutes=5))
    assert blocked_fields(tmp_path) == ("ci_pending", sha, NOON.isoformat())

    fake.ci[sha] = "failure"
    later = NOON + timedelta(minutes=8)
    run(env, fake, tmp_path, now=later)
    assert blocked_fields(tmp_path) == ("ci_failed", sha, later.isoformat())

    fake.ci[sha] = "success"
    run(env, fake, tmp_path)
    assert blocked_fields(tmp_path) == (None, None, None)
    assert "blocked" not in state(tmp_path)["app"]


def test_blackout_kind(env, fake, tmp_path):
    project = env.project(blackout=("11:00", "13:00"))
    run([project], fake, tmp_path)
    sha = env.commit()
    run([project], fake, tmp_path)
    assert blocked_fields(tmp_path) == ("blackout", sha, NOON.isoformat())


def test_dirty_clone_is_attention(env, fake, tmp_path):
    run(env, fake, tmp_path)
    sha = env.commit()
    fake.ci[sha] = "success"
    (env.clone / "n.txt").write_text("local edit")
    run(env, fake, tmp_path)
    assert blocked_fields(tmp_path) == ("attention", sha, NOON.isoformat())


def test_missing_remote_branch_is_remote_error(env, fake, tmp_path):
    run(env, fake, tmp_path)
    git(env.clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    run(env, fake, tmp_path)
    kind, sha, since = blocked_fields(tmp_path)
    assert (kind, sha, since) == ("remote_error", None, NOON.isoformat())


def test_error_is_attention(env, fake, tmp_path):
    run(env, fake, tmp_path)
    sha = env.commit()

    def boom():
        raise RuntimeError("boom")

    fake.on_ci = boom
    run(env, fake, tmp_path)
    assert blocked_fields(tmp_path)[0] == "attention"


def test_deployed_title_recorded_first_time_after_deploy_and_backfilled(env, fake, tmp_path):
    run(env, fake, tmp_path)
    assert state(tmp_path)["app"]["deployed_title"] == "c"

    sha = env.commit(msg="ship feature")
    fake.ci[sha] = "success"
    run(env, fake, tmp_path)
    assert state(tmp_path)["app"]["deployed_title"] == "ship feature"

    old = state(tmp_path)
    del old["app"]["deployed_title"]
    (tmp_path / "state.json").write_text(json.dumps(old))
    run(env, fake, tmp_path)
    assert state(tmp_path)["app"]["deployed_title"] == "ship feature"
