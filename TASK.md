# TASK：部署紀錄與監控網頁

## 要解決什麼問題

現在要知道部署狀況，只能 ssh 到 mini 看 `~/Library/Logs/mini-deploy.log`：五個專案混在同一個檔、
各專案 `update.sh` 的輸出也夾在裡面，看不出「現在誰在部署、在等什麼」，也沒辦法回頭看某一次部署的完整過程。
使用者要一個像 GitHub Actions 那樣的網頁：一眼看到每個專案的狀態，點進去看每次部署的過程記錄，部署中可以即時看進度。

## 做完怎麼確認（驗收條件）

**實作完成（codex）**，`uv run pytest` 全綠。先寫測試、跑到紅、貼出紅的輸出，再寫實作。沿用 `tests/test_cycle.py` 的寫法（暫存資料夾裡的真 git repo、CI 與 LINE 用替身）：

- [ ] 部署一次成功 → 紀錄資料夾多一筆，含專案名、commit、commit 標題、開始與結束時間、結果「成功」；那次 `update.sh` 的完整輸出在它自己的記錄檔裡，**不再寫進** `mini-deploy.log`。
- [ ] `update.sh` 失敗、逾時被中止 → 結果分別是「失敗」「逾時」，帶失敗原因；記錄檔保留到中止前的輸出。
- [ ] `update.sh` 執行中（測試用一個會等待的腳本）→ 那筆紀錄結果是「部署中」，記錄檔已經讀得到目前為止的輸出。
- [ ] mini-deploy 在部署中被強制結束，留下「部署中」的紀錄 → 下一輪開始時改成「中斷」。
- [ ] 部署失敗的 LINE 帶上那次部署的網頁連結（`https://liumac-mini.tail93fb54.ts.net:41200/deploys/<編號>`），不再只給記錄檔路徑。
- [ ] 網頁（用測試直接呼叫產生頁面的函式或對本機起在隨機 port 的 server 發請求）：
  - 首頁列出 `projects.toml` 的每個專案：目前已部署的 commit（前 7 碼＋標題）、最近一次部署的結果與時間、
    現在在做什麼（部署中／等 CI／禁止時段／停住的原因，取自狀態檔的 `blocked`；沒事就顯示「最新」）。
  - `/projects/<名稱>`：這個專案的部署歷史，新的在上面，每筆有結果、commit、開始時間、花了多久。
  - `/deploys/<編號>`：那次部署的資訊與完整記錄；部署中時頁面自己每 3 秒更新、捲到最底。
  - 不存在的專案或編號回 404；網址裡的名稱、編號不能讀到紀錄資料夾以外的檔案（測試 `../` 這類輸入）。
  - 頁面在手機寬度可讀（不出現橫向捲動），記錄用等寬字、保留換行。
- [ ] 裝上邊界檢查（import-linter）與歸屬檢查（每個程式檔都落在 `ARCHITECTURE.md` 模組表某一列底下），都接進 `uv run pytest`。
- [ ] `tests/test_cycle.py` 的 `test_update_failure_or_timeout_releases_lock` 在筆電忙的時候會紅（逾時只給 0.5 秒，腳本來不及寫標記檔）：改成不靠時間賽跑的寫法，用 `nice` 同時跑兩組 pytest 也穩定綠。
- [ ] push 分支、開 PR，PR 的 CI 綠。

**上線後（Claude 做）**

- [ ] mini `git -C ~/mini-deploy pull`，裝上網頁的 LaunchAgent，設好 Tailscale 轉發（`serve --bg --https=41200 http://127.0.0.1:41200`）。
- [ ] 下一次任一專案部署時，網頁上看得到它從「部署中」變成「成功」，點進去看得到完整記錄。

**使用者驗證**

1. 手機或筆電開著 Tailscale，打開 `https://liumac-mini.tail93fb54.ts.net:41200/`，看得到五個專案和各自的狀態。
2. push 任一專案到 main，等 CI 綠之後重新整理：那個專案顯示「部署中」，點進去記錄一直長出來，結束後變成「成功」。

## 動到的模組（新增兩個，階段 0 → 1）

| 模組 | 路徑 | 職責 | 可以依賴 |
|---|---|---|---|
| 部署器 | `deployer/` | 照舊；改成部署時寫紀錄、`update.sh` 輸出寫進那次的記錄檔 | 部署紀錄 |
| 部署紀錄（新） | `history/` | 每次部署一筆紀錄＋一個記錄檔的讀寫，擁有資料夾 `~/Library/Application Support/mini-deploy/deploys/` | 無 |
| 監控網頁（新） | `web/` | 唯讀網頁，讀部署紀錄與狀態檔產生頁面 | 部署紀錄、部署器（只用入口公開的讀取函式：專案清單、狀態檔） |
| 外殼 | 加上 `deploy/com.liu.mini-deploy-web.plist` | 網頁常駐（KeepAlive） | — |

## 範圍內

- `deployer/`、新的 `history/`、`web/`、`tests/`
- `deploy/com.liu.mini-deploy-web.plist`（新）、`pyproject.toml`（加 import-linter 設定與開發依賴）
- `ARCHITECTURE.md`（新模組表、階段 1、兩個檢查）、`README.md`（網頁網址、安裝方式、mini-deploy 更新後要重啟網頁）、`AGENTS.md` 與 `CLAUDE.md`（「不開連接埠／port 用不到」改成網頁只綁 127.0.0.1:41200、經 Tailscale 看）

## 範圍外（這次不准碰）

- 部署判斷規則（CI、禁止時段、鎖、快轉、30 分鐘上限）照舊；`state.json` 的欄位不改。
- 各專案的 repo、`projects.toml` 的專案內容。
- 網頁不做任何寫入操作（不能從網頁觸發部署、重跑、清狀態）。
- 不准 merge PR、不准 ssh 連 mini。

## 已裁決的分歧點

- 做一個 mini 上的網頁，不回報到 GitHub Deployments：repo 之後要公開，部署記錄可能印出主機路徑與設定 → 使用者決定（2026-10-17）。
- 網頁只綁 `127.0.0.1:41200`，經 Tailscale 的 HTTPS 轉發給使用者自己的裝置，不另做登入（跟 pikmin 地圖一樣）（Claude 決定）。
- 只用 Python 標準函式庫（`http.server`、`json`），不加網頁框架、不用資料庫：紀錄一筆一個 JSON 檔、記錄一個 `.log` 檔，編號遞增（Claude 決定）。
- 紀錄先全部保留，不自動清（Claude 決定，量大了再開 TASK）。
- `mini-deploy.log` 保留，只寫一行一則的事件（開始、成功、失敗、停住的原因），方便 ssh 時快速看（Claude 決定）。
- 頁面在伺服器端產生 HTML，部署中的頁面用 `<meta http-equiv="refresh">` 每 3 秒重新整理，不寫前端程式（Claude 決定）。
- 拆成三個模組、裝邊界與歸屬檢查：網頁是第二個功能，照 works 架構規約要升階段 1（Claude 決定）。
