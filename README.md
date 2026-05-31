# TiDB Fraud Detection — Cognitive Foundation for Fintech

Adaptive fraud detection with three-tier memory, substrate-driven model routing, and live custodial duties on a single TiDB cluster. No vector store, no warehouse, no ETL pipeline.

This repo is one of three implementations of the **cognitive foundation** architecture. The same memory substrate runs [industrial IoT](https://github.com/bernard-kavanagh/ev_charger_anomaly_detection) and [database operations](https://github.com/bernard-kavanagh/tidb-self-healing-db-agent); here it's adapted to e-commerce transactions and sports betting via [`adapters/fraud/`](adapters/fraud/__init__.py) and [`adapters/betting/`](adapters/betting/__init__.py).

> **For the architecture deep-dive — three-tier memory, custodial duties, the four-step lifecycle, what's shipped vs POC — see [ARCHITECTURE.md](ARCHITECTURE.md).**

---

## The demos

**Demo 1 — Fraud Dashboard (HTAP, 30-second hook).** Live transactions write to TiKV every 500 ms. A TiFlash columnar query detects velocity anomalies across those same rows in real time. One database. No ETL.

**Demo 2 — Agent UI (the cognitive foundation in action).** Two flows in one interface — a customer RAG path (vector search + Haiku) and an admin investigation path (5-tier context assembly → substrate-driven routing → tool-use loop → structured checkpoint). Every stage streams into the chain-of-thought sidebar.

**Demo 3 — Sports Betting Dashboard (same substrate, different vertical).** Same HTAP pattern, applied to sportsbook risk and fraud — liability concentration and betting-velocity anomalies, with adjust-odds and flag-bettor write-backs. Proves the adapter pattern: same code, different domain catalog.

A CLI version of the cognitive-foundation investigation loop (`python execution/betting_investigation.py "<trigger>" [entity_ref]`) is available for raw tool-trace output without the Streamlit layer.

---

## What TiDB replaces here

| TiDB capability | What it replaces | Where it appears |
|---|---|---|
| TiKV (row store) | Transactional DB | Order history, customer data, live bets, agent memory |
| TiFlash (columnar / HTAP) | Separate data warehouse | Fraud velocity, liability concentration — live against TiKV writes |
| Native Vector / HNSW index | Separate vector database | Product search, policy retrieval, fraud_memory |
| Unified SQL interface | Multiple connection strings | One driver, one port (4000), all capabilities |
| Transactional write-back | Application-level orchestration | `flag_order`, `adjust_odds`, `flag_bettor` write directly |

The fraud-velocity query and the betting-liability query both use `/*+ read_from_storage(tiflash[...]) */` to aggregate across the columnar engine while the live pulse is *simultaneously* inserting rows into TiKV. Same data, same database, no sync lag. No Flink, no Kafka, no enrichment store.

---

## Prerequisites

- Python 3.10+
- A [TiDB Cloud Starter](https://tidbcloud.com) cluster (free tier works)
- The `isrgrootx1.pem` SSL certificate — available in the Connect dialog under **Connection Type → General → CA certificate**

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Pinned set: `mysql-connector-python>=8.3,<9`, `sentence-transformers>=2.7,<3`, `python-dotenv>=1.0,<2`, `faker>=24,<26`, `streamlit>=1.30,<2`, `altair>=5,<6`, `pandas>=2.0,<3`, `anthropic>=0.30,<1`.

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your TiDB Cloud details (under **Connect → Python** in the console):

```
TIDB_HOST=gateway01.<region>.prod.aws.tidbcloud.com
TIDB_PORT=4000
TIDB_USER=<your-prefix>.root
TIDB_PASSWORD=<your-password>
TIDB_DATABASE=test
TIDB_SSL_CA=/path/to/isrgrootx1.pem
ANTHROPIC_API_KEY=sk-ant-...
```

> Starter and Dedicated clusters use slightly different host patterns — copy whatever the Connect dialog shows.

### 3. Create the schema

In the TiDB Cloud console, open your cluster → **SQL Editor** → paste `schema.sql` → run.

This creates all tables in one step, including `fraud_memory` (vector-indexed semantic memory) and `agent_reasoning` (structured episodic checkpoints). The schema file is idempotent — safe to re-run.

### 4. Seed the demo data

```bash
# Generate 100 customers, 6 products with embeddings, 3 policies, 500 orders (~30s)
python generate_world.py

# The demo persona (VIP customer used by the Agent UI)
python execution/seed_demo_data.py

# Order history for the demo persona
python execution/seed_orders.py

# Product/service reviews with sentiment scores and embeddings (~30s)
python execution/seed_reviews.py

# Fraud scenarios for the Fraud Dashboard
python execution/seed_fraud_data.py

# Optional — sports betting scenarios (schema already includes betting tables)
python execution/seed_betting_data.py
```

All seed scripts are idempotent.

---

## Running the demos

> **Two-terminal demos:** Demo 1 and Demo 3 stream live data in one terminal and serve a dashboard in another. The pulse terminal must stay running while the dashboard serves.

### Demo 1 — Fraud Dashboard

**Terminal 1** — live transactions:
```bash
python live_pulse.py
```

**Terminal 2** — dashboard:
```bash
streamlit run execution/fraud_dashboard.py
```

The dashboard auto-refreshes every 2 seconds:
- **Active Alerts** — orders flagged as suspicious
- **Revenue at Risk** — dollar value of pending/flagged orders
- **Velocity Anomalies** — IPs with 3+ transactions in 24h (TiFlash query)
- **Live Risk Queue** — the real-time transaction feed

The **"Investigate with Agent →"** button opens the Agent UI for natural-language drill-down.

### Demo 2 — Agent UI

```bash
python3 -m streamlit run execution/agent_ui.py
```

Switch roles in the sidebar to see two contrasting memory shapes.

**As "Customer (Bernard)" — the RAG path:**
- `"Can I return my gaming laptop?"` — SQL for purchase date + vector search for return policy → synthesised answer
- `"What headphones do you have?"` — semantic product search via vector index
- `"What's the shipping policy for VIP customers?"` — vector search against `sales_knowledge`

**As "Admin" — the cognitive-foundation path:**
- `"Give me a business overview"` — HTAP aggregate across customers, orders, products
- `"What do customers think about the gaming laptop?"` — vector search on the `reviews` table
- `"Give me a sentiment overview across all products"` — TiFlash sentiment aggregation, no separate ML pipeline

For admin investigations, see the **demo triggers** below — these point at IPs and customers that actually exist in the seed data.

### Demo 3 — Sports Betting Dashboard

**Terminal 1** — live bets:
```bash
python live_betting_pulse.py
```

**Terminal 2** — dashboard:
```bash
streamlit run execution/sports_betting_dashboard.py --server.port 8003
```

Two signals refresh every 2 seconds:
- **Liability Concentration** — events with 65%+ stake on one side. Action: **📉 Adjust Odds** reduces the overloaded side by 12% and increases the opposing side by 8%
- **Betting Velocity Anomalies** — IPs with 5+ bets in 24 hours. Action: **🚩 Flag Account** moves all accepted bets from that IP to flagged status

### Demo 4 (optional) — CLI Investigation

```bash
python execution/betting_investigation.py "<trigger text>" [entity_ref]
```

Terminal version of the cognitive-foundation investigation loop. Same lifecycle as the Admin path in Demo 2 (assemble → route → tool-use → slim summary), no UI. Useful for showing raw tool-trace output or scripting investigations against the betting adapter. Pass an entity_ref (customer_id or IP) for the full Tier 4 prior-investigations lookup.

---

## Known-good demo triggers

> ⚠️ **Important:** Querying an IP or customer that isn't in the seed data leaves the agent with nothing to verify on the SHORTCUT path and produces a fallback summary at 0.50 confidence. Use the triggers below for reliable demos.

| Vertical | Trigger (paste into Admin chat or CLI) | Expected path |
|---|---|---|
| Fraud — velocity burst | `investigate suspicious orders from IP 185.15.54.22` | SHORTCUT once warm (5 pending orders seeded) |
| Fraud — headless bot | `investigate orders with Puppeteer or Playwright user agents` | EXPLORE first time, SHORTCUT after compound |
| Fraud — chargeback fraud | `investigate customer 4 for chargeback fraud` | EXPLORE — agent finds Clayton Knight's 6 chargebacks across 2 rotating cards, deliveries dated *before* signup |
| Betting — arbitrage | `Customer placing opposing home + away bets from IP 203.0.113.99 within seconds` | SHORTCUT once arbitrage pattern is in `fraud_memory` |
| Betting — velocity | `customer 1 placed 8 bets from IP 91.108.56.177 in 30 minutes` | EXPLORE first time |

The **Clayton Knight investigation** is the strongest single demo — the agent independently discovers the *delivery-confirmed-before-signup* anomaly (5 of 6 chargebacks), which is not in any seed catalog. That's the capability multiplier in one slide.

---

## File structure

```
Agent_AG/
├── ARCHITECTURE.md          # Architecture deep-dive: theses, custodial duties, lifecycle
├── MEMORY_MAINTENANCE_POC.md  # POC-phase design questions for Reconciliation + Compaction
├── VOCABULARY.md            # Canonical cognitive foundation vocabulary
│
├── agent_tools.py           # Substrate: assemble_context, route_investigation,
│                            #   consolidate_fraud_memory, recall_similar_fraud,
│                            #   compound_resolution, write_reasoning_checkpoint,
│                            #   decay_fraud_memory, plus execute_sql / vector_search
├── cognitive_loop.py        # Investigation loop: assemble → route → tool-use → slim summary
├── generate_world.py        # Seeds the full database (run once)
├── schema.sql               # Full TiDB schema, including fraud_memory + agent_reasoning
├── live_pulse.py            # Streams live orders every 500ms (Demo 1)
├── live_betting_pulse.py    # Streams live bets every 500ms (Demo 3)
├── requirements.txt         # Pinned dependencies
├── .env.example             # Credential template
│
├── adapters/                       # Domain plugins on a generic substrate
│   ├── fraud/__init__.py           # 16 e-commerce fraud patterns + tier callables
│   └── betting/__init__.py         # 3 sports-betting patterns + tier callables
│
├── execution/
│   ├── agent_ui.py                  # Demo 2 — Streamlit chat UI with agent memory sidebar
│   ├── fraud_dashboard.py           # Demo 1 — Real-time fraud monitor
│   ├── sports_betting_dashboard.py  # Demo 3 — Betting risk + fraud monitor
│   ├── betting_investigation.py     # Demo 4 — CLI cognitive-foundation investigation
│   ├── run_agent.py                 # Legacy CLI helper (pre-cognitive-foundation; kept for compatibility)
│   ├── seed_demo_data.py            # Creates the demo persona (Bernard)
│   ├── seed_orders.py               # Adds order history for the demo persona
│   ├── seed_reviews.py              # Reviews with sentiment scores and embeddings
│   ├── seed_fraud_data.py           # Fraud scenarios for Demo 1
│   ├── seed_betting_data.py         # Betting events and scenarios for Demo 3
│   └── apply_fraud_schema.py        # Schema migration helper (run if needed)
│
└── directives/
    └── tidb_agent_demo.md           # Demo directive: lifecycle, business value, demo flow
```

For the architecture, theses, custodial-duty implementation details, and POC-phase design questions, see [ARCHITECTURE.md](ARCHITECTURE.md) and [MEMORY_MAINTENANCE_POC.md](MEMORY_MAINTENANCE_POC.md).

---

## Troubleshooting

| Error | Fix |
|---|---|
| `SSL connection error` | Check `TIDB_SSL_CA` in `.env` points to the downloaded `isrgrootx1.pem` |
| `No results found` for customer queries | Run `seed_demo_data.py` and `seed_orders.py` |
| `No velocity anomalies` on Fraud Dashboard | Run `seed_fraud_data.py` |
| `No liability concentration` on Betting Dashboard | Run `seed_betting_data.py` |
| `No velocity anomalies` on Betting Dashboard | Run `seed_betting_data.py` — seeds the IP burst scenario |
| `No results` for sentiment/review queries | Run `seed_reviews.py` |
| `TOKENIZERS_PARALLELISM` warning | Already handled in `agent_ui.py` — safe to ignore |
| TiFlash query falls back to TiKV | Replica sync takes ~1 min after schema creation — wait and retry |
| Agent returns 0.50 confidence fallback | The triggered IP/customer isn't in seed data — use the known-good triggers above |

---

## Composability with TiDB Python SDK

PingCAP's official [pytidb](https://github.com/pingcap/pytidb) SDK ships an MCP server, a Pydantic-style schema layer, and built-in embedding functions (cloud-hosted Titan, AWS Bedrock-hosted Titan via Bedrock IAM, or local). The Cognitive Foundation **composes with pytidb**, not against it: pytidb is the data-access layer, the Cognitive Foundation provides the memory semantics — typed three-tier memory, custodial duties, substrate-driven routing — one layer above it. Adopting pytidb's `EmbeddingFunction` or its MCP server requires no schema changes here. Both projects converge on TiDB as the substrate for AI-era memory, which we treat as independent corroboration of the architectural bet rather than a competing approach.

See [ARCHITECTURE.md](ARCHITECTURE.md#differentiation-pytidb-is-the-sdk-this-is-the-pattern) for the differentiation table and production-deployment shape.

---

## Cognitive Foundation Portfolio

This repo is one of three implementations demonstrating the cognitive foundation across different domains:

| Repo | Domain | Memory tier spotlight | Custodial duty spotlight | Business outcome |
|---|---|---|---|---|
| [`tidb-self-healing-db-agent`](https://github.com/bernard-kavanagh/tidb-self-healing-db-agent) | Database operations | **Procedural** | Write control + branching safety | Reduced MTTR, safe autonomous remediation |
| [`ev_charger_anomaly_detection`](https://github.com/bernard-kavanagh/ev_charger_anomaly_detection) | Industrial IoT | **Semantic** | All five duties — the production reference | 10× token reduction, 24/7 monitoring at capped cost |
| [`tidb_fraud_detection`](https://github.com/bernard-kavanagh/tidb_fraud_detection) | Fintech / Gaming | **Three tiers, two adapters** | Write Control, Dedup, Decay live; Reconciliation + Compaction as POC decisions | Adaptive fraud detection, regulatory-grade audit trail, multi-vertical adapter proof |

All three repos run on the same principle: a **unified data substrate** where the agent's memory lives alongside operational data. The domain adapter changes. The substrate stays the same.

*The model forgets everything. The platform remembers. The human decides.*
— Bernard Kavanagh, *Cognitive Foundation series*
