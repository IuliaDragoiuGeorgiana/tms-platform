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