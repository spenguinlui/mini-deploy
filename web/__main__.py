from pathlib import Path

from deployer import load_projects
from web import make_server


ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = Path("~/Library/Application Support/mini-deploy/state.json").expanduser()
HISTORY_PATH = Path("~/Library/Application Support/mini-deploy/deploys").expanduser()


server = make_server(load_projects(ROOT / "projects.toml"), STATE_PATH, HISTORY_PATH)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
