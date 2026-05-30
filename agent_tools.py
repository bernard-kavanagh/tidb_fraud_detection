# Create this file in your app/ or root directory on your EC2 instance.
# Prerequisites:
# pip install mysql-connector-python sentence-transformers python-dotenv
import mysql.connector
import json
import math
import os
from sentence_transformers import SentenceTransformer
from mysql.connector import Error

# --- CONFIGURATION ---
# Best Practice: Load Secrets from .env 
from dotenv import load_dotenv
load_dotenv()

DB_CONFIG = {
    'host': os.getenv('TIDB_HOST'),
    'port': int(os.getenv('TIDB_PORT', 4000)),
    'user': os.getenv('TIDB_USER'),
    'password': os.getenv('TIDB_PASSWORD'),
    'database': os.getenv('TIDB_DATABASE', 'test'),
    'ssl_ca': os.getenv('TIDB_SSL_CA'),
    'autocommit': True
}

# --- MODEL ROUTING CONSTANTS ---
# Single source of truth for model selection. Override via .env when testing
# new model versions (e.g. Opus on the explore path for complex fraud).
MODEL_SHORTCUT = os.getenv("TIDB_AGENT_MODEL_SHORTCUT", "claude-haiku-4-5")
MODEL_EXPLORE  = os.getenv("TIDB_AGENT_MODEL_EXPLORE",  "claude-sonnet-4-6")
MODEL_SUMMARY  = os.getenv("TIDB_AGENT_MODEL_SUMMARY",  "claude-haiku-4-5")

# --- COGNITIVE FOUNDATION TUNING ---
# Routing gate thresholds. Raise similarity gate to reduce shortcut rate.
# Lower confidence gate to allow more patterns to shortcut (not recommended).
ROUTING_CONFIDENCE_GATE  = float(os.getenv("ROUTING_CONFIDENCE_GATE",  "0.85"))
ROUTING_SIMILARITY_GATE  = float(os.getenv("ROUTING_SIMILARITY_GATE",  "0.55"))

# Deduplication threshold. Lower = more aggressive merging of similar patterns.
DEDUP_DISTANCE_THRESHOLD = float(os.getenv("DEDUP_DISTANCE_THRESHOLD", "0.15"))

# Write control floor — minimum confidence to persist into fraud_memory.
WRITE_CONTROL_MIN_CONFIDENCE = float(os.getenv("WRITE_CONTROL_MIN_CONFIDENCE", "0.85"))

# Load the Embedding Model (Global to avoid reloading per request)
# This runs locally on your EC2 instance.
_model = None

def get_model():
    """Lazy load the model to avoid crashes/delays on import."""
    global _model
    if _model is None:
        print("🧠 Loading Embedding Model for Vector Tools...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

def get_db_connection():
    """Helper to get a fresh connection."""
    return mysql.connector.connect(**DB_CONFIG)

# --- TOOL 1: THE ANALYTICAL ENGINE (SQL) ---
def execute_sql(query: str):
    """
    Executes a standard SQL query.
    Use this for: "Total revenue", "Count orders", "Check inventory".
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Safety: Prevent accidental destruction during demos unless intended
        if "DROP" in query.upper() or "DELETE" in query.upper():
            return "❌ SAFETY BLOCK: Destructive queries are blocked in this demo mode."

        cursor.execute(query)
        results = cursor.fetchall()
        
        if not results:
            return "No results found."
            
        # Limit context window usage by truncating massive results
        return json.dumps(results[:10], default=str)

    except Error as e:
        return f"❌ SQL Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- TOOL 2: THE SEMANTIC ENGINE (Vector Search) ---
def vector_search(user_query: str, target_table: str = 'sales_knowledge'):
    """
    Performs a semantic search using TiDB Vectors.
    
    Args:
        user_query: The natural language question (e.g. "Can I return a laptop?")
        target_table: 'sales_knowledge' (Policies) or 'products' (Catalog)
    """
    conn = None
    try:
        # 1. Convert text to Vector (Local Inference)
        query_embedding = get_model().encode(user_query).tolist()
        query_vec_str = str(query_embedding)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 2. Construct TiDB Vector Query
        # We use VEC_COSINE_DISTANCE for semantic similarity [Source 93]
        if target_table == 'sales_knowledge':
            sql = """
                SELECT content, category, 
                       VEC_COSINE_DISTANCE(embedding, %s) as distance
                FROM sales_knowledge
                ORDER BY distance ASC
                LIMIT 3;
            """
            
        elif target_table == 'products':
            sql = """
                SELECT name, price, description, category,
                       VEC_COSINE_DISTANCE(embedding, %s) as distance
                FROM products
                ORDER BY distance ASC
                LIMIT 3;
            """
        elif target_table == 'reviews':
            sql = """
                SELECT r.review_text, r.rating, r.sentiment_label, r.sentiment_score,
                       c.name as customer,
                       VEC_COSINE_DISTANCE(r.embedding, %s) as distance
                FROM reviews r
                JOIN customers c ON r.customer_id = c.customer_id
                ORDER BY distance ASC
                LIMIT 5;
            """
        else:
            return "❌ Error: Invalid target table for vector search."

        # 3. Execute
        cursor.execute(sql, (query_vec_str,))
        results = cursor.fetchall()

        # Format for the LLM
        response = []
        for row in results:
            if target_table == 'reviews':
                response.append(
                    f"[{row['sentiment_label'].upper()} | ⭐{row['rating']}/5 | {row['customer']}] "
                    f"\"{row['review_text']}\" (Confidence: {1 - row['distance']:.2f})"
                )
            else:
                response.append(f"Found: {row.get('content') or row.get('name')} (Confidence: {1 - row['distance']:.2f})")
            
        return "\n".join(response)

    except Error as e:
        return f"❌ Vector DB Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- TOOL 3: THE WRITE-BACK ENGINE (Fraud Action) ---
def flag_order(order_id: int, reason: str):
    """
    Flags an order as suspicious, demonstrating agentic write-back.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            UPDATE orders 
            SET status = 'flagged', flagged_reason = %s
            WHERE order_id = %s
        """
        cursor.execute(sql, (reason, order_id))
        conn.commit()
        return f"✅ Order {order_id} flagged successfully."
    except Error as e:
        return f"❌ SQL Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()

def adjust_odds(event_id: int, overloaded_selection: str):
    """
    Rebalances a betting market by adjusting odds.
    Reduces the overloaded selection's odds by 12% to make it less attractive,
    and increases the opposing side by 8% to draw money across.
    Used when liability concentration exceeds threshold — keeps the market open.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT home_odds, away_odds FROM betting_events WHERE event_id = %s",
            (event_id,)
        )
        row = cursor.fetchone()
        if not row:
            return f"❌ Event {event_id} not found."

        home_odds = float(row[0])
        away_odds = float(row[1])

        if overloaded_selection == 'home':
            new_home = round(home_odds * 0.88, 3)
            new_away = round(away_odds * 1.08, 3)
            summary = f"Home {home_odds} → {new_home} | Away {away_odds} → {new_away}"
        else:
            new_home = round(home_odds * 1.08, 3)
            new_away = round(away_odds * 0.88, 3)
            summary = f"Away {away_odds} → {new_away} | Home {home_odds} → {new_home}"

        cursor.execute(
            "UPDATE betting_events SET home_odds = %s, away_odds = %s WHERE event_id = %s",
            (new_home, new_away, event_id)
        )
        conn.commit()
        return f"✅ Odds adjusted for event {event_id}. {summary}"
    except Exception as e:
        return f"❌ Error adjusting odds: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()

