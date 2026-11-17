-- 旅遊商品語意搜尋 Demo：資料表結構（Neon Postgres + pgvector）
-- 向量維度預設 1536（OpenAI text-embedding-3-small），ingest.py 會依 EMBED_DIM 自動替換。

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS search_logs, orders, users, products CASCADE;

-- 旅遊商品
CREATE TABLE products (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    product_type      TEXT NOT NULL,          -- 團體旅遊 / 自由行 / 機加酒 / 郵輪 / 國內旅遊
    region            TEXT NOT NULL,          -- 日本 / 韓國 / 東南亞 / 歐洲 ...
    country           TEXT NOT NULL,
    cities            TEXT[] NOT NULL,
    days              INT NOT NULL,
    price             INT NOT NULL,           -- 起價（新台幣）
    airline           TEXT,
    departure_airport TEXT,                   -- TPE / KHH / RMQ / 台北車站 ...
    hotel_level       TEXT,
    highlights        TEXT[],
    itinerary         JSONB,                  -- [{day, title, content}]
    tags              TEXT[],
    suitable_for      TEXT[],
    seasons           TEXT[],
    departures        JSONB,                  -- [{date, price, seats_left}]  ← 即時資料，不放進 embedding
    popularity        REAL,
    rating            REAL,
    review_count      INT,
    description       TEXT,
    -- 搜尋用欄位
    doc_summary       TEXT,                   -- 給 embedding 的摘要文字
    doc_itinerary     TEXT,                   -- 給 embedding 的每日行程文字
    jieba_tokens      TEXT,                   -- Jieba 斷詞結果（空白分隔），舊方法 baseline 用
    tsv               TSVECTOR,               -- 全文檢索索引（title 權重 A、標籤/特色 B、其餘 C）
    emb_summary       vector(1536),
    emb_itinerary     vector(1536),
    embedding_model   TEXT,
    updated_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX products_tsv_idx  ON products USING GIN (tsv);
CREATE INDEX products_tags_idx ON products USING GIN (tags);
CREATE INDEX products_emb_summary_hnsw   ON products USING hnsw (emb_summary vector_cosine_ops);
CREATE INDEX products_emb_itinerary_hnsw ON products USING hnsw (emb_itinerary vector_cosine_ops);

-- 使用者
CREATE TABLE users (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    age              INT,
    gender           TEXT,
    city             TEXT,
    home_airport     TEXT,
    household        TEXT,                    -- 家庭組成：有幼兒 / 帶長輩 / 新婚 ...
    member_tier      TEXT,
    budget_min       INT,
    budget_max       INT,
    preferred_days   INT[],                   -- [最短, 最長]
    styles           TEXT[],                  -- 旅遊風格標籤
    note             TEXT,
    recent_searches  TEXT[],                  -- 隱性偏好
    wishlist         TEXT[],                  -- 收藏的商品 id
    profile_emb      vector(1536),            -- 使用者偏好向量（由消費紀錄＋收藏＋搜尋加權平均）
    profile_updated_at TIMESTAMPTZ
);

-- 訂單（消費紀錄）
CREATE TABLE orders (
    order_id        TEXT PRIMARY KEY,
    user_id         TEXT REFERENCES users(id),
    product_id      TEXT REFERENCES products(id),
    departure_date  DATE,
    pax             INT,
    amount          INT,
    rating          INT,
    review          TEXT
);
CREATE INDEX orders_user_idx ON orders(user_id);

-- 搜尋紀錄（之後可用於點擊率分析、Learning to Rank）
CREATE TABLE search_logs (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT,
    query       TEXT,
    params      JSONB,
    parsed      JSONB,
    result_ids  JSONB,
    timings_ms  JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);
