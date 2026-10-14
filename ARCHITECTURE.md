# mini-deploy 架構

階段：0 單一功能（檢查新 commit、判斷能不能部署、呼叫專案的部署腳本）
邊界檢查：尚未需要（第二個功能出現時裝 import-linter，見 ARCHITECTURE-GUIDE.md 第 4 節）
歸屬檢查：尚未需要（跟邊界檢查一起裝，見 ARCHITECTURE-GUIDE.md 第 1 節）

## 模組

| 模組 | 路徑 | 職責（一句話） | 可以依賴 | 擁有的資料 |
|---|---|---|---|---|
| 部署器 | `deployer/` | 看各專案預設分支有沒有新 commit、CI 過了沒、在不在禁止時段，條件都符合就執行該專案的 `deploy/update.sh` | 無 | 狀態檔 `~/Library/Application Support/mini-deploy/state.json`（每個專案最後部署成功與失敗的 commit） |
| 外殼 | `projects.toml`、`deploy/`（launchd 設定檔）、`pyproject.toml`、`.github/`、`README.md` | 啟動、每分鐘排程、安裝到 mini | — | — |

## 既有違規（只准變少）

- 無。
