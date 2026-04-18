"""
ArbitrageX — Serveur principal
================================
Lance avec : uvicorn main:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import asyncio
import os

from database import init_db, get_deals, save_deals, get_user, create_user, verify_token
from scanner import run_scan
from auth import create_token, hash_password, check_password
from pydantic import BaseModel

# ── DÉMARRAGE ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Lance le scan automatique en arrière-plan
    asyncio.create_task(scan_loop())
    yield

app = FastAPI(title="ArbitrageX API", lifespan=lifespan)

# Autoriser ton appli HTML à se connecter
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

# ── BOUCLE DE SCAN AUTO ────────────────────────────────────
async def scan_loop():
    interval = int(os.getenv("SCAN_INTERVAL_MINUTES", "5"))
    while True:
        try:
            print(f"[SCAN] Démarrage...")
            deals = await run_scan()
            await save_deals(deals)
            print(f"[SCAN] {len(deals)} deals sauvegardés")
        except Exception as e:
            print(f"[SCAN] Erreur: {e}")
        await asyncio.sleep(interval * 60)

# ── MODÈLES ────────────────────────────────────────────────
class RegisterBody(BaseModel):
    email: str
    password: str

class LoginBody(BaseModel):
    email: str
    password: str

# ── ROUTES AUTH ────────────────────────────────────────────
@app.post("/api/register")
async def register(body: RegisterBody):
    existing = await get_user(body.email)
    if existing:
        raise HTTPException(400, "Email déjà utilisé")
    hashed = hash_password(body.password)
    user = await create_user(body.email, hashed)
    token = create_token(user["id"], user["email"])
    return {"token": token, "email": user["email"], "plan": user["plan"]}

@app.post("/api/login")
async def login(body: LoginBody):
    user = await get_user(body.email)
    if not user or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Email ou mot de passe incorrect")
    token = create_token(user["id"], user["email"])
    return {"token": token, "email": user["email"], "plan": user["plan"]}

@app.get("/api/me")
async def me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Token manquant")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Token invalide")
    user = await get_user(payload["email"])
    return {"email": user["email"], "plan": user["plan"]}

# ── ROUTES DEALS ───────────────────────────────────────────
@app.get("/api/deals")
async def deals(
    cat: str = "all",
    min_score: int = 0,
    max_price: float = 9999,
    limit: int = 50,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    # Vérifier le token
    if not credentials:
        raise HTTPException(401, "Connecte-toi d'abord")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Session expirée")

    # Limiter selon le plan
    user = await get_user(payload["email"])
    plan = user.get("plan", "free")
    if plan == "free":
        limit = min(limit, 5)

    deals = await get_deals(cat=cat, min_score=min_score, max_price=max_price, limit=limit)
    return {"deals": deals, "total": len(deals), "plan": plan}

@app.get("/api/scan")
async def force_scan(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Non autorisé")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Token invalide")
    deals = await run_scan()
    await save_deals(deals)
    return {"message": f"{len(deals)} deals trouvés", "count": len(deals)}

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "ArbitrageX"}
