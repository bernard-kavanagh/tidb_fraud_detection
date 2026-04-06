-- Sports Betting Extension Schema
-- Run this AFTER schema.sql has been executed.
-- Creates the betting_events and bets tables with TiFlash replicas for HTAP demos.

-- ==========================================
-- SPORTS BETTING TABLES
-- ==========================================

-- Betting Events: Fixtures available for wagering
CREATE TABLE IF NOT EXISTS betting_events (
    event_id    INT AUTO_INCREMENT PRIMARY KEY,
    sport       VARCHAR(50),                        -- e.g. 'Football', 'Basketball', 'Tennis'
    home_team   VARCHAR(100),
    away_team   VARCHAR(100),
    league      VARCHAR(100),                       -- e.g. 'Premier League', 'NBA'
    event_time  DATETIME,
    status      VARCHAR(20) DEFAULT 'active',       -- values: active, suspended, settled
    home_odds   DECIMAL(6,3),
    away_odds   DECIMAL(6,3),
    draw_odds   DECIMAL(6,3)                        -- NULL for sports with no draw
);

-- Bets: Individual wagers placed by customers
CREATE TABLE IF NOT EXISTS bets (
    bet_id          INT AUTO_INCREMENT PRIMARY KEY,
    customer_id     INT,                            -- references customers table (no FK constraint for demo simplicity)
    event_id        INT,                            -- references betting_events
    selection       VARCHAR(20),                    -- 'home', 'away', 'draw'
    stake           DECIMAL(10,2),
    odds            DECIMAL(6,3),
    potential_payout DECIMAL(10,2),                 -- stake * odds, computed at insert time
    status          VARCHAR(20) DEFAULT 'accepted', -- values: accepted, voided, suspended
    ip_address      VARCHAR(45),
    placed_at       DATETIME DEFAULT NOW()
);

-- ==========================================
-- TIFLASH REPLICAS (HTAP)
-- ==========================================

ALTER TABLE betting_events SET TIFLASH REPLICA 1;
ALTER TABLE bets SET TIFLASH REPLICA 1;