def flag_bettor(ip_address: str):
    """
    Flags all accepted bets from a suspicious IP address as 'flagged'.
    Removes them from the active pool and holds for manual review.
    Demonstrates fraud detection write-back for the sports betting demo.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE bets SET status = 'flagged' WHERE ip_address = %s AND status = 'accepted'",
            (ip_address,)
        )
        affected = cursor.rowcount
        conn.commit()
        return f"✅ IP {ip_address} flagged. {affected} bets held for review."
    except Error as e:
        return f"❌ SQL Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()

def get_suspicious_orders():
    """
    Uses TiFlash/HTAP to find recent suspicious transaction patterns.
    Examples: 
      - Velocity bursts (same IP, many orders in short time)
      - Unusually high value for new accounts
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # HTAP Query: Find IPs with 3+ orders in the last 24h OR single orders > $5000.
        # Limits to 'pending' to avoid re-reviewing.
        sql = """
            SELECT o.order_id, c.name as customer, o.ip_address, o.amount, o.country, o.order_date
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.status = 'pending'
            AND (
                o.amount > 3000
                OR o.ip_address IN (
                    SELECT ip_address FROM orders 
                    WHERE status = 'pending' AND order_date >= NOW() - INTERVAL 1 DAY 
                    GROUP BY ip_address HAVING COUNT(*) >= 3
                )
            )
            ORDER BY o.order_date DESC
            LIMIT 5;
        """
        cursor.execute(sql)
        results = cursor.fetchall()
        
        if not results:
            return "No suspicious orders found."
            
        return json.dumps(results, default=str)
    except Error as e:
        return f"❌ SQL Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- TOOL 4: REVIEW ANALYTICS (HTAP + ML on Operational Data) ---
