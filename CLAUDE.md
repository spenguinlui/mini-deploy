# mini-deploy

Mac mini 的自動部署：mini 每分鐘檢查各專案預設分支有沒有新 commit，CI 通過、而且不在該專案的禁止時段，才在 mini 上執行該專案自己的部署腳本。用來取代 mini 上的 GitHub self-hosted runner，讓各專案可以轉成 public repo。

- Port 段: 41200-41209（監控網頁只綁 `127.0.0.1:41200`，經 Tailscale 查看）
- 分工: Claude 思考/驗收，實作委派 codex（規約見上層 works/CLAUDE.md）
- 生產在 mac mini（主機上 launchd 排程，不進 docker），筆電只開發。
- 本身預計公開成 public repo，repo 裡不放任何密碼。

## 定位（2026-10-14 與使用者對齊）

- **方向是 mini 自己拉**：GitHub 那邊沒有任何東西能在 mini 上執行指令。不裝 runner、不收 webhook；監控網頁只綁 localhost，經 Tailscale 查看，不開對外連接埠。
  理由：self-hosted runner 接在 public repo 上，外人可以透過 PR 夾帶 workflow 在 mini 上執行；webhook 要對外開接收端點。
- **只部署預設分支上 CI 通過的 commit**（大多數專案是 `main`，knowledge-garden 是 `v5`）。
  CI 沒過或查不到結果，就停在目前的版本不動。直接推 main 或走 PR 合併都一樣適用。
- **mini 不往 GitHub 推任何東西**，只拉。
- **部署怎麼做是各專案自己的事**：每個專案提供 `deploy/update.sh`；mini-deploy 只決定要不要跑、什麼時候跑，
  不寫任何專案專屬的部署步驟。
- CI 繼續跑在 GitHub 的主機上（public repo 免費）。

## 讀者設定（跟使用者溝通時的用詞基準）

- 業務面：一般使用者
- 開發面：初級後端工程師

這個程度的人不懂的詞，第一次出現就要解釋。提問與回報的規則見上層 `works/CLAUDE.md` 的語言標準。
