# TiDB Unified Agent — Demo

Three demos. One database. No separate vector store, no data warehouse, no ETL pipeline.

Most "unified database" pitches show a dashboard. This shows an **agent that reasons, queries, and acts** — combining SQL joins, vector similarity search, and real-time columnar analytics — all through a single TiDB connection string.

**Demo 1 — Agent UI:** A customer asks _"Can I return my gaming laptop?"_ The agent queries order history (SQL), retrieves the return policy (vector search), and synthesises a contextual answer — while logging its full chain of thought to TiDB as persistent episodic memory.

**Demo 2 — Fraud Dashboard:** Live transactions write to TiKV every 500ms. A TiFlash HTAP query detects velocity anomalies across those same rows in real time — no ETL, no separate warehouse. Suspicious orders can be flagged directly, or investigated via the Agent UI.

**Demo 3 — Sports Betting Risk Dashboard:** Same HTAP pattern, different vertical. Two signals run simultaneously: liability concentration (risk management) and betting velocity anomalies (fraud detection). Actions write back to TiDB directly — adjust odds to rebalance a market, or flag a suspicious IP to pull its bets.

---

## How TiDB makes this possible

| TiDB capability | What it replaces | Where it appears |
|---|---|---|
| TiKV (row store) | Transactional DB | Order history, customer data, live bets, agent memory |
| TiFlash (columnar / HTAP) | Separate data warehouse | Fraud velocity, liability concentration — live against TiKV writes |
| Native Vector / HNSW index | Separate vector database | Product search, policy retrieval |
| Unified SQL interface | Multiple connection strings | One driver, one port (4000), all capabilities |
| Transactional write-back | Application-level orchestration | `flag_order`, `adjust_odds`, `flag_bettor` — agent and dashboard write directly |

**The core talking point:** Both the fraud velocity query and the betting liability query use `/*+ read_from_storage(tiflash[...]) */` to aggregate across the columnar engine while the live pulse is simultaneously inserting rows into TiKV. Same data, same database, no synchronisation lag. No Flink, no Kafka, no enrichment pipeline.

---

## Architecture

```
User Question
     │
     ▼
┌─────────────────────────────────────┐
│         LLM Orchestration           │  ← decides which tool to call
└─────────────────────────────────────┘
     │               │
     ▼               ▼
execute_sql()   vector_search()        ← agent_tools.py
     │               │
     └───────┬───────┘
             ▼
    ┌─────────────────┐
    │  TiDB Serverless │
    │                 │
    │  TiKV  TiFlash  │  ← same DB, two engines
    │  Vector Index   │
    └─────────────────┘
             │
             ▼
   log_interaction()                   ← saves agent "thoughts" to chat_history
```

---

## Prerequisites

