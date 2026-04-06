import sys
import os
import random
import time
from faker import Faker

# Add parent directory to path to import agent_tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_tools import get_db_connection

def seed_fraud_scenarios():
    print("🕵️ Seeding Fraud Detection Data Patterns...")
    conn = None
    fake = Faker()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Ensure we have customers and products
        cursor.execute("SELECT customer_id FROM customers")
        valid_customers = [row['customer_id'] for row in cursor.fetchall()]
        
        cursor.execute("SELECT product_id, price FROM products")
        products_data = cursor.fetchall()
        
        if not valid_customers or not products_data:
            print("❌ Pls run generate_world.py + seed_demo_data.py first.")
            return

        # --- SCENARIO 1: The Normal Baseline ---
        print("   -> Creating baseline normal transaction history...")
        for _ in range(20):
            c_id = random.choice(valid_customers)
            prod = random.choice(products_data)
            p_id, price = prod['product_id'], prod['price']
            
            qty = random.randint(1, 2)
            # Use real price if found, else fake it
            amount = float(price * qty) if price else random.uniform(20.0, 150.0)
            
            date = fake.date_time_between(start_date='-7d', end_date='now')
            ip = fake.ipv4()
            country = fake.country()[:50]
            
            sql = """
                INSERT INTO orders 
                (customer_id, product_id, quantity, amount, ip_address, country, status, order_date) 
                VALUES (%s, %s, %s, %s, %s, %s, 'cleared', %s)
            """
            cursor.execute(sql, (c_id, p_id, qty, amount, ip, country, date))
            
        # --- SCENARIO 2: Fraud - Velocity Burst ---
        # Same IP, multiple rapid orders
        fraud_ip = "185.15.54.22"
        fraud_country = "Unknown"
        print("   -> Creating Fraud Scenario: Velocity Burst...")
        
        for i in range(5):
            c_id = random.choice(valid_customers) # Compromised accounts
            prod = random.choice(products_data)
            amount = float(prod['price']) * 2 if prod['price'] else 400.0
            date = fake.date_time_between(start_date='-1h', end_date='now')
            
            sql = """
                INSERT INTO orders 
                (customer_id, product_id, quantity, amount, ip_address, country, status, order_date) 
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
            """
            cursor.execute(sql, (c_id, prod['product_id'], 2, amount, fraud_ip, fraud_country, date))
            
        # --- SCENARIO 3: Fraud - High Value Anomaly ---
        # Very large single order
        print("   -> Creating Fraud Scenario: High Value Anomaly...")
        c_id = valid_customers[0] # Just use the first customer (perhaps Bernard)
        prod = random.choice(products_data)
        amount = 8999.00 # Suspiciously high
        date = fake.date_time_between(start_date='-1h', end_date='now')
        ip = fake.ipv4()
        country_anomaly = "San Marino"
        
        sql = """
            INSERT INTO orders 
            (customer_id, product_id, quantity, amount, ip_address, country, status, order_date) 
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
        """
        cursor.execute(sql, (c_id, prod['product_id'], 5, amount, ip, country_anomaly, date))
        
        conn.commit()
        print("✅ Fraud dataset injected successfully!")

    except Exception as e:
        print(f"❌ Error seeding fraud data: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

if __name__ == "__main__":
    seed_fraud_scenarios()
