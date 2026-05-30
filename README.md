# TiDB Fraud Detection — Cognitive Foundation for Fintech

Three demos. One **unified data substrate**. No separate vector store, no data warehouse, no ETL pipeline.

This platform implements the **cognitive foundation** architecture for fintech and gaming — adaptive fraud detection with three-tier memory, substrate-driven model routing, and live custodial duties on a single TiDB cluster. It demonstrates the **domain adapter** pattern: the same memory architecture used for [industrial IoT](https://github.com/bernard-kavanagh/ev_charger_anomaly_detection) and [database operations](https://github.com/bernard-kavanagh/tidb-self-healing-db-agent), adapted to e-commerce transactions and sports betting streams via [`adapters/fraud/`](adapters/fraud/__init__.py).

> ### What's wired today (8 of 12 theses)
>
> - **Thesis 03 — Custodial duties.** Duty 1 (write control) is a code gate in [`compound_resolution()`](agent_tools.py); duty 2 (deduplication) is [`consolidate_fraud_memory()`](agent_tools.py), wired to a sidebar button. Duties 3–5 (reconciliation, decay, compaction) ship as documented stubs in [agent_tools.py](agent_tools.py).
> - **Thesis 04 — Consolidation.** One TiDB cluster holds transactions, semantic memory, episodic checkpoints, and policy knowledge in one transaction boundary. No vector store, no cache, no warehouse.
> - **Thesis 05 — Context assembly.** [`assemble_context()`](agent_tools.py) builds a 5-tier prompt under a 3,600-token budget. Pure SQL, zero LLM calls, ~50 ms target.
> - **Thesis 06 — Substrate-driven routing.** [`route_investigation()`](agent_tools.py) **scans all Tier 5 matches** (canonical pattern from AGENT_LIFECYCLE.md §1 STEP 2). Any row passing both gates → Haiku/3-round shortcut. None passing → Sonnet/15-round explore. The gate decision is the demo moment.
> - **Thesis 07 — Three tiers, no conflation.** [`agent_reasoning`](schema.sql) is structured episodic checkpoints (observation/hypothesis/evidence/confidence/resolution); [`fraud_memory`](schema.sql) is vector-indexed semantic memory; procedural logic lives in the adapter.
> - **Thesis 08 — Supersede.** `superseded_by` column on `fraud_memory` ships; the dedup duty writes the link on every merge. Auto-supersede on contradiction (reconciliation) is the next duty to wire.
> - **Thesis 10 — Compliance is architectural.** ACID-bounded writes, single transaction log, vectors-as-datatype. A single SQL query reconstructs the chain from trigger → assembled context → routing decision → tool trace → checkpoint → resolution. The structure is there; the single-query RCA demo is the artefact still to be recorded.
> - **Thesis 11 — Pattern generic, domain is plugin.** Two adapters now share the same substrate: [`adapters/fraud/`](adapters/fraud/__init__.py) (16-pattern e-commerce catalog) and [`adapters/betting/`](adapters/betting/__init__.py) (3-pattern sports-book catalog). `assemble_context(adapter=...)` and `run_investigation(adapter=...)` pick the plugin.
>
> The four theses not yet delivered are 1 (memory is infrastructure — narrative claim, not testable code), 2 (model forgets / human decides — partially live via dedup; "human decides" needs an HITL approval gate), 9 (branching), and 12 (system of thought, not record — narrative claim).

Fraud detection hits the **Memory Wall** when transaction patterns evolve faster than static rules can adapt and every investigation starts cold — context, prior patterns, and entity history rebuilt from scratch. The cognitive foundation solves this with persistent three-tier memory, substrate-driven model routing, and lifecycle management served through budget-constrained context assembly.

Most "unified database" pitches show a dashboard. This shows an **agent that reasons, queries, and acts** — combining SQL joins, vector similarity search, and real-time columnar analytics — all through a single TiDB connection string.

**Demo 1 — Agent UI:** Two flows in one interface, demonstrating the difference between RAG and the cognitive foundation:
- **Customer** asks _"Can I return my gaming laptop?"_ — the RAG path: SQL for order history + vector search for the return policy + Haiku synthesis.
- **Admin** asks _"investigate suspicious orders from this IP"_ — the cognitive-foundation path: [`assemble_context()`](agent_tools.py) builds a 5-tier prompt under the token budget → [`route_investigation()`](agent_tools.py) picks Sonnet/explore or Haiku/shortcut based on `fraud_memory` matches → real tool-use loop with cached system prompt → slim summary call reads the structured checkpoint, not the loop. Every stage streams into the chain-of-thought sidebar.

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

**Cognitive foundation talking point:** The same cluster holds the live transaction stream (Data Plane) and the agent's investigation memory (Context Plane) in one ACID boundary. No sync lag between what the agent knows and what's happening in production.

**The core talking point:** Both the fraud velocity query and the betting liability query use `/*+ read_from_storage(tiflash[...]) */` to aggregate across the columnar engine while the live pulse is simultaneously inserting rows into TiKV. Same data, same database, no synchronisation lag. No Flink, no Kafka, no enrichment pipeline.

---

## Architecture — the cognitive foundation lifecycle

```
                            Trigger (Admin chat / CLI / dashboard "Investigate")
                                                  │
                                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  STEP 1 — assemble_context()    pure SQL · zero LLM calls · ~50 ms       │
   │                                                                          │
   │   T1 entity profile        T2 recent activity         T3 active checkpt   │
   │   T4 prior investigations  T5 semantic (fraud_memory) ← vector retrieval  │
   │   ──────────────────────────────────────────────────────────────────     │
   │   Returns: system_context (≤3,600 tokens), top_match, vector_matches      │
   └──────────────────────────────────────────────────────────────────────────┘
                                                  │
                                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  STEP 2 — route_investigation()  code-driven, not LLM                    │
   │                                                                          │
   │   Scan vector_matches:                                                   │
   │     any row with confidence ≥ 0.85 AND similarity ≥ gate                 │
   │       yes → SHORTCUT (Haiku, 3 rounds)                                   │
   │       no  → EXPLORE  (Sonnet, 15 rounds)                                 │
   │                                                                          │
   │   On SHORTCUT match → reinforce_pattern() bumps evidence_count           │
   └──────────────────────────────────────────────────────────────────────────┘
                                                  │
                                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  STEP 3 — agent loop (cognitive_loop.run_investigation)                  │
   │                                                                          │
   │   System prompt cached (cache_control: ephemeral) + adapter SCHEMA_HINT  │
   │   Tools: execute_sql, vector_search, recall_similar_fraud,               │
   │          flag_order, write_reasoning_checkpoint, compound_resolution     │
   │   Model picks the next tool. Loop ends on end_turn or round budget.      │
   └──────────────────────────────────────────────────────────────────────────┘
                                                  │
                                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  STEP 4 — slim summary call (Haiku on structured checkpoint, NOT loop)   │
   │                                                                          │
   │   SELECT latest agent_reasoning row → 3-paragraph investigation report   │
   │   Fallback: synthesise checkpoint from tool_trace if agent didn't write  │
   └──────────────────────────────────────────────────────────────────────────┘
                                                  │
                                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  ONE TiDB CLUSTER                                                        │
   │                                                                          │
   │   TiKV (row) ────► live transactions, bets, orders, sessions             │
   │   TiFlash (col) ─► HTAP velocity + liability queries on same writes      │
   │   Vector / HNSW ─► fraud_memory, sales_knowledge, reviews                │
   │                                                                          │
   │   Custodial duties run as SQL inside the cluster:                        │
   │     1 Write Control   ✅   2 Deduplication   ✅   3 Reconciliation 🟡 POC │
   │     4 Confidence Decay ✅   5 Compaction     🟡 POC                       │
   └──────────────────────────────────────────────────────────────────────────┘
```

**Five priority-ordered context sources, one substrate-driven routing decision, one cached system prompt, one structured summary.** The agent is stateless and ephemeral; the substrate remembers on its behalf. Pure SQL handles everything that isn't reasoning — assembly, routing, custodial duties — and the model only ever sees a curated prompt under a hard token budget.

See [directives/tidb_agent_demo.md](directives/tidb_agent_demo.md) for the lifecycle described in operator language.

---

## Cognitive Foundation: Three-Tier Memory

This repo implements all three tiers of the cognitive foundation's memory architecture:

### Episodic Memory
**Tables**: `agent_reasoning` (structured checkpoints), `chat_history` (conversation transcript), `agent_sessions`

`agent_reasoning` stores **outcomes-only checkpoints** — `observation`, `hypothesis`, `evidence_refs` (JSON), `confidence`, `resolution`. Written by the agent loop via [`write_reasoning_checkpoint()`](agent_tools.py). The Stage 5 slim summary call reads ONE row of this table to produce the investigation report — it does not replay the loop conversation. Memory grows at O(investigations), not O(reasoning steps) — Thesis 03 (write control).

`chat_history` remains as a UI-facing transcript for the conversational paths. It is not the episodic memory the routing layer reads.

### Semantic Memory
**Tables**: `fraud_memory` (learned patterns), `sales_knowledge`, `reviews`

`fraud_memory` is the compounding tier. Each confirmed investigation can write a pattern via [`compound_resolution()`](agent_tools.py) — vector-embedded, scoped `global` or `entity`, with `confidence`, `evidence_count`, `superseded_by`, and `last_reinforced_at`. Future agent sessions recall these patterns via [`recall_similar_fraud()`](agent_tools.py) or surface them automatically through Tier 5 of `assemble_context()`. The routing gate reads `confidence ≥ 0.85 AND similarity ≥ 0.55` from this table to decide Sonnet/explore vs Haiku/shortcut.

`sales_knowledge` and `reviews` remain hand-seeded reference knowledge for the customer/RAG flow.

**Cold-start solution.** [`adapters/fraud/`](adapters/fraud/__init__.py) ships with a `SEED_CATALOG` of 16 e-commerce fraud patterns (velocity, ATO, refund abuse, synthetic identity, device-fingerprint reuse, headless-browser, chargeback, gift-card laundering). [`adapters/betting/`](adapters/betting/__init__.py) adds 3 sportsbook patterns. Click the *"🌱 Seed fraud_memory"* sidebar button to load them — the cluster skips the warm-up curve and routes shortcut from invocation 1, the same way production EV charger clusters do.

### Procedural Memory
**Implementation**: Agent directives (`directives/tidb_agent_demo.md`), escalation logic, write-back actions

The 'how-to' layer: when to flag an order for review vs auto-resolve, when to adjust odds vs freeze a market, when to escalate to a human analyst. Currently encoded in the agent directive and the write-back tools (`flag_order`, `adjust_odds`, `flag_bettor`). These write-back actions demonstrate **human-in-the-loop** decision gates — the agent surfaces the anomaly, the human (or automated policy) decides the action.

> **Explicit procedural memory** — storing learned escalation strategies as a distinct memory type with its own retrieval path — is planned for the cognitive foundation project.

## Custodial Duties in Fintech

| Duty | Status | Implementation |
|---|---|---|
| **Write Control** | ✅ Live (code gate) | [`compound_resolution()`](agent_tools.py) rejects writes below `WRITE_CONTROL_MIN_CONFIDENCE` (default 0.85). Deterministic enforcement; misaligned models cannot pollute fraud_memory. `write_reasoning_checkpoint()` stores distilled checkpoints, not transcripts — memory grows at O(investigations), not O(reasoning steps). |
| **Deduplication** | ✅ Live | [`consolidate_fraud_memory()`](agent_tools.py) merges rows with cosine distance < `DEDUP_DISTANCE_THRESHOLD`. Highest-confidence wins; evidence counts sum; losers get `superseded_by` set. Wired to the *"🧹 Run dedup"* sidebar button. Seed loader uses the same threshold for idempotency, so paraphrased duplicates of catalog patterns also get caught. |
| **Confidence Decay** | ✅ Live (dry-run + apply) | [`decay_fraud_memory(half_life_days, dry_run, grace_period_days, floor)`](agent_tools.py). Exponential half-life: `confidence *= exp(-ln(2) * days_unreinforced / half_life_days)`. Two sidebar buttons: *"📉 Preview decay"* (no writes) and *"📉 Apply decay"*. Reinforcement signal flows from `reinforce_pattern()` (called when a pattern wins the routing gate) and from `consolidate_fraud_memory()`. |
| **Reconciliation** | 🟡 POC-phase decision | Detection of contradiction is domain-specific — same-`entity_ref` + opposing verdict semantics. We treat this as a customer-led design decision in POC planning: auto-supersede vs human-in-loop queue vs evidence-weighted. Schema-ready (`superseded_by`). |
| **Compaction** | 🟡 POC-phase decision | Archive policy for superseded + decayed-below-floor rows. Cadence and retention horizon are customer-led decisions for POC planning. |

> All five duties are now grep-able in the codebase, not just listed here. Tunable thresholds (routing gates, dedup, write control) are env-overridable via `.env` — see [`.env.example`](.env.example).
>
> The two POC-phase duties (Reconciliation, Compaction) have a dedicated planning artifact: **[MEMORY_MAINTENANCE_POC.md](MEMORY_MAINTENANCE_POC.md)** — five design questions for Reconciliation, four for Compaction. Customer-facing; bring it to the POC kickoff. This is intentionally *not* shipped as code — these duties require domain-specific judgment about regulatory environment, risk appetite, and operating model that only the buying team can make.
>
> For the full five-duty framework, see [VOCABULARY.md](./VOCABULARY.md).

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
- `agent_sessions`, `chat_history` — conversation log tables
- `reviews` — product and service reviews with sentiment scores and vector embeddings
- `betting_events`, `bets` — sports betting tables with TiFlash replicas
- **`fraud_memory`** — vector-indexed semantic memory of confirmed fraud patterns (cognitive foundation)
- **`agent_reasoning`** — structured episodic checkpoints (observation/hypothesis/evidence/confidence/resolution)

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

### Known-good demo triggers

These triggers point at IPs and customers that actually exist in `seed_fraud_data.py` / `seed_betting_data.py`. Use them when demoing — querying an IP that isn't in the seed data leaves the agent with nothing to verify on the SHORTCUT path and produces a fallback-summary report at 0.50 confidence.

| Vertical | Trigger (paste into Admin chat or CLI) | Expected path |
|---|---|---|
| Fraud — velocity burst | `investigate suspicious orders from IP 185.15.54.22` | SHORTCUT once warm (5 pending orders seeded against this IP) |
| Fraud — headless bot | `investigate orders with Puppeteer or Playwright user agents` | EXPLORE first time, SHORTCUT after pattern compounds |
| Fraud — chargeback fraud | `investigate customer 4 for chargeback fraud` | EXPLORE — the agent will find Clayton Knight's 6 chargebacks across 2 rotating cards, with deliveries dated *before* his signup |
| Betting — arbitrage | `Customer placing opposing home + away bets from IP 203.0.113.99 within seconds` | SHORTCUT once pattern 18 (arbitrage) is in `fraud_memory` |
| Betting — velocity | `customer 1 placed 8 bets from IP 91.108.56.177 in 30 minutes` | EXPLORE first time |

The "Clayton Knight" investigation is the strongest single demo — the agent independently discovers the *delivery-confirmed-before-signup* anomaly (5 of 6 chargebacks), which is not in any seed catalog. That's the capability multiplier in one slide.

---

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

Watch the sidebar update in real time. For the **Customer (RAG) path**, the conversation transcript persists to `chat_history`. For the **Admin (cognitive foundation) path**, the agent writes a structured checkpoint to `agent_reasoning` — observation, hypothesis, evidence_refs, confidence, resolution — which is what the slim summary call reads to produce the report. Two paths, two memory shapes, deliberately contrasted.

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

The cognitive foundation eliminates this separation architecturally — enrichment context (semantic memory), investigation history (episodic memory), and live transactions (data plane) share one transaction boundary. No ETL, no sync, no consistency gaps.

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
├── agent_tools.py          # Substrate: assemble_context, route_investigation,
│                           #   consolidate_fraud_memory, recall_similar_fraud,
│                           #   compound_resolution, write_reasoning_checkpoint,
│                           #   plus legacy execute_sql / vector_search / write-backs
├── cognitive_loop.py       # The investigation loop: assemble → route → tool-use → slim summary
├── generate_world.py       # Seeds the full database (run once)
├── schema.sql              # Full TiDB schema (now includes fraud_memory + agent_reasoning)
├── live_pulse.py           # Streams live orders every 500ms (fraud demo)
├── live_betting_pulse.py   # Streams live bets every 500ms (sports betting demo)
├── .env.example            # Credential template
│
├── adapters/                       # Thesis 11 — domain plugins on a generic substrate
│   ├── fraud/__init__.py           # 16 e-commerce fraud patterns + tier callables
│   └── betting/__init__.py         # 3 sports-betting patterns + tier callables (same substrate)
│
├── execution/
│   ├── agent_ui.py                    # Demo 1 — Streamlit chat UI with agent memory sidebar
│   ├── betting_investigation.py       # CLI entry-point for the betting adapter (Thesis 11 demo)
│   ├── fraud_dashboard.py             # Demo 2 — Real-time fraud monitor
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
    └── tidb_agent_demo.md        # Demo directive: lifecycle, business value, demo flow, procedural memory
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

---

## Cognitive Foundation Portfolio

This repo is one of three implementations demonstrating the cognitive foundation architecture across different domains:

| Repo | Domain | Memory tier spotlight | Custodial duty spotlight | Business outcome |
|---|---|---|---|---|
| [`tidb-self-healing-db-agent`](https://github.com/bernard-kavanagh/tidb-self-healing-db-agent) | Database operations | **Procedural** | Write control + branching safety | Reduced MTTR, safe autonomous remediation |
| [`ev_charger_anomaly_detection`](https://github.com/bernard-kavanagh/ev_charger_anomaly_detection) | Industrial IoT | **Semantic** | All five duties — the production reference | 10x token reduction, 24/7 monitoring at capped cost |
| [`tidb_fraud_detection`](https://github.com/bernard-kavanagh/tidb_fraud_detection) | Fintech / Gaming | **Three tiers, two adapters** | Write Control, Deduplication, Confidence Decay live; Reconciliation + Compaction as POC-phase decisions | Adaptive fraud detection, regulatory-grade audit trail, multi-vertical adapter proof |

All three repos run on the same principle: a **unified data substrate** where the agent's memory lives alongside operational data. The **domain adapter** changes. The cognitive foundation stays the same.

> *'The model forgets everything. The platform remembers. The human decides.'*
