# mini-deploy 架構

階段：1 多模組
邊界檢查：`uv run lint-imports`（已接進 `uv run pytest`）
歸屬檢查：`tests/test_architecture.py`（不檢查的路徑：`tests/`）

## 模組

| 模組 | 路徑 | 職責（一句話） | 可以依賴 | 擁有的資料 |
|---|---|---|---|---|
| 部署器 | `deployer/` | 看各專案預設分支有沒有新 commit、CI 過了沒、在不在禁止時段，條件都符合就執行該專案的 `deploy/update.sh` | 部署紀錄 | 狀態檔 `~/Library/Application Support/mini-deploy/state.json`（每個專案最後部署成功與失敗的 commit） |
| 部署紀錄 | `history/` | 每次部署一筆紀錄，保存部署資訊與完整輸出 | 無 | `~/Library/Application Support/mini-deploy/deploys/` |
| 監控網頁 | `web/` | 唯讀顯示專案狀態、部署歷史與每次部署的完整記錄 | 部署紀錄、部署器（只用公開入口） | — |
| 外殼 | `projects.toml`、`deploy/`（launchd 設定檔）、`pyproject.toml`、`.github/`、`README.md` | 啟動、每分鐘排程、安裝到 mini | — | — |

## 既有違規（只准變少）

- 無。
