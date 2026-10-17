import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from deployer import Project


NOW = datetime(2026, 10, 17, 12, 0)


@pytest.fixture
def site(tmp_path):
    from history import finish_deployment, start_deployment
    from web import make_server

    projects = [
        Project("alpha", tmp_path / "alpha", "main", "me/alpha"),
        Project("beta", tmp_path / "beta", "main", "me/beta"),
        Project("gamma", tmp_path / "gamma", "main", "me/gamma"),
        Project("delta", tmp_path / "delta", "main", "me/delta"),
    ]
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "alpha": {"deployed": "abcdef012345", "failed": None, "deployed_title": "first"},
        "beta": {"deployed": "123456789abc", "failed": None, "blocked": "等 CI"},
        "gamma": {"deployed": "987654321abc", "failed": None, "blocked": "禁止時段"},
        "delta": {"deployed": "111111111abc", "failed": None, "blocked": "clone 有改動"},
    }))
    history_path = tmp_path / "deploys"
    older = start_deployment(history_path, "alpha", "abcdef012345", "first", NOW - timedelta(minutes=3))
    finish_deployment(history_path, older, "成功", NOW - timedelta(minutes=2))
    latest = start_deployment(history_path, "alpha", "fedcba987654", "second", NOW - timedelta(seconds=10))
    (history_path / f"{latest}.log").write_text("line one\nline two\n")
    server = make_server(projects, state_path, history_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield base, latest
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return response.status, response.read().decode()


def test_home_lists_projects_deployed_commit_and_current_state(site):
    base, _ = site
    status, html = get(base + "/")
    assert status == 200
    for name in ("alpha", "beta", "gamma", "delta"):
        assert name in html
    assert "abcdef0" in html and "first" in html
    assert "部署中" in html
    assert "等 CI" in html
    assert "禁止時段" in html
    assert "clone 有改動" in html


def test_project_history_is_newest_first_with_duration(site):
    base, latest = site
    status, html = get(base + "/projects/alpha")
    assert status == 200
    assert html.index("second") < html.index("first")
    assert "部署中" in html
    assert "1 分鐘" in html
    assert f"/deploys/{latest}" in html


def test_running_deployment_page_refreshes_and_preserves_log(site):
    base, latest = site
    status, html = get(base + f"/deploys/{latest}")
    assert status == 200
    assert 'http-equiv="refresh" content="3; url=/deploys/' in html
    assert "#log-end" in html
    assert "line one\nline two" in html
    assert "<pre" in html
    assert 'id="log-end"' in html


def test_pages_are_mobile_readable(site):
    base, _ = site
    _, html = get(base + "/")
    assert 'name="viewport"' in html
    assert "overflow-wrap" in html
    assert "overflow-x: auto" in html


@pytest.mark.parametrize("path", [
    "/projects/missing",
    "/deploys/999999",
    "/projects/../state.json",
    "/projects/%2e%2e%2fstate.json",
    "/deploys/%2e%2e%2fstate.json",
])
def test_missing_and_traversal_paths_return_404(site, path):
    base, _ = site
    request = urllib.request.Request(base + path)
    opener = urllib.request.build_opener(urllib.request.HTTPHandler())
    with pytest.raises(urllib.error.HTTPError) as error:
        opener.open(request, timeout=3)
    assert error.value.code == 404


def serve_home(tmp_path, state, deployments=(), now=NOW):
    """deployments：(專案, commit, 標題, 結果) ；結果 None 代表部署中。"""
    from history import finish_deployment, start_deployment
    from web import make_server

    names = list(state)
    projects = [Project(name, tmp_path / name, "main", f"me/{name}") for name in names]
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))
    history_path = tmp_path / "deploys"
    for project, commit, title, result in deployments:
        deployment_id = start_deployment(history_path, project, commit, title, now - timedelta(minutes=30))
        if result is not None:
            finish_deployment(history_path, deployment_id, result, now - timedelta(minutes=29))
    server = make_server(projects, state_path, history_path, host="127.0.0.1", port=0, now=lambda: now)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        return get(f"http://127.0.0.1:{server.server_port}/")[1], f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def card(html, name):
    start = html.index(f">{name}</a>")
    end = html.find('<section class="card">', start)
    return html[start:end if end != -1 else len(html)]


def light(html, name):
    import re
    match = re.search(r'class="light (\w+)"[^>]*>.*?</span>\s*([^<]+)<', card(html, name))
    assert match, card(html, name)
    return match.group(1), match.group(2).strip()


def deployed(sha="a" * 40, title="t", **extra):
    return {"deployed": sha, "failed": None, "deployed_title": title, **extra}


def blocked(kind, sha="b" * 40, since=NOW - timedelta(minutes=7)):
    return {"blocked": "原因文字", "blocked_kind": kind, "blocked_sha": sha, "blocked_since": since.isoformat()}


