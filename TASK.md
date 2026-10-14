# TASK: 第一版：rent_house 的 main 有新 commit、CI 通過，mini 就自動上線

## 要解決什麼問題
mini 上的專案現在要嘛手動 ssh 部署，要嘛靠 GitHub self-hosted runner，而 runner 不能接 public repo。第一版只接 rent_house，從頭到尾跑通：mini 自己發現新版本、確認 CI 通過、上線，失敗時傳 LINE。

## 做完怎麼確認（驗收條件）
自動測試 `uv run pytest` 全綠。用暫存資料夾裡的真 git repo 當「GitHub 上的 repo」和「mini 上的 clone」；CI 查詢、LINE、時鐘用替身，不連網：
- [ ] 遠端分支有新 commit、CI 通過、不在禁止時段 → clone 快轉到那個 commit，執行專案根目錄的 `deploy/update.sh`，記為已部署
- [ ] 確認 CI 之後、切換之前，遠端又多了新 commit → 只切到確認過的那個
- [ ] CI 還在跑、還沒有任何檢查結果、或查詢失敗（網路、`gh` 出錯）→ 不切換、不執行、不通知，下一輪再看
- [ ] CI 沒過 → 不部署、不通知（GitHub 自己會寄信）
- [ ] 落在該專案的禁止時段（支援跨午夜，例如 23:00–01:00；用 mini 的本地時間）→ 不部署；時段一過，下一輪就部署
- [ ] `update.sh` 失敗或超過 30 分鐘 → 記為這個 commit 失敗、傳一次 LINE（內容有專案名、commit 前 7 碼、記錄檔路徑）；之後每一輪都不重跑同一個 commit、不重複通知；遠端出現新 commit 才再試
- [ ] clone 有未提交的改動，或有遠端沒有的 commit（不能快轉）→ 不動 clone、不執行，傳一次 LINE
- [ ] 第一次處理某個專案（還沒有任何紀錄）→ 把 clone 目前的 commit 當作已部署，不重新部署
- [ ] 一個專案出錯，不影響同一輪其他專案（測試放兩個專案）
- [ ] 沒設 LINE 權杖 → 只寫記錄檔，不出錯
- [ ] 記錄檔只在有事發生時寫（開始部署、成功、失敗、某個原因第一次讓它停下），沒事的那幾輪不寫
- [ ] `python3 -m deployer --test-notify` 傳一則測試 LINE
- [ ] mini-deploy 自己的 CI（`.github/workflows/ci.yml`，GitHub 主機跑 pytest）綠

（Claude 做）上線驗證：
- [ ] mini-deploy 開成 public repo（打開「合併後自動刪分支」）；mini 上 clone 到 `~/mini-deploy`；LINE 權杖放 `~/.config/mini-deploy/env`（權限 600）；裝 LaunchAgent，每 60 秒跑一輪
- [ ] `--test-notify` 在 mini 上跑一次，使用者收到 LINE
- [ ] rent_house 的 TASK 合進 main、CI 綠之後 5 分鐘內：mini 的 `~/rent_house` 切到那個 commit，三個服務重啟（`launchctl list | grep rent-house` 的 PID 變了），記錄檔有成功那一行，`https://rent.wayne-liu.com` 正常

## 動到的模組
- 部署器 `deployer/`
- 外殼：`projects.toml`、`deploy/`（launchd 設定檔）、`pyproject.toml`、`.github/`、`README.md`
- `ARCHITECTURE.md`：部署器「擁有的資料」改成狀態檔，外殼列出上面這些路徑

## 範圍內
- `deployer/`：檢查、判斷、切換、執行、記錄、LINE 通知；入口 `python3 -m deployer`（跑一輪就結束，由 launchd 每 60 秒叫一次）
- `projects.toml`（只放 rent_house）、`deploy/com.liu.mini-deploy.plist`、`README.md`（做什麼、怎麼裝、看記錄、手動跑一輪、測試通知）
- `.github/workflows/ci.yml`、`ARCHITECTURE.md`

## 範圍外（這次不准碰）
- 其他專案（stock_commentary、knowledge-garden…）的接入與 runner 拆除
- mini-deploy 自我更新
- 寫回 GitHub（commit 狀態、留言）、webhook、任何對外 port
- 暫停開關、重試指令、狀態網頁
- rent_house repo 的任何檔案（另一個 TASK 在做）

## 已裁決的分歧點
- 上線前要手動做事的版本 → 使用者裁決：不做暫停開關，各專案自己寫進部署腳本
- 失敗通知 → 使用者裁決：LINE，跟 knowledge-garden 備份失敗用同一個機器人，只通知失敗
- repo → 使用者裁決：現在就開 public
- 只用 Python 標準函式庫，mini 上用 Homebrew 的 `python3` 直接跑、不建虛擬環境；pytest 只是開發依賴（Claude 決定：mini 上少一樣要維護的東西）
- 每輪的做法（Claude 決定）：
  - `git ls-remote` 看遠端分支（不走 API、沒有次數限制）；遠端 commit 跟紀錄不同才查 CI
  - CI：`gh api repos/<owner>/<repo>/commits/<sha>/check-runs`，全部完成、結論都是 success／skipped／neutral 才算通過；一個都沒有算還沒跑
  - 切換：`git fetch` 後 `git merge --ff-only <sha>`，切到確認過的那個 commit
  - 部署指令固定是專案根目錄的 `deploy/update.sh`
  - 一輪內各專案依序處理（launchd 不會同時起兩輪）
- 狀態檔 `~/Library/Application Support/mini-deploy/state.json`，每個專案記最後部署成功與失敗的 commit（Claude 決定：`update.sh` 失敗時 clone 已經切過去了，只看 clone 分不出成功還是失敗）
- 設定檔 `projects.toml` 放 repo 裡，每個專案寫名稱、mini 上的路徑、分支、GitHub repo（owner/name）、禁止時段（可省略）（Claude 決定：加專案就是改設定再 push，有歷史可查）
- 記錄檔 `~/Library/Logs/mini-deploy.log`；LINE 權杖從 `~/.config/mini-deploy/env` 讀 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID`，不進 repo