def get_review_analytics():
    """
    Runs HTAP aggregate queries on the reviews table via TiFlash.
    Returns sentiment distribution, per-product ratings, and recent negative reviews.
    This demonstrates real-time ML analytics on operational data — no ETL required.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Overall sentiment + rating summary (TiFlash columnar scan)
        summary_sql = """
            SELECT /*+ read_from_storage(tiflash[reviews]) */
                COUNT(*)                                                        AS total_reviews,
                ROUND(AVG(rating), 2)                                           AS avg_rating,
                SUM(CASE WHEN sentiment_label = 'positive' THEN 1 ELSE 0 END)  AS positive_count,
                SUM(CASE WHEN sentiment_label = 'neutral'  THEN 1 ELSE 0 END)  AS neutral_count,
                SUM(CASE WHEN sentiment_label = 'negative' THEN 1 ELSE 0 END)  AS negative_count,
                ROUND(AVG(sentiment_score), 3)                                  AS avg_sentiment_score
            FROM reviews
        """
        cursor.execute(summary_sql)
        summary = cursor.fetchone()

        # Per-product breakdown — surfaces underperforming products
        product_sql = """
            SELECT /*+ read_from_storage(tiflash[reviews]) */
                p.name                                                              AS product_name,
                COUNT(r.review_id)                                                  AS review_count,
                ROUND(AVG(r.rating), 2)                                             AS avg_rating,
                ROUND(AVG(r.sentiment_score), 3)                                    AS avg_sentiment,
                SUM(CASE WHEN r.sentiment_label = 'negative' THEN 1 ELSE 0 END)    AS negative_count
            FROM reviews r
            JOIN products p ON r.product_id = p.product_id
            WHERE r.review_type = 'product'
            GROUP BY r.product_id, p.name
            ORDER BY avg_rating DESC
            LIMIT 10
        """
        cursor.execute(product_sql)
        product_ratings = cursor.fetchall()

        # Recent negative reviews — churn risk signals
        negative_sql = """
            SELECT r.review_text, r.rating, r.sentiment_score,
                   c.name AS customer, p.name AS product, r.created_at
            FROM reviews r
            JOIN customers c ON r.customer_id = c.customer_id
            LEFT JOIN products p ON r.product_id = p.product_id
            WHERE r.sentiment_label = 'negative'
            ORDER BY r.created_at DESC
            LIMIT 5
        """
        cursor.execute(negative_sql)
        negative_reviews = cursor.fetchall()

        # Sentiment trend over last 7 days
        trend_sql = """
            SELECT /*+ read_from_storage(tiflash[reviews]) */
                DATE(created_at)                    AS review_date,
                ROUND(AVG(sentiment_score), 3)      AS daily_sentiment,
                COUNT(*)                            AS review_count
            FROM reviews
            WHERE created_at >= NOW() - INTERVAL 7 DAY
            GROUP BY DATE(created_at)
            ORDER BY review_date ASC
        """
        cursor.execute(trend_sql)
        trend = cursor.fetchall()

        return json.dumps({
            "summary": summary,
            "product_ratings": product_ratings,
            "recent_negative_reviews": negative_reviews,
            "sentiment_trend_7d": trend
        }, default=str)

    except Error as e:
        return f"❌ SQL Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()


# --- COGNITIVE FOUNDATION: CONTEXT ASSEMBLY ---
#
# assemble_context() is the Thesis 05 function: the platform decides what
# the model sees BEFORE the model sees its first token. Pure SQL. Zero LLM
# calls. Hard token budget. Priority-ordered sources.
#
# Five tiers (fraud adapter):
#   T1  entity profile             ~80 tokens     (customers + risk band)
#   T2  recent transactions        ~100-300       (orders by entity/IP)
#   T3  active investigation       ~100-200       (latest agent_reasoning row)
#   T4  prior investigations       ~200-500       (agent_reasoning history for entity)
#   T5  domain semantic memory     cap 500        (fraud_memory via vector similarity)
#
# Returns (system_context, sources, top_match, vector_matches) — the last two
# feed the routing layer (Stage 3).

CONTEXT_BUDGET_TOKENS = 3600
TIER_CAPS = {
    "t1_entity": 80,
    "t2_recent": 300,
    "t3_active": 200,
    "t4_prior":  500,
    "t5_semantic": 500,
}

def _approx_tokens(text: str) -> int:
    """Cheap token estimate: ~4 chars per token. Good enough for budget gating."""
    return max(1, len(text) // 4)

def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    return text if len(text) <= max_chars else text[:max_chars] + "…"

def assemble_context(entity_ref: str = None, session_id: str = None,
                     trigger_text: str = None, adapter=None):
    """
    Build the agent's prompt context from the substrate. Pure SQL.

    Tiers 1, 2, 4 are domain-specific and delegated to the adapter (Thesis 11).
    Tiers 3 and 5 are substrate-generic and handled inline.

    Args:
        entity_ref:   customer_id (as str) or ip_address — the focus of the investigation
        session_id:   current agent session, used to find the active reasoning row
        trigger_text: natural-language description of what triggered this run,
                      used as the query vector for Tier 5 semantic retrieval
        adapter:      domain adapter module exposing tier_1_entity, tier_2_recent,
                      tier_4_prior. Defaults to adapters.fraud.

    Returns:
        dict with:
          system_context  — concatenated prompt under the budget
          sources         — per-tier provenance + token cost (for observability)
          top_match       — the single highest-confidence fraud_memory row, or None
          vector_matches  — list of fraud_memory rows from Tier 5 (for routing inspection)
    """
    if adapter is None:
        from adapters import fraud as adapter

    sources = {}
    blocks = []
    budget_used = 0
    top_match = None
    vector_matches = []

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # ----- TIER 1: entity profile + risk band (adapter) -----
        t1_text, t1_status = adapter.tier_1_entity(cursor, entity_ref)
        if t1_text:
            t1_text = _truncate_to_tokens(t1_text, TIER_CAPS["t1_entity"])
            t1_cost = _approx_tokens(t1_text)
            if budget_used + t1_cost <= CONTEXT_BUDGET_TOKENS:
                blocks.append(t1_text)
                budget_used += t1_cost
                sources["t1_entity"] = {"tokens": t1_cost, "status": t1_status}
        else:
            sources["t1_entity"] = {"tokens": 0, "status": t1_status}

        # ----- TIER 2: recent transactions for this entity (adapter) -----
        t2_lines, t2_status = adapter.tier_2_recent(cursor, entity_ref)
        if t2_lines:
            t2_text = "[T2 recent] " + " | ".join(t2_lines)
            t2_text = _truncate_to_tokens(t2_text, TIER_CAPS["t2_recent"])
            t2_cost = _approx_tokens(t2_text)
            if budget_used + t2_cost <= CONTEXT_BUDGET_TOKENS:
                blocks.append(t2_text)
                budget_used += t2_cost
                sources["t2_recent"] = {"tokens": t2_cost, "count": len(t2_lines), "status": t2_status}
        else:
            sources["t2_recent"] = {"tokens": 0, "status": t2_status}

        # ----- TIER 3: active investigation checkpoint (substrate) -----
        if session_id:
            cursor.execute(
                """SELECT observation, hypothesis, confidence
                   FROM agent_reasoning
                   WHERE session_id = %s
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                t3_text = (
                    f"[T3 active] obs={row['observation']} | "
                    f"hyp={row['hypothesis']} | conf={row['confidence']}"
                )
                t3_text = _truncate_to_tokens(t3_text, TIER_CAPS["t3_active"])
                t3_cost = _approx_tokens(t3_text)
                if budget_used + t3_cost <= CONTEXT_BUDGET_TOKENS:
                    blocks.append(t3_text)
                    budget_used += t3_cost
                    sources["t3_active"] = {"tokens": t3_cost, "status": "ok"}

        # ----- TIER 4: prior investigations for this entity (adapter) -----
        t4_lines, t4_status = adapter.tier_4_prior(cursor, entity_ref)
        if t4_lines:
            t4_text = "[T4 prior] " + " | ".join(t4_lines)
            t4_text = _truncate_to_tokens(t4_text, TIER_CAPS["t4_prior"])
            t4_cost = _approx_tokens(t4_text)
            if budget_used + t4_cost <= CONTEXT_BUDGET_TOKENS:
                blocks.append(t4_text)
                budget_used += t4_cost
                sources["t4_prior"] = {"tokens": t4_cost, "count": len(t4_lines), "status": t4_status}
        else:
            sources["t4_prior"] = {"tokens": 0, "status": t4_status}

        # ----- TIER 5: domain semantic memory (fraud_memory via vector similarity) -----
        if trigger_text:
            try:
                query_vec = str(get_model().encode(trigger_text).tolist())
                cursor.execute(
                    """SELECT pattern_id, scope, entity_ref, content, confidence, evidence_count,
                              (1 - VEC_COSINE_DISTANCE(embedding, %s)) AS similarity
                       FROM fraud_memory
                       WHERE superseded_by IS NULL
                       ORDER BY VEC_COSINE_DISTANCE(embedding, %s) ASC
                       LIMIT 3""",
                    (query_vec, query_vec)
                )
                vector_matches = cursor.fetchall() or []

                if vector_matches:
                    # Identify the top match for the routing layer (Stage 3).
                    top_match = max(vector_matches, key=lambda r: float(r['confidence']))

                    t5_lines = []
                    for r in vector_matches:
                        snippet = r['content'][:80]
                        t5_lines.append(
                            f"pattern={r['pattern_id']} scope={r['scope']} "
                            f"conf={r['confidence']} sim={float(r['similarity']):.2f} "
                            f"evidence={r['evidence_count']} :: {snippet}"
                        )
                    t5_text = "[T5 semantic] " + " | ".join(t5_lines)
                    t5_text = _truncate_to_tokens(t5_text, TIER_CAPS["t5_semantic"])
                    t5_cost = _approx_tokens(t5_text)
                    if budget_used + t5_cost <= CONTEXT_BUDGET_TOKENS:
                        blocks.append(t5_text)
                        budget_used += t5_cost
                        sources["t5_semantic"] = {
                            "tokens": t5_cost,
                            "count": len(vector_matches),
                            "status": "ok",
                        }
            except Error as e:
                sources["t5_semantic"] = {"tokens": 0, "status": f"degraded:{e}"}

    finally:
        if conn and conn.is_connected():
            conn.close()

    return {
        "system_context": "\n".join(blocks),
        "sources": sources,
        "budget_used": budget_used,
        "budget_total": CONTEXT_BUDGET_TOKENS,
        "top_match": top_match,
        "vector_matches": vector_matches,
    }


