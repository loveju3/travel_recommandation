# 旅遊商品語意搜尋推薦 Demo

用同一個畫面比較三種搜尋方式：

| 欄位 | 方法 | 說明 |
|---|---|---|
| Jieba 關鍵字 | 舊方法 baseline | Jieba 斷詞 → Postgres 全文檢索（`tsvector` + `ts_rank_cd`） |
| Embedding 向量 | 純語意 | 原始 query 的 embedding 與商品 embedding 算 cosine（pgvector） |
| Hybrid + 個人化 | 新方法 | LLM 解析條件 → SQL 過濾 → 關鍵字＋向量 RRF 融合 → 個人化與商業因素重新排序 |

在畫面左側切換使用者角色，就能看到同一個 query 對不同人排出不同結果，每筆結果也會顯示分數拆解和推薦原因。

---

## 一、快速開始（約 10 分鐘）

> Neon、OpenAI 和 `.env` 每個欄位的詳細說明、常見錯誤排除，請看 **[SETUP.md](SETUP.md)**。

### 1. 建立 Neon 專案
1. 登入 <https://console.neon.tech> → **New Project**
   - Project name：`travel-search-demo`（任意）
   - Postgres version：預設即可（16 以上）
   - Region：選 **AWS Asia Pacific (Singapore)**，離台灣最近，延遲最低