- Python 3.9+
- A [TiDB Starter](https://tidbcloud.com) cluster (free tier works)
- The `isrgrootx1.pem` SSL certificate (download from your TiDB Cloud connection details)

**Install dependencies:**

```bash
pip install mysql-connector-python sentence-transformers python-dotenv faker streamlit altair pandas
```

---

## Setup

### 1. Configure credentials

Copy the example env file and fill in your TiDB Cloud connection details:

```bash
cp .env.example .env
```

Edit `.env`:

```
TIDB_HOST=gateway01.<region>.prod.aws.tidbcloud.com
TIDB_PORT=4000
TIDB_USER=<your-prefix>.root
TIDB_PASSWORD=<your-password>
TIDB_DATABASE=test
TIDB_SSL_CA=/path/to/isrgrootx1.pem
```

> Your connection details are in the TiDB Cloud console under **Connect → Python**.

### 2. Create the schema

In your TiDB Cloud SQL Editor, run `schema.sql`.

This creates all tables in one step:
- `customers`, `orders`, `products` — relational tables with TiFlash replicas
- `sales_knowledge` — vector knowledge base with HNSW index
- `agent_sessions`, `chat_history` — episodic memory tables
- `reviews` — product and service reviews with sentiment scores and vector embeddings
- `betting_events`, `bets` — sports betting tables with TiFlash replicas

### 3. Seed the demo data

Run these in order from the project root:

```bash
# Step 1: Generate 100 customers, 6 products with vector embeddings, 3 policies, 500 orders
python generate_world.py

# Step 2: Create the demo persona (VIP customer used by the Agent UI)
python execution/seed_demo_data.py

# Step 3: Add order history for the demo persona
python execution/seed_orders.py

# Step 4: Seed product and service reviews with sentiment scores and vector embeddings
python execution/seed_reviews.py

# Step 5: Inject fraud scenarios for the Fraud Dashboard
python execution/seed_fraud_data.py
```

> `generate_world.py` and `seed_reviews.py` each take ~30 seconds — they run local embedding inference to generate vector data.

**Optional — Sports Betting Demo:**
```bash
# schema.sql already includes the betting tables — no extra schema step needed.
python execution/seed_betting_data.py
```

> `seed_betting_data.py` is idempotent — safe to re-run, it clears and reseeds each time.

---

## Running the demos

### Demo 1 — Agent UI (primary demo)

```bash
python3 -m streamlit run execution/agent_ui.py
```

A chat interface with a live **Agent Memory** sidebar showing the chain of thought.

**Switch roles** in the sidebar to see two perspectives:

**As "Customer (Bernard)" — try asking:**
- `"Can I return my gaming laptop?"`
  - *Shows: SQL to find purchase date + vector search to retrieve the 14-day return policy → synthesised answer*
- `"What headphones do you have?"`
  - *Shows: semantic product search via vector index*
- `"What's the shipping policy for VIP customers?"`
  - *Shows: vector search against the sales_knowledge table*

**As "Admin" — try asking:**
- `"Give me a business overview"`
  - *Shows: HTAP aggregate query across customers, orders, products*
- `"Show me recent orders"`
  - *Shows: multi-table JOIN query*
- `"What do customers think about the gaming laptop?"`
  - *Shows: vector search on the `reviews` table — semantic similarity against review embeddings*
- `"Give me a sentiment overview across all products"`
  - *Shows: `get_review_analytics()` — TiFlash HTAP aggregation of sentiment scores, per-product ratings, 7-day trend, and recent negative reviews. No separate ML pipeline — sentiment scores are stored alongside the operational data in TiDB.*
- `"Which products have the most negative reviews?"`
  - *Shows: HTAP columnar scan + sentiment aggregation in one query*

Watch the sidebar update in real time — the agent logs its full reasoning to `chat_history` in TiDB on every turn.

---

### Demo 2 — Fraud Dashboard (HTAP showcase)

Open two terminals.

**Terminal 1** — stream live transactions:
```bash
python live_pulse.py
```

**Terminal 2** — run the dashboard:
```bash
streamlit run execution/fraud_dashboard.py
```

The dashboard auto-refreshes every 2 seconds and shows:
- **Active Alerts** — orders flagged as suspicious
- **Revenue at Risk** — dollar value of pending/flagged orders
- **Velocity Anomalies** — IPs with 3+ transactions in 24h (the TiFlash HTAP query)
- **Live Risk Queue** — the real-time transaction feed

Use the **"Investigate with Agent →"** button to open the Agent UI and ask questions like _"why is order #42 suspicious?"_ or _"flag order #42"_ — demonstrating the same write-back capability through natural language.

**The talking point:** The velocity query uses `/*+ read_from_storage(tiflash[orders]) */` to hit the columnar engine for real-time analytics on data that is *simultaneously* being written transactionally. No ETL, no separate data warehouse.

---

### Demo 3 — Sports Betting Risk Dashboard (HTAP — alternate vertical)

Same TiDB HTAP pattern as the Fraud Dashboard, applied to sportsbook risk and fraud management. Two signals, two actions — all writing back directly to TiDB.

Open two terminals.

**Terminal 1** — stream live bets:
```bash
python live_betting_pulse.py
```

**Terminal 2** — run the dashboard:
```bash
streamlit run execution/sports_betting_dashboard.py --server.port 8003
```

The dashboard auto-refreshes every 2 seconds and shows:

**Risk signal — Liability Concentration:**
Events where 65%+ of stakes are on one side. Action: **📉 Adjust Odds** — reduces the overloaded selection's odds by 12% and increases the opposing side by 8%. Market stays open.

**Fraud signal — Betting Velocity Anomalies:**
IPs with 5+ bets in 24 hours. Signals multi-accounting, arbitrage bots, or coordinated activity. Action: **🚩 Flag Account** — moves all accepted bets from that IP to flagged status for review.

**The talking point:** Ververica solves this with Flink + a separate enrichment store to combine streaming data with historical context. TiDB does it in one query — the same database holds the live bet stream (TiKV) and the historical context for enrichment (TiFlash). Two HTAP queries, two write-back actions, one connection string.

**Vertical:** Gaming, gambling operators.

---

### Demo 4 — CLI Agent (optional / for developers)

```bash
python execution/run_agent.py
```

A terminal version of the agent loop — useful for showing raw chain-of-thought output without the UI layer.

---

## File structure

```
Agent_AG/
├── agent_tools.py          # All agent tools: SQL, vector, fraud, betting write-backs
├── agent_state.py          # StateManager — session and history management
├── generate_world.py       # Seeds the full database (run once)
├── schema.sql              # Full TiDB schema: all tables, TiFlash replicas, HNSW vector indexes
├── live_pulse.py           # Streams live orders every 500ms (fraud demo)
├── live_betting_pulse.py   # Streams live bets every 500ms (sports betting demo)
├── .env.example            # Credential template
│
├── execution/
│   ├── agent_ui.py               # Demo 1 — Streamlit chat UI with agent memory sidebar
│   ├── fraud_dashboard.py        # Demo 2 — Real-time fraud monitor
│   ├── sports_betting_dashboard.py  # Demo 3 — Betting risk and fraud monitor
│   ├── run_agent.py              # Demo 4 — CLI agent loop
│   ├── seed_demo_data.py         # Creates the demo persona (Bernard)
│   ├── seed_orders.py            # Adds order history for the demo persona
│   ├── seed_reviews.py           # Seeds product + service reviews with sentiment scores and embeddings
│   ├── seed_fraud_data.py        # Injects fraud scenarios for Demo 2
│   ├── seed_betting_data.py      # Seeds betting events and scenarios for Demo 3
│   └── apply_fraud_schema.py     # Schema migration helper (run if needed)
│
└── directives/
    └── tidb_agent_demo.md        # Agent persona and operating instructions
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `SSL connection error` | Check `TIDB_SSL_CA` path in `.env` points to the downloaded `isrgrootx1.pem` |
| `No results found` for customer queries | Run `seed_demo_data.py` and `seed_orders.py` |
| `No velocity anomalies` on Fraud Dashboard | Run `seed_fraud_data.py` to inject fraud scenarios |
| `No liability concentration` on Betting Dashboard | Run `seed_betting_data.py` to inject betting scenarios |
| `No velocity anomalies` on Betting Dashboard | Run `seed_betting_data.py` — seeds the IP burst scenario |
| `No results` for sentiment/review queries | Run `seed_reviews.py` — seeds product and service reviews with embeddings |
| `TOKENIZERS_PARALLELISM` warning | Already handled in `agent_ui.py` — safe to ignore |
| TiFlash query falls back to TiKV | TiFlash replica sync takes ~1 min after schema creation — wait and retry |
