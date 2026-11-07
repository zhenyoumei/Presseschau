# Presseschau · 德國報紙每日導覽

每天早上自動整理 **FAZ、SZ、DIE ZEIT、DER SPIEGEL、FOCUS** 的新聞，產生一個德中對照的網頁：

- **今日頭條**：每家報紙的前幾則重要新聞
- **多家報紙共同報導**：自動找出好幾家報紙都在報的同一件事，方便比較各報怎麼下標題
- **主題分類**：德國政治、國際、經濟、文化・藝文、科學・教育、社會
- 德文標題與導言，下面附繁體中文機器翻譯；可以切換「中文」「導言」顯示，也可以只看某幾家報紙
- 每天的頁面自動存檔（「存檔 Archiv」）

完全免費：程式在 GitHub Actions 上執行，網頁放在 GitHub Pages，翻譯用 Google Translate 的免費介面。

---

## 第一次設定（約 15 分鐘）

### 1. 建立 GitHub 帳號
到 <https://github.com> 註冊（已經有帳號可以跳過）。

### 2. 建立一個新的 repository（存放程式的地方）
1. 右上角「＋」→ **New repository**
2. Repository name 填：`presseschau`
3. 選 **Public**（免費帳號的 GitHub Pages 需要公開；網頁上只有新聞標題、導言和連結）
4. 其他選項都不用勾 → **Create repository**

### 3. 上傳程式檔案
1. 在新 repository 的頁面點 **uploading an existing file**
2. 把這四個檔案拖進去：`build.py`、`feeds.toml`、`requirements.txt`、`README.md`
3. 按下方綠色 **Commit changes**

### 4. 建立自動排程檔
`.github` 是隱藏資料夾，用拖的常常傳不上去，所以改用手動建立：
1. 在 repository 頁面點 **Add file → Create new file**
2. 檔名欄位輸入：`.github/workflows/presseschau.yml`（打到 `/` 時會自動變成資料夾）
3. 打開附上的 `presseschau.yml`，全部複製後貼到內容區
4. 按 **Commit changes**

### 5. 先手動執行一次
1. 點上方 **Actions** 分頁（如果出現提示，按「I understand my workflows, go ahead and enable them」）
2. 左邊點 **Tägliche Presseschau** → 右邊 **Run workflow** → 再按綠色 **Run workflow**
3. 約 1～3 分鐘後出現綠色勾勾 ✓ 就表示成功了

> 如果出現紅色 ✗，而且錯誤訊息有 `permission denied` 或 `403`：
> 到 **Settings → Actions → General → Workflow permissions**，選 **Read and write permissions** → Save，再執行一次。

### 6. 開啟網頁
1. **Settings → Pages**
2. Source 選 **Deploy from a branch**
3. Branch 選 **main**，資料夾選 **/docs** → **Save**
4. 等 1～2 分鐘，頁面上方會出現網址，格式是：
   `https://您的帳號.github.io/presseschau/`

把網址加入書籤，或在手機瀏覽器選「加入主畫面」，用起來就跟 App 一樣。

---

## 之後
- 每天**台灣時間 06:23 左右**自動更新（GitHub 的排程有時會晚 10～30 分鐘）。
- 網頁最下方的「來源狀態」會列出每個 RSS 是否讀取成功。出現 ✗ 時，表示報社改了網址，到 `feeds.toml` 換掉即可。

## 自己調整
所有設定都在 `feeds.toml`，在 GitHub 網頁上點檔案 → 右上角鉛筆圖示就能編輯：

| 想改的事 | 怎麼改 |
|---|---|
| 頭條、各主題要幾則 | `top_items_per_paper`、`items_per_feed` |
| 不要中文翻譯 | `translate = false` |
| 加一家報紙（例如 Tagesspiegel、taz、NZZ） | 複製一段 `[[papers]]`，填上它的 RSS 網址 |
| 不要某個主題 | 刪掉那段 `[[topics]]` |

**更新時間**改在 `.github/workflows/presseschau.yml` 的 `cron: "23 22 * * *"`。時間是 UTC，台灣時間減 8 小時：例如想要早上 07:30，就寫 `"30 23 * * *"`。

## 注意
- 中文是機器翻譯，專有名詞和雙關語標題常常翻得不準，請以德文為準。
- 「多家報紙共同報導」是用關鍵字比對，偶爾會把不相干的新聞放在一起，或漏掉某些新聞。
- 標題與導言的著作權屬於各報社。點標題可以閱讀原文，部分為付費內容。