def test_home_lights_follow_priority(tmp_path):
    state = {
        "running": deployed(**blocked("attention")),
        "failed": deployed(**blocked("ci_pending")),
        "timedout": deployed(),
        "interrupted": deployed(),
        "attention": deployed(**blocked("attention")),
        "pending": deployed(**blocked("ci_pending")),
        "cifailed": deployed(**blocked("ci_failed")),
        "blackout": deployed(**blocked("blackout")),
        "remote": deployed(**blocked("remote_error", sha=None)),
        "ok": deployed(),
        "fresh": deployed(),
        "recovered": deployed(),
    }
    html, _ = serve_home(tmp_path, state, [
        ("running", "c" * 40, "x", None),
        ("failed", "c" * 40, "x", "失敗"),
        ("timedout", "c" * 40, "x", "逾時"),
        ("interrupted", "c" * 40, "x", "中斷"),
        ("ok", "a" * 40, "t", "成功"),
        ("recovered", "c" * 40, "x", "失敗"),
        ("recovered", "a" * 40, "t", "成功"),
    ])
    expected = {
        "running": ("yellow", "部署中"),
        "failed": ("red", "需要處理"),
        "timedout": ("red", "需要處理"),
        "interrupted": ("red", "需要處理"),
        "attention": ("red", "需要處理"),
        "pending": ("gray", "等待中"),
        "cifailed": ("gray", "等待中"),
        "blackout": ("gray", "等待中"),
        "remote": ("gray", "等待中"),
        "ok": ("green", "最新"),
        "fresh": ("green", "最新"),
        "recovered": ("green", "最新"),
    }
    assert {name: light(html, name) for name in state} == expected


def test_lights_ignore_blocked_text(tmp_path):
    html, _ = serve_home(tmp_path, {"app": deployed(blocked="出錯：CI 還沒有結果")})
    assert light(html, "app") == ("green", "最新")


@pytest.mark.parametrize("kind", ["ci_pending", "ci_failed"])
def test_waiting_for_ci_shows_checks_link_and_minutes(tmp_path, kind):
    html, _ = serve_home(tmp_path, {"app": deployed(**blocked(kind))})
    section = card(html, "app")
    assert f'href="https://github.com/me/app/commit/{"b" * 40}/checks"' in section
    assert "CI 進度" in section
    assert "已等 7 分鐘" in section


def test_other_waits_have_no_checks_link(tmp_path):
    html, _ = serve_home(tmp_path, {"app": deployed(**blocked("blackout"))})
    assert "CI 進度" not in html
    assert "已等" not in html


@pytest.mark.parametrize("state,deployments,refreshes", [
    ({"app": deployed(**blocked("ci_pending"))}, [], True),
    ({"app": deployed(**blocked("ci_failed"))}, [], True),
    ({"app": deployed()}, [("app", "c" * 40, "x", None)], True),
    ({"app": deployed(), "other": deployed()}, [], False),
])
def test_home_refreshes_every_5_seconds_only_while_something_is_in_progress(tmp_path, state, deployments, refreshes):
    html, _ = serve_home(tmp_path, state, deployments)
    assert ('http-equiv="refresh" content="5"' in html) is refreshes
    assert ("http-equiv" in html) is refreshes


def test_current_version_shows_title_without_any_deployment_record(tmp_path):
    html, _ = serve_home(tmp_path, {"app": deployed(sha="1234567890ab", title="initial import")})
    assert "1234567 initial import" in card(html, "app")
    assert "尚無部署標題" not in html


def test_project_and_deployment_pages_have_result_lights(site):
    import re
    base, latest = site
    _, html = get(base + "/projects/alpha")
    assert re.findall(r'class="light (\w+)"', html) == ["yellow", "green"]
    _, html = get(base + f"/deploys/{latest}")
    assert re.findall(r'class="light (\w+)"', html) == ["yellow"]


@pytest.mark.parametrize("result,color", [("成功", "green"), ("失敗", "red"), ("逾時", "red"), ("中斷", "red")])
def test_finished_deployment_page_light(tmp_path, result, color):
    import re
    from history import finish_deployment, start_deployment
    from web import make_server
    history_path = tmp_path / "deploys"
    deployment_id = start_deployment(history_path, "app", "c" * 40, "x", NOW)
    finish_deployment(history_path, deployment_id, result, NOW)
    (tmp_path / "state.json").write_text("{}")
    server = make_server([Project("app", tmp_path, "main", "me/app")], tmp_path / "state.json", history_path, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        _, html = get(f"http://127.0.0.1:{server.server_port}/deploys/{deployment_id}")
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
    assert re.findall(r'class="light (\w+)"', html) == [color]
    assert result in html
