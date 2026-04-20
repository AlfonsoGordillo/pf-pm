import os
import bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Request
from fastapi.responses import RedirectResponse

SECRET_KEY = os.getenv("SECRET_KEY", "projects-factory-pm-secret-2026")
ALGORITHM = "HS256"
EXPIRE_HOURS = 8

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=EXPIRE_HOURS)
    return jwt.encode({"sub": email, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

def auth_check(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return decode_token(token)
