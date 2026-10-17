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
        "alpha": {"deployed": "abcdef012345", "failed": None},
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
