"""
Configuration settings loaded from environment variables.
NEVER hardcode secrets in this file.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==========================================
# JWT Settings
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError(
        "SECRET_KEY must be set in .env file. "
        "Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

ALGORITHM = os.getenv("ALGORITHM", "HS256")

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)

# ==========================================
# OpenRouteService API
# ==========================================
ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    raise ValueError(
        "ORS_API_KEY must be set in .env file. "
        "Get your API key from OpenRouteService."
    )

ORS_BASE_URL = os.getenv(
    "ORS_BASE_URL",
    "https://api.openrouteservice.org"
)

# ==========================================
# Email Settings (SMTP)
# ==========================================
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "True").lower() == "true"

# Frontend base URL for email links
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:4200")