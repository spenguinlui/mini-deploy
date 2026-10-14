import os
import signal
import subprocess
from pathlib import Path


def run_update(path: Path, log_path: Path, timeout: float) -> str | None:
    """執行專案的 deploy/update.sh，輸出接到記錄檔。成功回 None，失敗回原因。"""
    with open(log_path, "a") as log:
        try:
            proc = subprocess.Popen(
                ["deploy/update.sh"], cwd=path, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as e:
            return f"無法執行 deploy/update.sh：{e}"
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return f"超過 {int(timeout)} 秒沒結束，已中止"
    return None if code == 0 else f"結束代碼 {code}"
