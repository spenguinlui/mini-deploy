import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Project:
    name: str
    path: Path
    branch: str
    repo: str  # GitHub 的 owner/name
    blackout: tuple[str, str] | None = None  # ("23:00", "01:00")，mini 本地時間，可跨午夜


def load_projects(path: Path) -> list[Project]:
    data = tomllib.loads(path.read_text())
    return [
        Project(
            name=p["name"],
            path=Path(p["path"]).expanduser(),
            branch=p["branch"],
            repo=p["repo"],
            blackout=tuple(p["blackout"]) if "blackout" in p else None,
        )
        for p in data["projects"]
    ]
