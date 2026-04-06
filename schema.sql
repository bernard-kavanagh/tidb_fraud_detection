
-- **Instructions:**
-- 1. Save this code block as `schema.sql`.
-- 2. Open your TiDB Cloud Console.
-- 3. Import or copy-paste this entire block into the SQL Editor and run it.


/*
   TiDB Schema for Antigravity Agent Demo
   --------------------------------------
   Purpose: Supports a Sales Engineering Agent capable of:
   1. Real-time Analytics (HTAP)
   2. Semantic Search (Vector)
   3. Stateful Conversation (Episodic Memory)
*/

-- ==========================================
-- 1. FACT MEMORY (Relational Data)
-- ==========================================

-- Customers: Who are we selling to?
CREATE TABLE IF NOT EXISTS customers (
    customer_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100),
    region VARCHAR(50), -- e.g., 'EMEA', 'NA', 'APAC'
    vip_status BOOLEAN DEFAULT FALSE,
    signup_date DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Products: The catalog with Vector Embeddings for Semantic Search
-- Note: VECTOR(384) matches the 'all-MiniLM-L6-v2' model output
CREATE TABLE IF NOT EXISTS products (
    product_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10, 2),
    description TEXT, 
    embedding VECTOR(384) 
);

-- Orders: The Transactional Link (Fact Table)
CREATE TABLE IF NOT EXISTS orders (
    order_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT,
    product_id INT,
    quantity INT,
    amount DECIMAL(10,2),
    ip_address VARCHAR(45),
    country VARCHAR(50),
    status ENUM('pending', 'flagged', 'cleared', 'fraudulent') DEFAULT 'pending',
    flagged_reason TEXT,
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- ==========================================
-- 2. SEMANTIC MEMORY (Knowledge Base)
-- ==========================================

-- Sales Knowledge: Business rules and policies for RAG
CREATE TABLE IF NOT EXISTS sales_knowledge (
    doc_id INT AUTO_INCREMENT PRIMARY KEY,
    content TEXT,        -- e.g., "Gaming Laptops have a 14-day return limit."
    category VARCHAR(50), -- e.g., 'Returns', 'Shipping'
    embedding VECTOR(384),
    metadata JSON        -- e.g., {"priority": "high", "tags": ["laptop", "strict"]}
);

-- ==========================================
-- 3. EPISODIC MEMORY (Agent State)
-- ==========================================

-- Sessions: Tracks distinct user conversations
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id VARCHAR(36) PRIMARY KEY, -- UUID
    user_id VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    metadata JSON -- Flexible context like {"sentiment": "positive"}
);

-- Chat History: The "Black Box" recorder for Root Cause Analysis (RCA)
CREATE TABLE IF NOT EXISTS chat_history (
    message_id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36),
    role ENUM('user', 'assistant', 'system', 'tool'), 
    content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata JSON, -- Stores tool usage: {"tool": "Vector Search"}
    FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id)
);

-- ==========================================
-- 4. OPTIMIZATIONS (The "Secret Sauce")
-- ==========================================

/* 
   A. Enable TiFlash (HTAP) 
   This pushes data to the Columnar Engine for real-time analytics 
   and accelerates Vector Search scans.
*/
ALTER TABLE customers SET TIFLASH REPLICA 1;
ALTER TABLE products SET TIFLASH REPLICA 1;
ALTER TABLE orders SET TIFLASH REPLICA 1;
ALTER TABLE sales_knowledge SET TIFLASH REPLICA 1;
ALTER TABLE chat_history SET TIFLASH REPLICA 1; -- Enables analytics on user questions

/* 
   B. Create Vector Indexes (HNSW)
   This enables Approximate Nearest Neighbor (ANN) search for low latency.
   Note: Without this, vector search is a full table scan (slower but accurate).
*/
-- Index for Product Catalog
ALTER TABLE products DROP INDEX IF EXISTS idx_prod_embedding;
ALTER TABLE products ADD VECTOR INDEX idx_prod_embedding ((VEC_L2_DISTANCE(embedding)));

-- Index for Knowledge Base
ALTER TABLE sales_knowledge DROP INDEX IF EXISTS idx_know_embedding;
ALTER TABLE sales_knowledge ADD VECTOR INDEX idx_know_embedding ((VEC_L2_DISTANCE(embedding)));

-- ==========================================
-- 5. REVIEWS (Operational ML Data)
-- ==========================================

/*
   Stores product and service reviews written by customers.
   - Sentiment score + label pre-computed at write time (simulates edge inference)
   - Embedding enables semantic search: "find reviews mentioning slow delivery"
   - TiFlash replica enables real-time aggregate analytics (AVG rating, sentiment trend)
     directly on operational data — no ETL, no data warehouse needed.
*/
CREATE TABLE IF NOT EXISTS reviews (
    review_id   INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    product_id  INT NULL,                         -- NULL for service/experience reviews
    review_type ENUM('product', 'service') DEFAULT 'product',
    rating      TINYINT NOT NULL,                 -- 1–5 stars
    review_text TEXT NOT NULL,
    sentiment_score DECIMAL(4,3),                 -- -1.000 (very negative) → 1.000 (very positive)
    sentiment_label ENUM('positive', 'neutral', 'negative'),
    embedding   VECTOR(384),                      -- for semantic search on review content
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id)  REFERENCES products(product_id)
);

ALTER TABLE reviews SET TIFLASH REPLICA 1;

ALTER TABLE reviews DROP INDEX IF EXISTS idx_review_embedding;
ALTER TABLE reviews ADD VECTOR INDEX idx_review_embedding ((VEC_L2_DISTANCE(embedding)));

