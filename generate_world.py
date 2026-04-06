import mysql.connector
import random
import json
import os
import time
from faker import Faker
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# 1. Configuration
config = {
    'host': os.getenv('TIDB_HOST'),
    'port': int(os.getenv('TIDB_PORT', 4000)),
    'user': os.getenv('TIDB_USER'),
    'password': os.getenv('TIDB_PASSWORD'),
    'database': os.getenv('TIDB_DATABASE', 'test'),
    'ssl_ca': os.getenv('TIDB_SSL_CA'),
    'ssl_verify_cert': True
}

# 2. Initialize Models
fake = Faker()
print("📥 Loading AI Model (This might take a moment)...")
model = SentenceTransformer('all-MiniLM-L6-v2') 

# --- DATASETS ---

# A. Product Catalog (The "Vector" Target)
tech_products = [
    ("ProBook X1", "Laptop", 1200.00, "A high-performance laptop for professional video editing and 3D rendering."),
    ("Stealth G5", "Laptop", 1500.00, "Ultra-thin gaming laptop with RGB keyboard and high refresh rate screen."),
    ("OfficeMate", "Laptop", 600.00, "Reliable budget laptop for word processing and spreadsheets."),
    ("SoundMax Pro", "Audio", 250.00, "Noise-cancelling over-ear headphones with deep bass and 30-hour battery."),
    ("Buds Air", "Audio", 120.00, "Wireless in-ear earbuds with transparency mode and water resistance."),
    ("VisionTab 12", "Tablet", 800.00, "12-inch tablet with stylus support, perfect for digital artists and designers.")
]

# B. Sales Knowledge Base (The "Context" Target)
# These are the rules your Agent will use to "reason" about the data.
policy_documents = [
    {
        "category": "Returns",
        "content": "Standard products have a 30-day return window. However, Gaming Laptops (like Stealth G5) are restricted to a 14-day return window due to crypto-mining risks.",
        "meta": {"priority": "high", "tags": ["laptop", "gaming", "returns"]}
    },
    {
        "category": "Shipping",
        "content": "VIP Customers in EMEA receive free overnight shipping on all orders over $500. Standard customers pay $25.",
        "meta": {"priority": "medium", "tags": ["shipping", "vip", "emea"]}
    },
    {
        "category": "Discounts",
        "content": "Corporate bulk orders (quantity > 3) automatically qualify for a 12% discount. This does not apply to Audio products.",
        "meta": {"priority": "low", "tags": ["b2b", "discount"]}
    }
]

def generate_world():
    try:
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        print("✅ Connected to TiDB.")
        
        print("🚀 Starting World Generation...")

        # --- Step 1: Generate Customers (Relational) ---
        print("👤 Generating 100 Customers...")
        customer_ids = []
        regions = ['EMEA', 'NA', 'APAC', 'LATAM']
        
        for _ in range(100):
            name = fake.name()
            region = random.choice(regions)
            vip = random.choice([True, False])
            
            sql = "INSERT INTO customers (name, email, region, vip_status) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (name, fake.email(), region, vip))
            customer_ids.append(cursor.lastrowid)
        
        conn.commit()

        # --- Step 2: Generate Products + Vectors (AI) ---
        print("📦 Generating Products with Vector Embeddings...")
        product_ids = []
        
        for name, cat, price, desc in tech_products:
            embedding = model.encode(desc).tolist()
            embedding_str = str(embedding)
            
            sql = "INSERT INTO products (name, category, price, description, embedding) VALUES (%s, %s, %s, %s, %s)"
            cursor.execute(sql, (name, cat, price, desc, embedding_str))
            product_ids.append(cursor.lastrowid)
            
        conn.commit()

        # --- Step 3: Generate Sales Knowledge (The Missing Link) ---
        print("📚 Generating Sales Policies (Agent Context)...")
        
        for doc in policy_documents:
            # Vectorize the policy text so the Agent can find it semantically
            embedding = model.encode(doc['content']).tolist()
            embedding_str = str(embedding)
            meta_json = json.dumps(doc['meta'])
            
            sql = "INSERT INTO sales_knowledge (content, category, embedding, metadata) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (doc['content'], doc['category'], embedding_str, meta_json))

        conn.commit()

        # --- Step 4: Generate Orders (The Link) ---
        print("🛒 Generating 500 Historical Orders...")
        
        for _ in range(500):
            c_id = random.choice(customer_ids)
            p_id = random.choice(product_ids)
            qty = random.randint(1, 5)
            date = fake.date_time_between(start_date='-1y', end_date='now')
            
            sql = "INSERT INTO orders (customer_id, product_id, quantity, order_date) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (c_id, p_id, qty, date))

        conn.commit()
        print("🎉 World Generation Complete! Your Agent is ready.")
        conn.close()

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    generate_world()