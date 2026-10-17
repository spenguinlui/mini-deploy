import argparse
from pathlib import Path

from deployer import ci, line
from deployer.config import load_projects
from deployer.cycle import run_once

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = Path("~/Library/Application Support/mini-deploy/state.json").expanduser()
LOG_PATH = Path("~/Library/Logs/mini-deploy.log").expanduser()
HISTORY_PATH = Path("~/Library/Application Support/mini-deploy/deploys").expanduser()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m deployer", description="檢查各專案並部署一輪")
    parser.add_argument("--test-notify", action="store_true", help="傳一則測試 LINE 就結束")
    args = parser.parse_args(argv)
    if args.test_notify:
        if line.send("[mini-deploy] 測試通知"):
            print("已傳出測試 LINE")
            return 0
        print(f"沒設 LINE 權杖：請在 {line.ENV_FILE} 填 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_USER_ID")
        return 1
    run_once(
        load_projects(ROOT / "projects.toml"),
        state_path=STATE_PATH,
        log_path=LOG_PATH,
        history_path=HISTORY_PATH,
        ci_status=ci.ci_status,
        notify=line.send,
    )
    return 0
