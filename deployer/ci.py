import json
import subprocess

PASSED = {"success", "skipped", "neutral"}


def evaluate(check_runs: list[dict]) -> str:
    """回傳 success / failure / pending。一個檢查都沒有算還沒跑。"""
    if not check_runs or any(r["status"] != "completed" for r in check_runs):
        return "pending"
    return "success" if all(r["conclusion"] in PASSED for r in check_runs) else "failure"


def ci_status(repo: str, sha: str) -> str:
    """查不到（網路、gh 出錯）一律當 pending，下一輪再看。"""
    try:
        out = subprocess.run(
            ["gh", "api", "--paginate", "--jq", ".check_runs[]",
             f"repos/{repo}/commits/{sha}/check-runs"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "pending"
    return evaluate([json.loads(line) for line in out.splitlines() if line.strip()])
