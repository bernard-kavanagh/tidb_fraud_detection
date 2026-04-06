import sys
import os
import random
from datetime import datetime, timedelta
from faker import Faker

# Add parent directory to path to import agent_tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_tools import get_db_connection

def seed_betting_data():
    print("⚽ Seeding Sports Betting Data...")
    conn = None
    fake = Faker()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch existing customer IDs
        cursor.execute("SELECT customer_id FROM customers")
        valid_customers = [row['customer_id'] for row in cursor.fetchall()]

        if not valid_customers:
            print("❌ No customers found. Run generate_world.py first.")
            return

        # Clear existing betting data so re-runs are idempotent
        print("   -> Clearing existing betting data...")
        cursor.execute("DELETE FROM bets")
        cursor.execute("DELETE FROM betting_events")
        cursor.execute("ALTER TABLE betting_events AUTO_INCREMENT = 1")
        cursor.execute("ALTER TABLE bets AUTO_INCREMENT = 1")
        print("   -> Tables cleared and IDs reset.")

        now = datetime.now()

        # ==========================================
        # STEP 1: Insert 10 Betting Events
        # ==========================================
        print("   -> Seeding 10 betting events across 3 sports...")

        events = [
            # Football — Premier League
            {
                'sport': 'Football', 'home_team': 'Arsenal', 'away_team': 'Chelsea',
                'league': 'Premier League',
                'event_time': now + timedelta(hours=2),
                'home_odds': 2.10, 'away_odds': 3.20, 'draw_odds': 3.40
            },
            {
                'sport': 'Football', 'home_team': 'Manchester City', 'away_team': 'Liverpool',
                'league': 'Premier League',
                'event_time': now + timedelta(hours=5),
                'home_odds': 1.90, 'away_odds': 3.50, 'draw_odds': 3.60
            },
            {
                'sport': 'Football', 'home_team': 'Real Madrid', 'away_team': 'Barcelona',
                'league': 'La Liga',
                'event_time': now + timedelta(hours=8),
                'home_odds': 2.20, 'away_odds': 2.80, 'draw_odds': 3.10
            },
            {
                'sport': 'Football', 'home_team': 'PSG', 'away_team': 'Marseille',
                'league': 'Ligue 1',
                'event_time': now + timedelta(hours=24),
                'home_odds': 1.85, 'away_odds': 3.30, 'draw_odds': 3.70
            },
            {
                'sport': 'Football', 'home_team': 'Bayern Munich', 'away_team': 'Borussia Dortmund',
                'league': 'Bundesliga',
                'event_time': now + timedelta(hours=36),
                'home_odds': 1.95, 'away_odds': 3.40, 'draw_odds': 3.50
            },
            # Basketball — NBA
            {
                'sport': 'Basketball', 'home_team': 'Lakers', 'away_team': 'Celtics',
                'league': 'NBA',
                'event_time': now + timedelta(hours=4),
                'home_odds': 2.05, 'away_odds': 1.80, 'draw_odds': None
            },
            {
                'sport': 'Basketball', 'home_team': 'Warriors', 'away_team': 'Bulls',
                'league': 'NBA',
                'event_time': now + timedelta(hours=10),
                'home_odds': 1.75, 'away_odds': 2.10, 'draw_odds': None
            },
            {
                'sport': 'Basketball', 'home_team': 'Heat', 'away_team': 'Nets',
                'league': 'NBA',
                'event_time': now + timedelta(hours=28),
                'home_odds': 1.90, 'away_odds': 2.00, 'draw_odds': None
            },
            # Tennis — Grand Slams / ATP
            {
                'sport': 'Tennis', 'home_team': 'Novak Djokovic', 'away_team': 'Carlos Alcaraz',
                'league': 'ATP Masters',
                'event_time': now + timedelta(hours=6),
                'home_odds': 1.80, 'away_odds': 2.05, 'draw_odds': None
            },
            {
                'sport': 'Tennis', 'home_team': 'Jannik Sinner', 'away_team': 'Daniil Medvedev',
                'league': 'ATP Masters',
                'event_time': now + timedelta(hours=32),
                'home_odds': 1.95, 'away_odds': 1.95, 'draw_odds': None
            },
        ]

        event_ids = []
        for ev in events:
            sql = """
                INSERT INTO betting_events
                (sport, home_team, away_team, league, event_time, status, home_odds, away_odds, draw_odds)
                VALUES (%s, %s, %s, %s, %s, 'active', %s, %s, %s)
            """
            cursor.execute(sql, (
                ev['sport'], ev['home_team'], ev['away_team'], ev['league'],
                ev['event_time'], ev['home_odds'], ev['away_odds'], ev['draw_odds']
            ))
            event_ids.append(cursor.lastrowid)

        print(f"   -> Created {len(event_ids)} events. Event IDs: {event_ids}")

        # Map event index to event data for later use
        events_with_ids = list(zip(event_ids, events))

        # ==========================================
        # STEP 2: Normal Baseline (~60 bets)
        # ==========================================
        print("   -> Creating baseline of 60 normal bets...")

        for _ in range(60):
            c_id = random.choice(valid_customers)
            ev_id, ev = random.choice(events_with_ids)

            if ev['sport'] == 'Football':
                selection = random.choices(
                    ['home', 'away', 'draw'], weights=[45, 35, 20]
                )[0]
            else:
                selection = random.choices(['home', 'away'], weights=[50, 50])[0]

            if selection == 'home':
                odds = ev['home_odds']
            elif selection == 'away':
                odds = ev['away_odds']
            else:
                odds = ev['draw_odds']

            stake = round(random.uniform(10, 500), 2)
            potential_payout = round(stake * odds, 2)
            placed_at = fake.date_time_between(start_date='-48h', end_date='now')
            ip = fake.ipv4()

            sql = """
                INSERT INTO bets
                (customer_id, event_id, selection, stake, odds, potential_payout, status, ip_address, placed_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'accepted', %s, %s)
            """
            cursor.execute(sql, (c_id, ev_id, selection, stake, odds, potential_payout, ip, placed_at))

        print("   -> Baseline bets created.")

        # ==========================================
        # STEP 3: Liability Concentration Scenario
        # ==========================================
        # Pick the first football event (Arsenal vs Chelsea)
        football_events = [(eid, ev) for eid, ev in events_with_ids if ev['sport'] == 'Football']
        liability_event_id, liability_event = football_events[0]

        print(f"\n   -> 🚨 LIABILITY CONCENTRATION scenario on Event #{liability_event_id}: "
              f"{liability_event['home_team']} vs {liability_event['away_team']} ({liability_event['league']})")
        print("      12 bets all on 'home', stakes $200–$800, placed within last 2 hours")

        for _ in range(12):
            c_id = random.choice(valid_customers)
            stake = round(random.uniform(200, 800), 2)
            odds = liability_event['home_odds']
            potential_payout = round(stake * odds, 2)
            placed_at = fake.date_time_between(start_date='-2h', end_date='now')
            ip = fake.ipv4()

            sql = """
                INSERT INTO bets
                (customer_id, event_id, selection, stake, odds, potential_payout, status, ip_address, placed_at)
                VALUES (%s, %s, 'home', %s, %s, %s, 'accepted', %s, %s)
            """
            cursor.execute(sql, (c_id, liability_event_id, stake, odds, potential_payout, ip, placed_at))

        print(f"      ✅ Liability concentration seeded on Event #{liability_event_id} "
              f"({liability_event['home_team']} vs {liability_event['away_team']})")

        # ==========================================
        # STEP 4: Velocity Burst Scenario
        # ==========================================
        velocity_customer_id = valid_customers[0]
        velocity_ip = '91.108.56.177'

        # Pick 8 different events (or repeat if fewer available) for variety
        velocity_events = random.choices(events_with_ids, k=8)

        print(f"\n   -> 🚨 VELOCITY BURST scenario: Customer #{velocity_customer_id} | IP: {velocity_ip}")
        print("      8 bets in the last 30 minutes across different events")

        for ev_id, ev in velocity_events:
            if ev['sport'] == 'Football':
                selection = random.choices(['home', 'away', 'draw'], weights=[45, 35, 20])[0]
            else:
                selection = random.choices(['home', 'away'], weights=[50, 50])[0]

            if selection == 'home':
                odds = ev['home_odds']
            elif selection == 'away':
                odds = ev['away_odds']
            else:
                odds = ev['draw_odds']

            stake = round(random.uniform(50, 300), 2)
            potential_payout = round(stake * odds, 2)
            placed_at = fake.date_time_between(start_date='-30m', end_date='now')

            sql = """
                INSERT INTO bets
                (customer_id, event_id, selection, stake, odds, potential_payout, status, ip_address, placed_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'accepted', %s, %s)
            """
            cursor.execute(sql, (velocity_customer_id, ev_id, selection, stake, odds, potential_payout, velocity_ip, placed_at))

        print(f"      ✅ Velocity burst seeded for Customer #{velocity_customer_id} from IP {velocity_ip}")

        conn.commit()

        print("\n✅ Betting data seeded successfully!")
        print("   📊 Summary:")
        print(f"      • {len(event_ids)} betting events (Football, Basketball, Tennis)")
        print(f"      • ~60 baseline bets across all events")
        print(f"      • 12 liability concentration bets on Event #{liability_event_id} "
              f"({liability_event['home_team']} vs {liability_event['away_team']})")
        print(f"      • 8 velocity burst bets from Customer #{velocity_customer_id} (IP: {velocity_ip})")
        print("\n   🎯 Demo points to highlight:")
        print(f"      → Liability alert should fire on: Event #{liability_event_id} — "
              f"{liability_event['home_team']} vs {liability_event['away_team']}")
        print(f"      → Velocity anomaly: Customer #{velocity_customer_id} from IP {velocity_ip}")

    except Exception as e:
        print(f"❌ Error seeding betting data: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

if __name__ == "__main__":
    seed_betting_data()
