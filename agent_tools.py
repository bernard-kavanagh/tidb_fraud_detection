# Create this file in your app/ or root directory on your EC2 instance.
# Prerequisites:
# pip install mysql-connector-python sentence-transformers python-dotenv
import mysql.connector
import json
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


# --- TOOL 5: THE STATE MACHINE (Memory) ---
def create_session(session_id: str, user_id: str = "guest"):
    """
    Initializes a new session in TiDB to satisfy Foreign Key constraints.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            INSERT INTO agent_sessions (session_id, user_id, metadata)
            VALUES (%s, %s, %s)
        """
        # Default metadata
        meta = json.dumps({"source": "run_agent.py"})
        
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