# --- COGNITIVE FOUNDATION: CUSTODIAL DUTIES ---
#
# The five duties are what turn a vector table into memory (Thesis 03).
# Shipping deduplication first as the demo-visible duty; reconciliation and
# confidence decay follow.

def consolidate_fraud_memory():
    """
    Custodial duty 2 — Deduplication. Merges fraud_memory rows whose
    cosine distance is below DEDUP_DISTANCE_THRESHOLD.

    For each duplicate cluster:
      - keep the row with the highest confidence (ties broken by oldest pattern_id)
      - sum evidence_count across the cluster
      - mark all other rows superseded_by → kept_pattern_id
      - bump last_reinforced_at on the kept row

    Returns a JSON summary of what was merged. Demo-visible: wire to a button
    in the UI and watch fraud_memory shrink in real time.
    """
    conn = None
    merges = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """SELECT pattern_id, content, embedding, confidence, evidence_count, created_at
               FROM fraud_memory
               WHERE superseded_by IS NULL
               ORDER BY pattern_id ASC"""
        )
        rows = cursor.fetchall()

        if len(rows) < 2:
            return json.dumps({"status": "ok", "active_rows": len(rows), "merges": []})

        # Find near-duplicates by computing pairwise VEC_COSINE_DISTANCE in SQL,
        # one query per row — keeps logic simple and lets TiDB do the math.
        seen = set()
        for anchor in rows:
            if anchor['pattern_id'] in seen:
                continue
            anchor_vec = anchor['embedding']
            # Portable: WHERE on the same expression rather than HAVING on the
            # alias. Avoids HAVING-without-GROUP-BY ambiguity across SQL engines.
            cursor.execute(
                """SELECT pattern_id, confidence, evidence_count, created_at,
                          VEC_COSINE_DISTANCE(embedding, %s) AS distance
                   FROM fraud_memory
                   WHERE superseded_by IS NULL
                     AND pattern_id != %s
                     AND VEC_COSINE_DISTANCE(embedding, %s) < %s
                   ORDER BY distance ASC""",
                (anchor_vec, anchor['pattern_id'], anchor_vec, DEDUP_DISTANCE_THRESHOLD),
            )
            dupes = cursor.fetchall()
            if not dupes:
                continue

            cluster = [anchor] + dupes
            # Highest confidence wins; ties → oldest pattern_id (smaller id)
            keep = max(cluster, key=lambda r: (float(r['confidence']), -r['pattern_id']))
            total_evidence = sum(int(r['evidence_count']) for r in cluster)
            losers = [r for r in cluster if r['pattern_id'] != keep['pattern_id']]

            for loser in losers:
                cursor.execute(
                    "UPDATE fraud_memory SET superseded_by = %s WHERE pattern_id = %s",
                    (keep['pattern_id'], loser['pattern_id'])
                )
                seen.add(loser['pattern_id'])
            cursor.execute(
                """UPDATE fraud_memory
                   SET evidence_count = %s, last_reinforced_at = NOW()
                   WHERE pattern_id = %s""",
                (total_evidence, keep['pattern_id'])
            )
            seen.add(keep['pattern_id'])

            merges.append({
                "kept_pattern_id": keep['pattern_id'],
                "merged_pattern_ids": [r['pattern_id'] for r in losers],
                "evidence_consolidated": total_evidence,
            })

        conn.commit()
        return json.dumps({
            "status": "ok",
            "active_rows_before": len(rows),
            "active_rows_after": len(rows) - sum(len(m["merged_pattern_ids"]) for m in merges),
            "merges": merges,
        }, default=str)
    except Error as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        if conn and conn.is_connected():
            conn.close()


