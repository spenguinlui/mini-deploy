"""唯讀監控網頁：公開的伺服器入口都在這裡。"""

import html
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from deployer import Project, read_state
from history import get_deployment, list_deployments


STYLE = """
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 960px; padding: 1rem; font: 16px/1.5 system-ui, sans-serif; color: #202124; }
a { color: #0759b7; }
h1 { font-size: 1.6rem; }
.card { border: 1px solid #d8dce3; border-radius: 10px; margin: 0 0 1rem; padding: 1rem; overflow-wrap: anywhere; }
.meta { color: #5f6368; }
.status { font-weight: 700; }
pre { background: #15171a; color: #f4f4f4; border-radius: 8px; padding: 1rem; overflow-x: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
@media (max-width: 600px) { body { padding: .75rem; } .card { padding: .75rem; } }
"""


def _page(title: str, body: str, refresh: str = "") -> bytes:
    refresh_tag = f'<meta http-equiv="refresh" content="{html.escape(refresh, quote=True)}">' if refresh else ""
    return (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{refresh_tag}<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body>{body}</body></html>"
    ).encode()


def _time(value: str | None) -> str:
    if not value:
        return "—"
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")


def _duration(record: dict) -> str:
    if not record["ended_at"]:
        return "部署中"
    seconds = max(0, int((datetime.fromisoformat(record["ended_at"]) - datetime.fromisoformat(record["started_at"])).total_seconds()))
    if seconds >= 60:
        minutes, remainder = divmod(seconds, 60)
        return f"{minutes} 分鐘" + (f" {remainder} 秒" if remainder else "")
    return f"{seconds} 秒"


def _commit_label(commit: str | None, title: str | None) -> str:
    if not commit:
        return "尚無紀錄"
    return f"{commit[:7]} {title or '（尚無部署標題）'}"


def _home(projects: list[Project], state: dict, records: list[dict]) -> bytes:
    cards = []
    for project in projects:
        project_state = state.get(project.name, {})
        deployed = project_state.get("deployed")
        deployed_record = next((r for r in records if r["project"] == project.name and r["commit"] == deployed and r["result"] == "成功"), None)
        latest = next((r for r in records if r["project"] == project.name), None)
        current = "部署中" if latest and latest["result"] == "部署中" else project_state.get("blocked", "最新")
        recent = f'{latest["result"]} · {_time(latest["started_at"])}' if latest else "尚無部署紀錄"
        cards.append(
            '<section class="card">'
            f'<h2><a href="/projects/{html.escape(project.name, quote=True)}">{html.escape(project.name)}</a></h2>'
            f'<div>目前版本：{html.escape(_commit_label(deployed, deployed_record["title"] if deployed_record else None))}</div>'
            f'<div>最近部署：{html.escape(recent)}</div>'
            f'<div class="status">現在：{html.escape(current)}</div></section>'
        )
    return _page("mini-deploy", "<h1>mini-deploy</h1>" + "".join(cards))


def _project_page(project: Project, records: list[dict]) -> bytes:
    cards = []
    for record in records:
        cards.append(
            '<section class="card">'
            f'<div class="status">{html.escape(record["result"])}</div>'
            f'<a href="/deploys/{record["id"]}#log-end">{html.escape(_commit_label(record["commit"], record["title"]))}</a>'
            f'<div class="meta">開始：{html.escape(_time(record["started_at"]))} · 花費：{html.escape(_duration(record))}</div>'
            "</section>"
        )
    body = f'<p><a href="/">← 所有專案</a></p><h1>{html.escape(project.name)}</h1>' + ("".join(cards) or "<p>尚無部署紀錄</p>")
    return _page(project.name, body)


def _deployment_page(record: dict) -> bytes:
    error = f'<p>原因：{html.escape(record["error"])}</p>' if record["error"] else ""
    body = (
        f'<p><a href="/projects/{html.escape(record["project"], quote=True)}">← {html.escape(record["project"])}</a></p>'
        f'<h1>部署 #{record["id"]}</h1><section class="card">'
        f'<div class="status">{html.escape(record["result"])}</div>'
        f'<div>commit：{html.escape(_commit_label(record["commit"], record["title"]))}</div>'
        f'<div>開始：{html.escape(_time(record["started_at"]))}</div>'
        f'<div>結束：{html.escape(_time(record["ended_at"]))}</div>{error}</section>'
        f'<pre>{html.escape(record["log"])}</pre><span id="log-end" tabindex="0" autofocus></span>'
    )
    refresh = f'3; url=/deploys/{record["id"]}#log-end' if record["result"] == "部署中" else ""
    return _page(f'部署 #{record["id"]}', body, refresh)


def make_server(
    projects: list[Project],
    state_path: Path,
    history_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 41200,
) -> ThreadingHTTPServer:
    project_by_name = {project.name: project for project in projects}
    state_path = Path(state_path)
    history_path = Path(history_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            content = None
            if path == "/":
                content = _home(projects, read_state(state_path), list_deployments(history_path))
            else:
                match = re.fullmatch(r"/projects/([^/]+)", path)
                if match and match.group(1) in project_by_name:
                    project = project_by_name[match.group(1)]
                    content = _project_page(project, list_deployments(history_path, project.name))
                match = re.fullmatch(r"/deploys/([0-9]+)", path) if content is None else None
                if match:
                    record = get_deployment(history_path, int(match.group(1)))
                    if record is not None:
                        content = _deployment_page(record)
            if content is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


__all__ = ["make_server"]
