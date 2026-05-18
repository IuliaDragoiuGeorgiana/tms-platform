from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
import secrets
import string
import hashlib


def hash_password(password: str) -> str:
    """Primește parola în clar, returnează hash-ul bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Compară parola introdusă cu hash-ul din DB. Returnează True/False."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: dict) -> str:
    """
    Generează un JWT token.
    data = {"sub": user_id, "role": "DISPECER", "company_id": "..."}
    Tokenul expiră după ACCESS_TOKEN_EXPIRE_MINUTES.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def generate_temporary_password(length: int = 12) -> str:
    """
    Generează o parolă temporară aleatoare pentru conturile invite.
    Conține litere mari, mici, cifre și un simbol.
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))

def generate_reset_token() -> str:
    """
    Generează un token random pentru resetarea parolei.
    Tokenul real se trimite pe email, iar în DB se salvează doar hash-ul.
    """
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """
    Hash-uiește tokenul de resetare folosind SHA-256.

    Tokenul este generat random, cu entropie mare, deci SHA-256 este potrivit
    pentru lookup rapid în baza de date. Pentru parole se folosește în continuare bcrypt.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reset_token_expiry() -> datetime:
    """
    Tokenul de resetare expiră după 15 minute.
    """
    return datetime.now(timezone.utc) + timedelta(minutes=15)