"""
Base de données — PostgreSQL (Supabase)
"""

import os
import asyncpg
import json
import jwt
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY   = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool

# ── INIT ───────────────────────────────────────────────────
async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Table utilisateurs
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                plan TEXT DEFAULT 'free',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Table deals
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id TEXT PRIMARY KEY,
                source TEXT,
                category TEXT,
                title TEXT,
                price FLOAT,
                market_price FLOAT,
                margin FLOAT,
                margin_pct FLOAT,
                deal_score INT,
                velocity TEXT,
                roi_pct FLOAT,
                grade TEXT,
                url TEXT,
                detected_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        print("[DB] Tables initialisées")

# ── USERS ──────────────────────────────────────────────────
async def get_user(email: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE email=$1", email)
        return dict(row) if row else None

async def create_user(email: str, password_hash: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING *",
            email, password_hash
        )
        return dict(row)

def verify_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None

# ── DEALS ──────────────────────────────────────────────────
async def save_deals(deals: list[dict]):
    if not deals:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        for d in deals:
            await conn.execute("""
                INSERT INTO deals (
                    id, source, category, title, price, market_price,
                    margin, margin_pct, deal_score, velocity, roi_pct, grade, url, detected_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (id) DO UPDATE SET
                    price=EXCLUDED.price,
                    market_price=EXCLUDED.market_price,
                    margin=EXCLUDED.margin,
                    deal_score=EXCLUDED.deal_score,
                    detected_at=EXCLUDED.detected_at
            """,
                d.get("id"), d.get("source"), d.get("category"),
                d.get("title"), float(d.get("price", 0)),
                float(d.get("market_price", 0)), float(d.get("marge", 0)),
                float(d.get("mpct", 0)), int(d.get("deal_score", 0)),
                d.get("vel", "?"), float(d.get("roi", 0)),
                d.get("grade", "?"), d.get("url", ""),
                datetime.utcnow()
            )

async def get_deals(cat="all", min_score=0, max_price=9999, limit=50):
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT * FROM deals
            WHERE deal_score >= $1
              AND price <= $2
              {}
            ORDER BY deal_score DESC
            LIMIT $3
        """.format("AND category = $4" if cat != "all" else "")

        if cat != "all":
            rows = await conn.fetch(query, min_score, max_price, limit, cat)
        else:
            rows = await conn.fetch(query, min_score, max_price, limit)

        return [dict(r) for r in rows]
