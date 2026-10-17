"""部署紀錄：公開的讀寫入口都在這裡。"""

import json
from datetime import datetime
from pathlib import Path


def _record_path(root: Path, deployment_id: int) -> Path:
    return root / f"{deployment_id}.json"


def deployment_log_path(root: Path, deployment_id: int) -> Path:
    return root / f"{deployment_id}.log"


def _write(root: Path, record: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = _record_path(root, record["id"])
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    temporary.replace(path)


def start_deployment(
    root: Path,
    project: str,
    commit: str,
    title: str,
    started_at: datetime,
) -> int:
    root = Path(root)
    existing = [int(path.stem) for path in root.glob("*.json") if path.stem.isdigit()] if root.exists() else []
    deployment_id = max(existing, default=0) + 1
    _write(root, {
        "id": deployment_id,
        "project": project,
        "commit": commit,
        "title": title,
        "started_at": started_at.isoformat(),
        "ended_at": None,
        "result": "部署中",
        "error": None,
    })
    deployment_log_path(root, deployment_id).touch()
    return deployment_id


def finish_deployment(
    root: Path,
    deployment_id: int,
    result: str,
    ended_at: datetime,
    error: str | None = None,
) -> None:
    record = get_deployment(root, deployment_id)
    if record is None:
        raise FileNotFoundError(f"找不到部署紀錄 {deployment_id}")
    record.update(result=result, ended_at=ended_at.isoformat(), error=error)
    record.pop("log", None)
    _write(Path(root), record)


def get_deployment(root: Path, deployment_id: int) -> dict | None:
    root = Path(root)
    path = _record_path(root, deployment_id)
    if not path.is_file():
        return None
    record = json.loads(path.read_text())
    log_path = deployment_log_path(root, deployment_id)
    record["log"] = log_path.read_text(errors="replace") if log_path.is_file() else ""
    return record


def list_deployments(root: Path, project: str | None = None) -> list[dict]:
    root = Path(root)
    if not root.is_dir():
        return []
    records = []
    for path in root.glob("*.json"):
        if not path.stem.isdigit():
            continue
        record = get_deployment(root, int(path.stem))
        if record is not None and (project is None or record["project"] == project):
            records.append(record)
    return sorted(records, key=lambda record: record["id"], reverse=True)


def interrupt_running(root: Path, ended_at: datetime) -> None:
    for record in list_deployments(root):
        if record["result"] == "部署中":
            finish_deployment(
                root,
                record["id"],
                "中斷",
                ended_at,
                "mini-deploy 在部署完成前結束",
            )


__all__ = [
    "deployment_log_path",
    "finish_deployment",
    "get_deployment",
    "interrupt_running",
    "list_deployments",
    "start_deployment",
]
