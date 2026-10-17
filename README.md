# mini-deploy

Mac mini 的自動部署。mini 每 60 秒跑一輪：看各專案在 GitHub 上的分支有沒有新 commit，
那個 commit 的 CI 通過、而且不在該專案的禁止時段，就把 mini 上的 clone 快轉過去，
執行專案自己的 `deploy/update.sh`。只從 GitHub 拉，不推任何東西。監控網頁只綁
`127.0.0.1:41200`，透過 Tailscale 的 HTTPS 轉發查看，不開對外連接埠。

- CI 還沒跑完、查不到、沒過：不動，下一輪再看。
- `update.sh` 失敗或超過 30 分鐘：記為失敗、傳一次 LINE，同一個 commit 不重跑，等新 commit。
- clone 有未提交的改動或有遠端沒有的 commit：不動 clone，傳一次 LINE。
- 第一次看到某個專案：把 clone 目前的 commit 當作已部署。
- 專案設了 `lock`：快轉與執行 `update.sh` 前用該路徑建立目錄鎖；鎖被佔時每秒重試，最多等 10 分鐘，逾時記錄並傳一次 LINE。

設定在 `projects.toml`。加專案時改完並 push，PR 合進 `main` 後，在 mini 執行
`git -C ~/mini-deploy pull` 套用設定。各檔案位置：

| 東西 | 位置 |
|---|---|
| 記錄檔 | `~/Library/Logs/mini-deploy.log` |
| 每次部署的資訊與完整輸出 | `~/Library/Application Support/mini-deploy/deploys/` |
| 狀態檔（每個專案最後成功／失敗的 commit） | `~/Library/Application Support/mini-deploy/state.json` |
| LINE 權杖 | `~/.config/mini-deploy/env`（不進 repo） |

監控網頁是 `https://liumac-mini.tail93fb54.ts.net:41200/`。裝置需先連上同一個
Tailscale 私人網路；頁面只能查看，不能觸發部署或改狀態。

## 安裝到 mini

需要 Homebrew 的 `python3`（3.11 以上）和已登入的 `gh`（`gh auth status` 確認）。不用建虛擬環境。

```sh
git clone https://github.com/<owner>/mini-deploy.git ~/mini-deploy

mkdir -p ~/.config/mini-deploy
cat > ~/.config/mini-deploy/env <<'ENV'
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_USER_ID=...
ENV
chmod 600 ~/.config/mini-deploy/env

cd ~/mini-deploy && python3 -m deployer --test-notify   # 應該收到一則 LINE

cp deploy/com.liu.mini-deploy.plist ~/Library/LaunchAgents/
cp deploy/com.liu.mini-deploy-web.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.liu.mini-deploy.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.liu.mini-deploy-web.plist

# 第一次設定 Tailscale HTTPS 轉發
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg --https=41200 http://127.0.0.1:41200
```

plist 裡的路徑寫死 `/Users/liu`，mini 上的帳號不同要先改。

## 平常會用到的

```sh
tail -f ~/Library/Logs/mini-deploy.log      # 看記錄（只有事情發生時才寫）
cd ~/mini-deploy && python3 -m deployer      # 手動跑一輪
python3 -m deployer --test-notify            # 傳測試 LINE
launchctl kickstart -k gui/$(id -u)/com.liu.mini-deploy   # 叫 launchd 立刻跑一輪
launchctl kickstart -k gui/$(id -u)/com.liu.mini-deploy-web  # 更新 mini-deploy 後重啟網頁
```

## 開發

```sh
uv run pytest
```