def reinforce_pattern(pattern_id: int) -> bool:
    """
    Mark a fraud_memory pattern as reinforced.

    Called by the cognitive loop when a pattern wins the routing gate — the
    pattern was useful, so `last_reinforced_at` bumps and `evidence_count`
    increments. This is the reinforcement signal that Gap 2 of the maintenance
    audit identified: without it, decay treats actively-used patterns the same
    as forgotten ones, so a pattern that drives 100 shortcuts a day would fade
    while a never-matched pattern stays at its initial confidence.

    Returns True if a row was updated (active pattern), False otherwise.
    Best-effort — failures are swallowed by the caller; investigations never
    block on reinforcement.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE fraud_memory
               SET evidence_count    = evidence_count + 1,
                   last_reinforced_at = NOW()
               WHERE pattern_id = %s AND superseded_by IS NULL""",
            (pattern_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Error:
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()


def reconcile_fraud_memory():
    """
    Custodial duty 3 — Reconciliation.

    When two fraud_memory patterns contradict each other (e.g., an entity was
    cleared in one investigation and flagged in another), this duty resolves
    the conflict by surfacing both patterns, applying a resolution strategy,
    and writing a superseded_by chain on the losing pattern.

    Resolution strategy options (to be selected at implementation time):
      - recency wins:  newer high-confidence pattern supersedes older one
      - evidence wins: higher evidence_count pattern supersedes
      - human-in-loop: surface to operator dashboard for manual resolution

    Not yet implemented. Wire alongside consolidate_fraud_memory() once dedup
    is stable in production.
    """
    raise NotImplementedError(
        "reconcile_fraud_memory() not yet implemented. "
        "See AGENT_LIFECYCLE.md §3 for the reconciliation specification."
    )


def decay_fraud_memory(half_life_days: int = 30, dry_run: bool = False,
                       grace_period_days: int = 7, floor: float = 0.30):
    """
    Custodial duty 4 — Confidence Decay.

    Reduces the confidence of fraud_memory patterns that have not been
    reinforced recently. Reinforcement happens via two paths:
      - reinforce_pattern()       when a pattern wins the routing gate
      - consolidate_fraud_memory() when dedup merges into the pattern

    Exponential half-life math:
        new = old * exp( -ln(2) * days_unreinforced / half_life_days )

    Examples (half_life_days = 30):
      - 30 days unreinforced → confidence halves    (0.90 → 0.45)
      - 60 days unreinforced → confidence quarters  (0.90 → 0.225)
      - 90 days unreinforced → ~12.5% of original   (0.90 → 0.113)

    Patterns dropping below ROUTING_CONFIDENCE_GATE stop driving SHORTCUTs.
    Patterns dropping below `floor` (default 0.30) are candidates for
    compaction — they're skipped by future decay passes to avoid further
    erosion of an already-dead pattern.

    Args:
        half_life_days:    time for confidence to halve. Domain-tunable.
        dry_run:           True → preview only, no writes. Always use first.
        grace_period_days: skip patterns reinforced in the last N days.
                           Prevents penalising fresh writes.
        floor:             skip patterns already below this confidence. They've
                           already lost the routing gate; further decay is
                           waste.

    Returns:
        JSON: dry_run, half_life_days, totals (active, eligible, skipped),
              decayed (list of per-pattern preview: pattern_id, days_unreinforced,
              old_confidence, new_confidence, will_lose_routing, content_snippet).
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """SELECT pattern_id, content, confidence, last_reinforced_at,
                      DATEDIFF(NOW(), last_reinforced_at) AS days_unreinforced
               FROM fraud_memory
               WHERE superseded_by IS NULL"""
        )
        rows = cursor.fetchall()

        decayed = []
        skipped_grace = 0
        skipped_floor = 0

        for r in rows:
            days = int(r['days_unreinforced'] or 0)
            old = float(r['confidence'])

            if days < grace_period_days:
                skipped_grace += 1
                continue
            if old < floor:
                skipped_floor += 1
                continue

            decay_factor = math.exp(-math.log(2) * days / half_life_days)
            new = round(old * decay_factor, 3)

            decayed.append({
                "pattern_id": r['pattern_id'],
                "days_unreinforced": days,
                "old_confidence": old,
                "new_confidence": new,
                "will_lose_routing": new < ROUTING_CONFIDENCE_GATE,
                "content_snippet": (r['content'][:60] + "…") if len(r['content']) > 60 else r['content'],
            })

        if not dry_run and decayed:
            for item in decayed:
                cursor.execute(
                    "UPDATE fraud_memory SET confidence = %s WHERE pattern_id = %s",
                    (item['new_confidence'], item['pattern_id']),
                )
            conn.commit()

        return json.dumps({
            "dry_run": dry_run,
            "half_life_days": half_life_days,
            "grace_period_days": grace_period_days,
            "floor": floor,
            "total_active": len(rows),
            "eligible_decayed": len(decayed),
            "skipped_grace_period": skipped_grace,
            "skipped_below_floor": skipped_floor,
            "patterns": decayed,
        }, default=str)
    except Error as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        if conn and conn.is_connected():
            conn.close()


def compact_fraud_memory():
    """
    Custodial duty 5 — Compaction.

    Removes or archives fraud_memory rows that are:
      - superseded (superseded_by IS NOT NULL) and older than 90 days
      - decayed below confidence 0.50 and unreinforced for > 60 days
      - exact duplicates missed by the deduplication threshold

    Compaction keeps the semantic memory store lean so vector search latency
    does not grow unboundedly as the system accumulates patterns.

    Intended to run as a scheduled job (weekly or monthly), not inline with
    the investigation loop.

    Not yet implemented.
    """
    raise NotImplementedError("compact_fraud_memory() not yet implemented.")


# --- COGNITIVE FOUNDATION: ROUTING LAYER ---
#
# Thesis 06 — the substrate decides which model runs, not the model itself.
#
# After assemble_context(), inspect the top fraud_memory match. If it passes
# BOTH gates, route the investigation to the shortcut path: cheaper model,
# tighter round budget, pre-classify skipped (the substrate already classified
# the trigger by retrieving its match). Otherwise, explore path.

ROUTE_SHORTCUT = {
    "path": "SHORTCUT",
    "model": MODEL_SHORTCUT,
    "max_tool_rounds": 3,
}
ROUTE_EXPLORE = {
    "path": "EXPLORE",
    "model": MODEL_EXPLORE,
    "max_tool_rounds": 15,
}

def route_investigation(vector_matches, confidence_gate=None, similarity_gate=None):
    """
    Decide which model + round budget runs the investigation loop.

    Canonical pattern (AGENT_LIFECYCLE.md §1 STEP 2): scan Tier 5 matches
    for ANY entry passing both gates. Earlier versions of this function
    inspected a single pre-selected top_match — a higher-similarity match
    with marginally lower confidence could be wrongly excluded. The scan
    fixes that.

    Accepts either:
      - a list of vector_matches dicts (canonical, preferred)
      - a single dict (legacy compatibility — wraps as a one-element list)
      - None / empty list (cold start — explore path)

    Gate precedence (highest first):
      1. confidence_gate / similarity_gate kwargs (caller override)
      2. ROUTING_CONFIDENCE_GATE / ROUTING_SIMILARITY_GATE (env or module default)
    Adapter-level overrides are resolved by the caller (run_investigation in
    cognitive_loop.py) before invoking this function — that keeps the function
    pure and adapter-agnostic.

    If multiple rows pass both gates, prefer the one with the highest
    combined confidence × similarity (deterministic, surfaced in reason).

    Returns: path, model, max_tool_rounds, reason, gates, matched_pattern_id.
    """
    cg = ROUTING_CONFIDENCE_GATE if confidence_gate is None else float(confidence_gate)
    sg = ROUTING_SIMILARITY_GATE if similarity_gate is None else float(similarity_gate)

    if vector_matches is None:
        candidates = []
    elif isinstance(vector_matches, dict):
        candidates = [vector_matches]
    else:
        candidates = list(vector_matches)

    if not candidates:
        return {
            **ROUTE_EXPLORE,
            "reason": "no fraud_memory matches returned by assemble_context",
            "gates": {"confidence": None, "similarity": None,
                      "confidence_gate": cg, "similarity_gate": sg},
            "scanned": 0,
            "matched_pattern_id": None,
        }

    passing = []
    for m in candidates:
        conf = float(m.get("confidence") or 0)
        sim = float(m.get("similarity") or 0)
        if conf >= cg and sim >= sg:
            passing.append((conf * sim, conf, sim, m))

    if passing:
        # Deterministic best: highest (conf × sim), tie-broken by similarity.
        passing.sort(key=lambda t: (t[0], t[2]), reverse=True)
        best_score, best_conf, best_sim, best = passing[0]
        return {
            **ROUTE_SHORTCUT,
            "reason": (
                f"{len(passing)}/{len(candidates)} fraud_memory matches passed both gates "
                f"(conf≥{cg}, sim≥{sg}); chose pattern {best.get('pattern_id')} "
                f"(conf={best_conf:.2f}, sim={best_sim:.2f}, score={best_score:.3f}) "
                f"— substrate-driven shortcut"
            ),
            "gates": {
                "confidence": best_conf, "similarity": best_sim,
                "confidence_gate": cg, "similarity_gate": sg,
            },
            "scanned": len(candidates),
            "passed": len(passing),
            "matched_pattern_id": best.get("pattern_id"),
        }

    # Surface the closest miss for observability — operator sees which row
    # was nearest the gate and why it failed.
    closest = max(
        candidates,
        key=lambda m: (float(m.get("confidence") or 0) >= cg,
                       float(m.get("similarity") or 0)),
    )
    c_conf = float(closest.get("confidence") or 0)
    c_sim = float(closest.get("similarity") or 0)
    failing = []
    if c_conf < cg:
        failing.append(f"conf={c_conf:.2f}<{cg}")
    if c_sim < sg:
        failing.append(f"sim={c_sim:.2f}<{sg}")
    return {
        **ROUTE_EXPLORE,
        "reason": (
            f"scanned {len(candidates)} matches; none passed both gates. "
            f"Closest: pattern {closest.get('pattern_id')} (" + ", ".join(failing) + ")"
        ),
        "gates": {
            "confidence": c_conf, "similarity": c_sim,
            "confidence_gate": cg, "similarity_gate": sg,
        },
        "scanned": len(candidates),
        "passed": 0,
        "matched_pattern_id": None,
    }


# --- COGNITIVE FOUNDATION: SEMANTIC MEMORY OPERATIONS ---

def recall_similar_fraud(query_text: str, scope: str = None, entity_ref: str = None, k: int = 5):
    """
    Retrieve confirmed fraud patterns from fraud_memory via vector similarity.
    Optional scope + entity_ref filters narrow the lookup.

    This is one of the tools the agent loop can choose to call. assemble_context()
    already surfaces the top-k matches in Tier 5; recall_similar_fraud() is the
    on-demand version when the loop wants a broader pull or a different scope.
    """
    conn = None
    try:
        query_vec = str(get_model().encode(query_text).tolist())
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        sql = """
            SELECT pattern_id, scope, entity_ref, content, confidence, evidence_count,
                   (1 - VEC_COSINE_DISTANCE(embedding, %s)) AS similarity
            FROM fraud_memory
            WHERE superseded_by IS NULL
        """
        params = [query_vec]
        if scope:
            sql += " AND scope = %s"
            params.append(scope)
        if entity_ref:
            sql += " AND entity_ref = %s"
            params.append(entity_ref)
        sql += " ORDER BY VEC_COSINE_DISTANCE(embedding, %s) ASC LIMIT %s"
        params.extend([query_vec, k])

        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        if not rows:
            return "No similar fraud patterns in memory."

        return json.dumps([
            {
                "pattern_id": r["pattern_id"],
                "scope": r["scope"],
                "entity_ref": r["entity_ref"],
                "content": r["content"],
                "confidence": float(r["confidence"]),
                "similarity": float(r["similarity"]),
                "evidence_count": r["evidence_count"],
            }
            for r in rows
        ], default=str)
    except Error as e:
        return f"❌ Recall Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()


def compound_resolution(content: str, confidence: float = 0.85,
                        scope: str = "global", entity_ref: str = None):
    """
    Write a confirmed fraud pattern to fraud_memory.

    This is the Thesis 02 line made operational: the platform remembers on the
    model's behalf. The model proposes the resolution; this function embeds it
    and persists it as a semantic memory row that future sessions can recall.

    Custodial duty 1 — Write control — is enforced HERE as an explicit code
    gate, not just by tool-description guidance to the model. Calls below the
    configured floor (WRITE_CONTROL_MIN_CONFIDENCE, default 0.85) are rejected
    with an error string. Deterministic enforcement; misaligned models cannot
    pollute the memory store.
    """
    if confidence < WRITE_CONTROL_MIN_CONFIDENCE:
        return (
            f"❌ Write control: confidence={confidence:.2f} is below the "
            f"minimum threshold ({WRITE_CONTROL_MIN_CONFIDENCE}). Only "
            f"confirmed outcomes (confidence≥{WRITE_CONTROL_MIN_CONFIDENCE}) "
            f"persist to fraud_memory. Raise confidence or do not persist."
        )

    conn = None
    try:
        embedding = str(get_model().encode(content).tolist())
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """INSERT INTO fraud_memory
                 (scope, entity_ref, content, embedding, confidence, evidence_count, last_reinforced_at)
               VALUES (%s, %s, %s, %s, %s, 1, NOW())""",
            (scope, entity_ref, content, embedding, confidence)
        )
        new_id = cursor.lastrowid
        conn.commit()
        return f"✅ fraud_memory pattern {new_id} stored (scope={scope}, confidence={confidence:.2f})."
    except Error as e:
        return f"❌ Compound Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()


def seed_fraud_memory_from_adapter(adapter=None):
    """
    Load an adapter's SEED_CATALOG into fraud_memory.

    Mirrors the EV adapter's outage_catalog seeding pattern from AGENT_LIFECYCLE.md:
    production clusters skip the warm-up curve because they bring weeks of
    consolidated patterns to invocation 1. The seed catalog gives a fresh cluster
    the same advantage on day one — high-confidence canonical patterns that the
    routing gate can shortcut on immediately.

    Idempotent by COSINE DISTANCE, not exact string match — paraphrased
    duplicates are caught using the same DEDUP_DISTANCE_THRESHOLD that the
    deduplication custodial duty uses. So a tweaked wording of an existing
    seed entry will not re-seed.
    """
    if adapter is None:
        from adapters import fraud as adapter

    seeded = []
    skipped = []
    model = get_model()

    for entry in getattr(adapter, "SEED_CATALOG", []):
        conn = None
        try:
            embedding = str(model.encode(entry["content"]).tolist())
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            # Vector-distance idempotency: any active pattern within the dedup
            # threshold is treated as already-present.
            cursor.execute(
                """SELECT pattern_id, VEC_COSINE_DISTANCE(embedding, %s) AS distance
                   FROM fraud_memory
                   WHERE superseded_by IS NULL
                   ORDER BY distance ASC LIMIT 1""",
                (embedding,),
            )
            existing = cursor.fetchone()
            cursor.close()

            if existing and float(existing['distance']) < DEDUP_DISTANCE_THRESHOLD:
                skipped.append({
                    "snippet": entry["content"][:60],
                    "matched_pattern_id": existing['pattern_id'],
                    "distance": float(existing['distance']),
                })
                continue

            result = compound_resolution(
                content=entry["content"],
                confidence=entry.get("confidence", 0.85),
                scope=entry.get("scope", "global"),
                entity_ref=entry.get("entity_ref"),
            )
            seeded.append(result)
        finally:
            if conn and conn.is_connected():
                conn.close()
    return json.dumps({"seeded": seeded, "already_present": skipped}, default=str)


def write_reasoning_checkpoint(session_id: str, observation: str, hypothesis: str,
                               evidence_refs: list = None, confidence: float = 0.0,
                               resolution: str = None):
    """
    Write a structured episodic checkpoint to agent_reasoning.

    NOT a transcript. Each row is the agent's distilled state at a decision
    point. Stage 5 (slim summary) reads the latest row and produces the
    investigation report from these five fields — without replaying the
    loop conversation.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO agent_reasoning
                 (session_id, observation, hypothesis, evidence_refs, confidence, resolution)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (session_id, observation, hypothesis,
             json.dumps(evidence_refs or []), confidence, resolution)
        )
        new_id = cursor.lastrowid
        conn.commit()
        return f"✅ agent_reasoning checkpoint {new_id} written."
    except Error as e:
        return f"❌ Checkpoint Error: {e}"
    finally:
        if conn and conn.is_connected():
            conn.close()


