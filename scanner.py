"""
Scanner eBay + Moteur de scoring
"""

import httpx
import asyncio
import base64
import os
import math
from datetime import datetime

EBAY_CLIENT_ID     = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

KEYWORDS = {
    "consoles": ["nintendo switch", "ps5", "xbox series", "gameboy", "ps4"],
    "pokemon":  ["pokemon card", "dracaufeu", "pikachu carte", "booster pokemon"],
    "sneakers": ["jordan 1", "yeezy 350", "nike dunk", "air max 90"],
    "montres":  ["seiko skx", "casio g-shock", "omega", "tissot"],
}
CATEGORY_IDS = {
    "consoles": "139971",
    "pokemon":  "183454",
    "sneakers": "15709",
    "montres":  "31387",
}

POS_KW = ["très bon état","excellent","neuf","scellé","sealed","boîte","complet","psa","bgs"]
NEG_KW = ["vendu en l'état","pour pièces","défaut","rayé","cassé","ne fonctionne","incomplet"]

VEL = {
    "consoles": {"default":[1,7,3],"retro":[3,21,7]},
    "pokemon":  {"psa":[1,5,2],"sealed":[2,10,5],"holo":[3,15,7],"default":[5,30,14]},
    "sneakers": {"hype":[1,7,3],"default":[7,30,14]},
    "montres":  {"luxury":[14,90,30],"default":[10,45,20]},
}

# ── TOKEN EBAY ─────────────────────────────────────────────
_token = None
_token_exp = 0

async def get_token() -> str:
    global _token, _token_exp
    import time
    if _token and time.time() < _token_exp:
        return _token
    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope"
        )
        r.raise_for_status()
        data = r.json()
        _token = data["access_token"]
        _token_exp = time.time() + data["expires_in"] - 60
        return _token

# ── RECHERCHE EBAY ─────────────────────────────────────────
async def search_ebay(keyword: str, category: str) -> list[dict]:
    token = await get_token()
    cat_id = CATEGORY_IDS.get(category, "")
    params = {
        "q": keyword, "limit": "50", "sort": "newlyListed",
        "filter": "price:[0..800],priceCurrency:EUR",
    }
    if cat_id:
        params["category_ids"] = cat_id

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
            },
            params=params,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return [
            {
                "id":       item["itemId"],
                "source":   "ebay",
                "category": category,
                "title":    item.get("title", ""),
                "price":    float(item.get("price", {}).get("value", 0)),
                "url":      item.get("itemWebUrl", ""),
            }
            for item in data.get("itemSummaries", [])
        ]

# ── SCORING ────────────────────────────────────────────────
def vel_profile(title: str, cat: str) -> str:
    t = title.lower()
    if cat == "consoles":
        return "retro" if any(k in t for k in ["gameboy","snes","nes","megadrive","ps1","ps2","n64","3ds","gba"]) else "default"
    if cat == "pokemon":
        if any(k in t for k in ["psa","bgs"]): return "psa"
        if any(k in t for k in ["scellé","sealed","booster","coffret"]): return "sealed"
        if any(k in t for k in ["holo","full art"]): return "holo"
        return "default"
    if cat == "sneakers":
        return "hype" if any(k in t for k in ["jordan","dunk","yeezy"]) else "default"
    if cat == "montres":
        return "luxury" if any(k in t for k in ["rolex","omega","breitling","patek"]) else "default"
    return "default"

def score_deal(d: dict, market_price: float) -> dict | None:
    price = d.get("price", 0)
    if not market_price or market_price <= 0 or price <= 0 or price >= market_price:
        return None

    marge    = market_price - price
    mpct     = (marge / market_price) * 100
    roi      = (marge / price) * 100
    cat      = d.get("category", "")
    title    = d.get("title", "")

    s_marge  = min(max(60 * math.log(1 + mpct / 15) / math.log(1 + 100 / 15), 0), 60)

    profile  = vel_profile(title, cat)
    vel_data = (VEL.get(cat) or {}).get(profile) or (VEL.get(cat) or {}).get("default") or [14, 60, 30]
    avg_days = vel_data[2]
    vel_label = "Très rapide" if avg_days <= 3 else "Rapide" if avg_days <= 7 else "Moyen" if avg_days <= 21 else "Lent"
    s_vel    = 20 if avg_days <= 3 else 16 if avg_days <= 7 else 10 if avg_days <= 21 else 4

    tl       = title.lower()
    s_conf   = 12
    s_conf  += len([k for k in POS_KW if k in tl]) * 2
    s_conf  -= len([k for k in NEG_KW if k in tl]) * 3
    s_conf   = min(max(s_conf, 0), 20)

    total = round(s_marge + s_vel + s_conf)
    grade = "Excellent" if total >= 90 else "Très bon" if total >= 75 else "Correct" if total >= 60 else "Faible"

    return {
        **d,
        "market_price": round(market_price, 2),
        "marge":        round(marge, 0),
        "mpct":         round(mpct, 1),
        "roi":          round(roi, 1),
        "deal_score":   total,
        "vel":          vel_label,
        "grade":        grade,
        "detected_at":  datetime.utcnow().isoformat(),
    }

# ── SCAN COMPLET ───────────────────────────────────────────
async def run_scan() -> list[dict]:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        print("[SCAN] Clés eBay manquantes dans les variables d'environnement")
        return []

    all_raw = []

    for category, keywords in KEYWORDS.items():
        for kw in keywords[:2]:  # 2 keywords par catégorie pour rester dans les limites
            try:
                listings = await search_ebay(kw, category)
                all_raw.extend(listings)
                print(f"  [{category}] '{kw}' → {len(listings)} annonces")
            except Exception as e:
                print(f"  [{category}] '{kw}' → Erreur: {e}")
            await asyncio.sleep(0.5)

    # Déduplique
    seen, dedup = set(), []
    for d in all_raw:
        if d["id"] not in seen:
            seen.add(d["id"])
            dedup.append(d)

    # Calcul prix marché par catégorie (médiane × 1.15)
    by_cat: dict[str, list[float]] = {}
    for d in dedup:
        by_cat.setdefault(d["category"], []).append(d["price"])
    market_prices = {}
    for cat, prices in by_cat.items():
        s = sorted(p for p in prices if p > 0)
        if s:
            market_prices[cat] = s[len(s) // 2] * 1.15

    # Score
    scored = []
    for d in dedup:
        mp = market_prices.get(d["category"], 0)
        result = score_deal(d, mp)
        if result:
            scored.append(result)

    scored.sort(key=lambda x: x["deal_score"], reverse=True)
    print(f"[SCAN] {len(scored)} deals scorés sur {len(dedup)} annonces")
    return scored
