"""
Authentification — JWT + bcrypt
"""

import os
import jwt
import bcrypt
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub":   str(user_id),
        "email": email,
        "exp":   datetime.utcnow() + timedelta(days=30),
        "iat":   datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")
