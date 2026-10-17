import subprocess
from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_import_boundaries():
    result = subprocess.run(["lint-imports"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_all_python_program_files_belong_to_an_architecture_module():
    architecture = (ROOT / "ARCHITECTURE.md").read_text()
    tracked = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    program_files = [path for path in tracked if not path.startswith("tests/")]
    module_roots = ("deployer/", "history/", "web/")
    assert "階段：1 多模組" in architecture
    for root in module_roots:
        assert f"`{root}`" in architecture
    assert not [path for path in program_files if not path.startswith(module_roots)]
