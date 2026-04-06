import mysql.connector
import uuid
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
config = {
    'host': os.getenv('TIDB_HOST'),
    'port': int(os.getenv('TIDB_PORT', 4000)),
    'user': os.getenv('TIDB_USER'),
    'password': os.getenv('TIDB_PASSWORD'),
    'database': os.getenv('TIDB_DATABASE', 'test'),
    'ssl_ca': os.getenv('TIDB_SSL_CA'),
    'autocommit': True
}

class StateManager:
    def __init__(self):
        self.conn = mysql.connector.connect(**config)
    
    def get_or_create_session(self, user_id):
        """
        Checks if a user has an active session. If not, creates one.
        Returns: session_id (UUID)
        """
        cursor = self.conn.cursor(dictionary=True)
        
        # 1. Check for existing open session (active in last 24h)
        sql = """SELECT session_id FROM agent_sessions 
                 WHERE user_id = %s 
                 ORDER BY start_time DESC LIMIT 1"""
        cursor.execute(sql, (user_id,))
        result = cursor.fetchone()
        
        if result:
            return result['session_id']
        
        # 2. Create new session if none exists
        new_session_id = str(uuid.uuid4())
        sql = "INSERT INTO agent_sessions (session_id, user_id) VALUES (%s, %s)"
        cursor.execute(sql, (new_session_id, user_id))
        self.conn.commit()
        
        print(f"🆕 New Session Created: {new_session_id}")
        return new_session_id

    def save_interaction(self, session_id, role, content, tool_used=None):
        """
        Logs the "Thought Process" to TiDB for future RCA.
        """
        cursor = self.conn.cursor()
        
        # Metadata allows us to debug WHICH tool (SQL vs Vector) was used later
        meta = json.dumps({"tool": tool_used}) if tool_used else None
        
        sql = """INSERT INTO chat_history (session_id, role, content, metadata) 
                 VALUES (%s, %s, %s, %s)"""
        
        cursor.execute(sql, (session_id, role, content, meta))
        self.conn.commit()

    def get_recent_history(self, session_id, limit=5):
        """
        Fetches the last N messages to give the Agent context.
        """
        cursor = self.conn.cursor(dictionary=True)
        sql = """SELECT role, content FROM chat_history 
                 WHERE session_id = %s 
                 ORDER BY message_id ASC""" # Get them in chronological order
        
        cursor.execute(sql, (session_id,))
        rows = cursor.fetchall()
        
        # Keep only the last 'limit' messages to save tokens
        return rows[-limit:]

# --- TEST BLOCK ---
if __name__ == "__main__":
    # Run this to verify your State Manager is working
    state = StateManager()
    
    # 1. Create a Test User
    s_id = state.get_or_create_session("test_user_bernard")
    print(f"✅ Session ID: {s_id}")
    
    # 2. Log a fake conversation
    state.save_interaction(s_id, "user", "I want to buy a laptop.")
    state.save_interaction(s_id, "assistant", "Sure! We have the Stealth G5.", tool_used="Vector Search")
    
    # 3. Retrieve it
    history = state.get_recent_history(s_id)
    print("📜 History Retrieved:", history)