# 環境設定說明：Neon、OpenAI 與 `.env`

所有設定都放在專案根目錄的 `.env`。`.env` 已列在 `.gitignore`，不會被 commit，API key 不會外流。

```
travel_recommandation/
├── .env            ← 你要填的設定檔（不進版控）
├── .env.example    ← 範本（會進版控）
└── ...
```

---

## 步驟 1：建立 Neon 資料庫，取得 `DATABASE_URL`

1. 登入 <https://console.neon.tech>
2. 按 **New Project**
   | 欄位 | 建議值 |
   |---|---|
   | Project name | `travel-search-demo` |
   | Postgres version | 預設（16 / 17 都可以） |
   | Region | **AWS Asia Pacific (Singapore)**（離台灣最近） |
   | Database name | 預設的 `neondb` 即可 |
3. 建立完成後，在專案 Dashboard 右上角按 **Connect**
4. 在彈出視窗：
   - Branch：`main`
   - Database：`neondb`
   - Role：`neondb_owner`
   - **Connection pooling 開關請關掉**，使用直連字串（匯入腳本會一次執行多段 DDL，直連比較穩定）
5. 複製連線字串，格式如下：
   ```
   postgresql://neondb_owner:密碼@ep-xxxx-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
   - 結尾一定要有 `?sslmode=require`
   - 如果字串裡有 `&channel_binding=require`，保留也沒關係
6. **pgvector 不需要手動安裝**。`scripts/ingest.py` 會自動執行 `CREATE EXTENSION IF NOT EXISTS vector;`。想先手動確認的話，可以在 Neon 的 **SQL Editor** 執行同一行。

> Neon 免費方案閒置約 5 分鐘後會自動暫停（scale to zero），下一次查詢要多花約 0.5～1 秒喚醒。面試前先打開頁面搜一兩次暖機。

---

## 步驟 2：取得 OpenAI API key

1. 到 <https://platform.openai.com/api-keys> → **Create new secret key**
2. 複製 `sk-...` 開頭的 key，它只會顯示一次
3. 確認帳號在 **Billing** 頁面有餘額。這個 demo 的費用很低：
   - 匯入時產生約 400 筆 embedding：遠低於 0.01 美元
   - 每次搜尋：1 次 embedding，加上最多 2 次小模型呼叫（解析＋推薦理由）
4. 如果你的組織有限制可用的模型，到 **Settings → Limits / Projects** 確認 `text-embedding-3-small` 和你要用的對話模型都有開放

---

## 步驟 3：填寫 `.env`

資料夾裡已經放好一份 `.env`（內容和 `.env.example` 相同），直接改裡面的值即可：

```dotenv
# ── 資料庫 ─────────────────────────────
DATABASE_URL=postgresql://neondb_owner:密碼@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require

# ── OpenAI ─────────────────────────────
OPENAI_API_KEY=sk-proj-xxxxxxxx

# Embedding 設定
EMBED_PROVIDER=openai                 # openai＝正式；fake＝離線測試（沒有語意能力）
EMBED_MODEL=text-embedding-3-small    # 可改成 text-embedding-3-large（效果較好、較貴）
EMBED_DIM=1536                        # 向量維度，要和資料表一致

# 對話模型：query 解析、推薦理由
CHAT_MODEL=gpt-4o-mini                # 帳號不能用這個模型時，換成你可用的小模型

# 設成 1 會整體關閉 LLM；搜尋仍可運作，只是不做 query 解析與推薦理由
DISABLE_LLM=0
```

### 各欄位說明

| 變數 | 必填 | 說明 |
|---|---|---|
| `DATABASE_URL` | ✅ | Neon 連線字串（步驟 1） |
| `OPENAI_API_KEY` | ✅ | OpenAI 金鑰（步驟 2）。沒有的話只能用 fake 模式 |
| `EMBED_PROVIDER` | | `openai`（預設）或 `fake` |
| `EMBED_MODEL` | | 預設 `text-embedding-3-small` |
| `EMBED_DIM` | | 預設 `1536`。`text-embedding-3-*` 系列支援縮短維度，例如設成 `512` 可以省空間，但要重新執行 `ingest.py` |
| `CHAT_MODEL` | | 預設 `gpt-4o-mini` |
| `DISABLE_LLM` | | `1` 會關閉所有 LLM 功能 |

> **換 embedding 模型或維度之後，一定要重跑 `python scripts/ingest.py`。** 這個腳本會重建資料表，並重新產生所有向量。查詢向量和商品向量必須來自同一個模型、同一個維度，否則比對結果沒有意義。

---

## 步驟 4：安裝、檢查、匯入、啟動

```bash
cd ~/travel_recommandation

# 建立虛擬環境（擇一）
python3 -m venv .venv && source .venv/bin/activate
# 或 conda create -n travel-demo python=3.11 -y && conda activate travel-demo

pip install -r requirements.txt

# ① 檢查設定：會依序測 .env、Neon、pgvector、Embedding、對話模型
python scripts/check_setup.py

# ② 建表＋匯入資料＋產生 embedding（約 30 秒）
python scripts/ingest.py

# ③ 啟動
uvicorn app.main:app --reload --port 8000
```

打開 <http://localhost:8000>，右上角兩個標籤應該顯示：
- `Embedding：openai / text-embedding-3-small`
- 綠色的 `LLM gpt-4o-mini`

④ 選用：跑離線評估，把指標放進簡報
```bash
python scripts/eval.py
```

---

## 常見問題

| 狀況 | 原因 / 解法 |
|---|---|
| `connection ... timeout` / `could not translate host name` | 連線字串貼錯，或公司網路擋住 5432 port。改用手機熱點試試看 |
| `SSL connection is required` | 連線字串結尾少了 `?sslmode=require` |
| `password authentication failed` | 密碼錯誤：在 Neon 的 **Roles** 頁面重設密碼，再重新複製連線字串 |
| `extension "vector" is not available` | 很少發生。到 Neon SQL Editor 手動執行 `CREATE EXTENSION vector;` |
| `openai.AuthenticationError` | API key 錯誤或已被刪除 |
| `openai.RateLimitError` / `insufficient_quota` | 帳號沒有餘額，到 Billing 儲值 |
| `model_not_found` | 帳號不能用這個模型：修改 `CHAT_MODEL` 或 `EMBED_MODEL` |
| `expected 1536 dimensions, not 512` | 改過 `EMBED_DIM` 但沒重跑 `ingest.py` |
| 網頁右上角顯示「LLM 未啟用」 | `.env` 沒有讀到 `OPENAI_API_KEY`，或 `DISABLE_LLM=1`。改完 `.env` 要重啟 uvicorn |
| Apple Silicon 上 `psycopg` 安裝失敗 | `requirements.txt` 用的是 `psycopg[binary]`，通常不會失敗；如果還是失敗，先 `pip install --upgrade pip` 再裝一次 |

## 安全提醒
- 不要把 `.env` commit 到 git，也不要貼在截圖或簡報上
- demo 結束後，如果擔心外流，可以到 OpenAI 刪除這把 key，或到 Neon 重設資料庫密碼
