from datetime import datetime, timedelta, timezone
from hashlib import sha256

import bcrypt
import jwt

from app.core.config import get_settings

ACCESS_TOKEN_TTL = timedelta(hours=12)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "iat": now, "exp": now + ACCESS_TOKEN_TTL},
        get_settings().jwt_secret.get_secret_value(), algorithm="HS256",
    )


def decode_token(token: str) -> dict:
    return jwt.decode(
        token, get_settings().jwt_secret.get_secret_value(), algorithms=["HS256"],
        options={"require": ["sub", "iat", "exp"]},
    )