# --- TOOL 5: THE STATE MACHINE (Memory) ---
def create_session(session_id: str, user_id: str = "guest", metadata: dict = None):
    """
    Initializes a new session in TiDB to satisfy Foreign Key constraints.

    Convention for cognitive-foundation investigations:
      - Set user_id = str(entity_ref) (customer_id or ip_address) when starting
        an entity-focused investigation. Tier 4 in assemble_context joins on
        agent_sessions.user_id; sessions created with 'guest' or a UI-level
        label will silently return no prior investigations for that entity.

    Audit-trail conventions (metadata JSON):
      - source              : where the session was created from. Examples:
                              "agent_ui.bootstrap" (Streamlit UI start),
                              "agent_ui.investigation" (Admin fraud invest),
                              "betting_investigation.cli", "run_agent.cli".
      - parent_session_id   : OPTIONAL. When a session spawns a child session
                              (e.g. UI bootstrap spawns an entity-scoped
                              investigation), the child writes the parent's
                              session_id here. Enables full lineage queries:
                                SELECT session_id, JSON_EXTRACT(metadata, '$.source'),
                                       JSON_EXTRACT(metadata, '$.parent_session_id')
                                FROM agent_sessions WHERE session_id = X;

    Both fields are metadata-only (no schema change). Elevate to columns if
    you want indexed lineage queries; the data is already there.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        sql = """
            INSERT INTO agent_sessions (session_id, user_id, metadata)
            VALUES (%s, %s, %s)
        """
        # Honest metadata. Caller-supplied; we don't fabricate a source.
        meta = json.dumps(metadata or {})

        cursor.execute(sql, (session_id, user_id, meta))
        conn.commit()
        print(f"✅ Session {session_id} created.")

    except Error as e:
        print(f"❌ Session Creation Failed: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

def log_interaction(session_id: str, role: str, content: str, tool_used: str = None):
    """
    Saves the Agent's 'Thoughts' to TiDB for RCA (Root Cause Analysis).
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            INSERT INTO chat_history (session_id, role, content, metadata)
            VALUES (%s, %s, %s, %s)
        """
        meta = json.dumps({"tool": tool_used}) if tool_used else None
        
        cursor.execute(sql, (session_id, role, content, meta))
        conn.commit()
        return "✅ Memory Saved."

    except Error as e:
        print(f"Logging Failed: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- TEST HARNESS (Run this to verify before deploying) ---
if __name__ == "__main__":
    print("🧪 Testing SQL Tool...")
    print(execute_sql("SELECT count(*) FROM orders"))

    print("\n🧪 Testing Vector Tool (Policy)...")
    print(vector_search("What is the return policy for gaming laptops?", "sales_knowledge"))

    print("\n🧪 Testing Vector Tool (Products)...")
    print(vector_search("Something specifically for video editing", "products"))

    print("\n🧪 Testing seed_fraud_memory_from_adapter() (idempotent)...")
    print(seed_fraud_memory_from_adapter())

    print("\n🧪 Testing recall_similar_fraud() (velocity-burst query)...")
    print(recall_similar_fraud("velocity burst same IP multiple orders card testing"))

    print("\n🧪 Testing consolidate_fraud_memory() (dedup duty)...")
    print(consolidate_fraud_memory())

    print("\n🧪 Testing route_investigation() — cold (None matches)...")
    print(route_investigation(None))

    print("\n🧪 Testing route_investigation() — warm (synthetic passing match)...")
    print(route_investigation([{
        "pattern_id": 999, "confidence": 0.91, "similarity": 0.72
    }]))

    print("\n🧪 Testing assemble_context() — cold start (no entity)...")
    ctx = assemble_context(trigger_text="suspicious orders from 192.168.1.1")
    print(f"  budget_used={ctx['budget_used']}/{ctx['budget_total']}")
    print(f"  sources={ctx['sources']}")
    print(f"  top_match={'found' if ctx['top_match'] else 'none'}")
    print(f"  vector_matches={len(ctx['vector_matches'])} rows")

    print("\n🧪 Testing write control (rejects low-confidence write)...")
    print(compound_resolution("Test pattern below the floor", confidence=0.10))