2. 建立後在專案 Dashboard 按 **Connect**，複製連線字串，格式類似：
   ```
   postgresql://neondb_owner:xxxx@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
   建議關掉 **Connection pooling** 開關，使用直連字串（匯入腳本會執行多段 DDL）。
3. 不需要手動啟用 pgvector，`ingest.py` 會自動執行 `CREATE EXTENSION IF NOT EXISTS vector;`。

### 2. 安裝與設定
> 懶人版：`./start.sh` 會自動選 Python 3.12.12（pyenv）、建 `.venv`、裝套件並啟動服務，可重複執行。第一次用新資料庫請加 `--ingest`，只建環境不啟動用 `--setup`。

```bash
cd ~/travel_recommandation
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 編輯 .env，填入 DATABASE_URL 與 OPENAI_API_KEY（資料夾裡已經有一份範本）
python scripts/check_setup.py   # 檢查 Neon、pgvector、OpenAI 是否都能連上
```

### 3. 匯入資料並產生 embedding
```bash
python scripts/ingest.py
```
這一步會建立資料表、匯入 186 筆商品、10 位使用者、20 筆訂單，並呼叫 OpenAI 產生約 400 筆 embedding（`text-embedding-3-small` 的費用不到 0.01 美元）。

> `data/*.json` 已經產生好了。如果想修改假資料，先調整 `scripts/catalog.py` 或 `scripts/generate_data.py`，執行 `python scripts/generate_data.py` 重新產生，再跑一次 `ingest.py`。

### 4. 啟動
```bash
uvicorn app.main:app --reload --port 8000
```
打開 <http://localhost:8000>。也可以用網址直接帶入 query 和使用者：`http://localhost:8000/?q=想看北極光&user=U08`

### 5. 離線評估（選用）
```bash
python scripts/eval.py            # Hybrid 使用 LLM 解析
python scripts/eval.py --no-llm   # 不使用 LLM
```
也可以在網頁的「離線評估」分頁執行。

### 沒有 API key 時
在 `.env` 設定 `EMBED_PROVIDER=fake`、`DISABLE_LLM=1`，就能完全離線跑完整流程。fake 模式使用字元 n-gram 雜湊，沒有語意能力，只能用來確認程式能跑；正式 demo 請用 OpenAI。

---

## 二、專案結構
```
├── app/
│   ├── main.py          FastAPI 路由
│   ├── search.py        三種搜尋 + RRF + 個人化 / 商業重排（核心邏輯）
│   ├── llm.py           Query 解析、推薦理由（可關閉）
│   ├── embeddings.py    OpenAI embedding（含 query 快取）
│   ├── tokenizer.py     Jieba 斷詞 + 停用詞
│   ├── evaluate.py      Recall / NDCG / MRR
│   ├── db.py, config.py
├── scripts/
│   ├── catalog.py       目的地、景點、主題素材庫
│   ├── generate_data.py 產生假資料
│   ├── ingest.py        建表、匯入、產生 embedding、計算使用者偏好向量
│   ├── eval.py          命令列評估
│   └── check_setup.py   檢查 .env、Neon、OpenAI 設定
├── SETUP.md           Neon / OpenAI / .env 設定說明
├── sql/schema.sql
├── static/index.html    前端（單一 HTML，不需要 build）
└── data/                products.json / users.json / eval_queries.json / userdict.txt
```

## 三、資料設計

**商品（186 筆）**：涵蓋 9 個區域、30 個目的地，類型包含團體旅遊、自由行、機加酒、郵輪、國內旅遊。每個目的地會搭配不同主題產生多個商品，主題包括經典、親子、蜜月、長輩慢遊、美食、季節限定（賞楓、賞櫻、雪景、滑雪、極光）、深度、奢華、小資、戶外、溫泉、購物。
- 欄位：標題、類型、地區/國家/城市、天數、價格、航空公司、出發機場、住宿等級、行程特色、每日行程、標籤、適合族群、季節、出發日期與剩餘名額、熱門度、評分
- 刻意設計了「字面對不上、語意相符」的描述，例如商品寫「銀髮族、樂齡、步調悠閒」，使用者搜尋「帶爸媽」；商品寫「歐若拉」，使用者搜尋「極光」

**使用者（10 位）**：

| ID | 角色 | 特色 |
|---|---|---|
| U01 | 王建國 63歲 | 退休夫妻、膝蓋不好、討厭購物站 → 溫泉、慢遊 |
| U02 | 林佳穎 36歲 | 帶 5 歲和 8 歲小孩 → 親子、主題樂園 |
| U03 | 陳柏翰 28歲 | 台中出發、戶外健行、冒險 |
| U04 | 張雅婷 31歲 | 新婚、高預算 → 浪漫、奢華、海島 |
| U05 | 黃志明 45歲 | 高雄出發、只能請短假、愛美食 |
| U06 | 李美華 56歲 | 退休美術老師 → 歐洲藝術深度旅行 |
| U07 | 劉宇軒 22歲 | 學生、小資、自由行 |
| U08 | 吳淑芬 42歲 | 攝影愛好者、追季節限定風景 |
| U09 | 蔡家豪 37歲 | 每年滑雪、帶 10 歲小孩 |
| U10 | 鄭小姐 | 新會員，**冷啟動**（沒有任何紀錄） |

每位使用者的資料包含：基本資料、家庭組成、會員等級、預算區間、偏好天數、慣用出發機場、旅遊風格、個人描述、訂單（含評分與評論）、收藏清單、近期搜尋。

**使用者偏好向量** = 加權平均（買過的商品 × 評分 × 時間衰減、收藏 × 0.6、近期搜尋 × 0.4、個人描述 × 0.8）

## 四、排序公式

```
最終分數 = α·相關性 + β·個人化 + γ·商業          （α β γ 可在畫面上用滑桿調整）

相關性 = 0.5·RRF(關鍵字排名, 向量排名) + 0.3·cosine + 0.2·LLM 標籤命中率
個人化 = 0.5·cos(使用者向量, 商品向量) + 0.5·規則平均
         規則：預算、天數、出發機場、家庭組成（小孩→親子、長輩→慢遊）、風格標籤
商業   = 0.5·熱門度 + 0.3·評分 + 0.2·名額急迫性；近期無可售團位 ×0.3

已購買過的商品 ×0.6；冷啟動使用者 β 自動歸 0，權重分給相關性與商業
```

LLM 解析出的條件太嚴格、結果不足時，會分階段自動放寬：先只保留目的地和類型，再完全不過濾。

---

## 五、建議的 Demo 流程（約 5 分鐘）

| # | 角色 | Query | 想展示的重點 |
|---|---|---|---|
| 1 | U01 王建國 | `帶爸媽去日本泡溫泉，不要太累` | Jieba 把句子切成「帶爸／媽去」，斷詞錯誤；向量能理解「帶爸媽」≈「長輩友善」；Hybrid 再加上無購物站、不換飯店等個人偏好 |
| 2 | U02 → U04 → U07 | `沖繩` | 同一個 query 切換角色：親子媽媽、新婚夫妻、小資學生各自排出不同結果；U04 買過的商品會被降權 |
| 3 | 任一角色 | `十萬以內的歐洲行程` | 關鍵字方法看不懂「十萬以內」；LLM 會轉成 `price ≤ 100000` 的過濾條件 |
| 4 | U05 黃志明 | `週末短天數去韓國大吃` | LLM 解析成天數 ≤ 3 和美食標籤；個人化會優先高雄出發的商品 |
| 5 | 任一角色 | `白川鄉合掌村` | 專有名詞是關鍵字的強項，純向量可能漏掉。這說明為什麼要做 Hybrid，而不是只用 embedding |
| 6 | U10 新會員 | `想看北極光` | 冷啟動：個人化權重自動轉給相關性與熱門度 |
| 7 | — | 「離線評估」分頁 | 26 組人工標註 query 的 Recall / NDCG / MRR 比較 |

綠色左框代表評估集裡人工標註為相關的商品，欄位標題會顯示「命中 x/10」。

## 六、可以在面試時延伸討論的實務議題

1. **為什麼不只用 embedding**：專有名詞、地名、商品代碼需要精準比對；RRF 不用校準兩種分數的尺度，是業界常見的做法。
2. **即時資料和語意資料要分開**：價格、出發日期、剩餘名額會一直變動，不放進 embedding，改用 SQL 過濾或在重排時計算。商品內容更新時才需要重新產生 embedding（可用 `embedding_model` 和 `updated_at` 欄位追蹤）。
3. **規模化**：商品數到數十萬筆時，HNSW 索引搭配 `WHERE` 過濾可能出現召回不足（post-filtering 問題），可以用 pgvector 0.8 的 `hnsw.iterative_scan`，或依區域做分區。
4. **成本與延遲**：query embedding 有快取；LLM 解析大約增加 0.5～1.5 秒，可以只對長 query 啟用，或改用較小的模型或 fine-tune 過的模型。Neon 閒置會自動暫停，第一次查詢會比較慢，demo 前先暖機。
5. **評估與迭代**：先用離線指標（NDCG）挑出方法，再用線上 A/B 測試看點擊率和轉換率。`search_logs` 已經記錄每次搜尋，可以用來做 Learning-to-Rank。Neon 的 branch 功能適合拿來做不同 embedding 模型的實驗。
6. **個資與公平性**：偏好向量只存在資料庫內部，不送到外部 LLM；送給 LLM 的推薦理由內容只包含必要的輪廓摘要。另外要避免個人化過度，讓使用者一直只看到同類型商品（filter bubble）。
7. **冷啟動**：新會員退回熱門度和相關性；也可以在註冊時詢問 2～3 個偏好問題，或依當次 session 的點擊即時更新偏好向量。
