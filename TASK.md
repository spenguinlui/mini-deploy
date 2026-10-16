# TASK: 部署前先拿專案的鎖，並接上 knowledge-garden

## 要解決什麼問題
knowledge-garden 要改由 mini-deploy 部署。它在 mini 上有一支每 60 秒跑一輪的排程（收錄筆記、建站），
每一輪開始時建一個目錄 `/tmp/kb-inbox.lock` 當作鎖（目錄建得出來就算拿到，跑完刪掉；鎖在就不跑這一輪）。
現在的 mini-deploy 不看這把鎖，可能在那一輪建站建到一半時換掉程式碼，結果是新舊混雜的網站，
或那一輪當掉、發一則「收錄程式異常結束」的 LINE。原本的部署腳本會等這把鎖放掉才拉程式碼，改用 mini-deploy 不能少了這層保護。

## 做完怎麼確認（驗收條件）
`uv run pytest` 全綠。新測試沿用既有寫法（暫存資料夾裡的真 git repo，CI、LINE、時鐘用替身），鎖用暫存資料夾裡的目錄：
- [ ] 專案設了 `lock`、鎖沒人拿 → 照常部署；`update.sh` 執行當下鎖目錄存在（腳本自己檢查並寫進檔案）；部署完鎖目錄不見
- [ ] 鎖被別人拿著、等待途中被放掉 → 放掉之前 clone 的 commit 不變、`update.sh` 沒跑；放掉之後部署完成
- [ ] 鎖一直被拿著，超過等待上限 → clone 的 commit 不變、`update.sh` 沒跑；記錄檔寫一次、LINE 傳一次，
      下一輪還是等不到也不重複；別人的鎖目錄和裡面的檔案原封不動；鎖放掉後的下一輪照常部署
- [ ] `update.sh` 失敗、超過時間被停掉 → 鎖一樣會放掉
- [ ] 沒設 `lock` 的專案行為不變（既有測試全綠，不准改既有測試的預期）
- [ ] 測試不真的等 10 分鐘：等待上限由 `run_once` 的參數帶入，測試給小的值
- [ ] `uv run python -c "from pathlib import Path; from deployer.config import load_projects; print(load_projects(Path('projects.toml')))"`
      印出 rent_house 與 knowledge-garden 兩個專案，knowledge-garden 的鎖是 `/tmp/kb-inbox.lock`
- [ ] GitHub 上這個 PR 的 CI 綠

## 動到的模組
- 部署器 `deployer/`、外殼（`projects.toml`、`README.md`）

## 範圍內
- `deployer/config.py`、`deployer/cycle.py`（需要的話新檔 `deployer/lock.py`）、`tests/`
- `projects.toml`：開頭說明加 `lock`；新增 knowledge-garden（path `~/knowledge-garden`、branch `v5`、repo `spenguinlui/knowledge-garden`、lock `/tmp/kb-inbox.lock`）
- `README.md`：說明 `lock`；「加專案就是改它再 push」改成實際做法（push 合進 main 後，在 mini 跑 `git -C ~/mini-deploy pull`）

## 範圍外（這次不准碰）
- `deploy/com.liu.mini-deploy.plist`、`.github/`、`deployer/ci.py`、`deployer/line.py`、`deployer/runner.py`
- `update.sh` 30 分鐘上限、狀態檔 `state.json` 的欄位
- 其他種類的鎖（例如 rent_house 排程用的 lockf 檔案鎖）；rent_house 那一段不加 `lock`
- 不准 merge PR、不准 ssh 連 mini

## 已裁決的分歧點
- 鎖只在「快轉到新 commit＋執行 `update.sh`」這段拿著；查 CI、`git fetch` 不拿（fetch 不動工作目錄）（Claude 決定）
- 鎖被佔就等：每秒試一次，最多 10 分鐘。不用「這輪先跳過、下一輪再試」：兩支排程都是每 60 秒一輪，
  開始的時間點可能一直撞在一起，結果永遠部署不到（Claude 決定）
- 等不到算一次停下，走既有的 `stop()`（同一個原因只記一次），要傳 LINE：等 10 分鐘還拿不到，
  多半是鎖沒被清掉（例如程式被強制結束），那時收錄也一起停了，要有人去看（Claude 決定）
- 等的時候同一輪後面的專案跟著等（一輪本來就依序處理），最多晚 10 分鐘，可以接受（Claude 決定）
- 只刪自己建的鎖；鎖只支援「建目錄」這一種，因為 knowledge-garden 用的就是這種（Claude 決定）
- mini-deploy 不部署自己，改完由 Claude 到 mini 手動 pull（Claude 決定）
