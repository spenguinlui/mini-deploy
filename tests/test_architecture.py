import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_import_boundaries():
    result = subprocess.run(["lint-imports"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def architecture_paths(architecture: str) -> list[str]:
    """ARCHITECTURE.md 模組表「路徑」欄裡每個用反引號標出的路徑。"""
    rows = [line for line in architecture.splitlines() if line.startswith("|")]
    column = [cell.strip() for cell in rows[0].strip("|").split("|")].index("路徑")
    return [
        path
        for row in rows[2:]
        for path in re.findall(r"`([^`]+)`", row.strip("|").split("|")[column])
    ]


def test_all_python_program_files_belong_to_an_architecture_module():
    architecture = (ROOT / "ARCHITECTURE.md").read_text()
    tracked = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    program_files = [path for path in tracked if not path.startswith("tests/")]
    module_roots = tuple(architecture_paths(architecture))
    assert "階段：1 多模組" in architecture
    assert {"deployer/", "history/", "web/"} <= set(module_roots)
    assert not [path for path in module_roots if not (ROOT / path).exists()]
    assert not [path for path in program_files if not path.startswith(module_roots)]
