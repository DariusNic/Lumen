import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/finance_thesis")

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)

    ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

    # --- Email (SMTP) -----------------------------------------------------
    # Gmail by default. App Password required (Google rejects regular passwords).
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    # Friendly From header. Falls back to the SMTP username.
    MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Lumen")
    MAIL_FROM_ADDRESS = os.getenv("MAIL_FROM_ADDRESS", "") or os.getenv("SMTP_USERNAME", "")
    # When SMTP creds are missing OR MAIL_DRY_RUN=true, emails are logged to
    # stdout instead of sent. Keeps local dev frictionless and tests sane.
    MAIL_DRY_RUN = os.getenv("MAIL_DRY_RUN", "").lower() in ("1", "true", "yes")

    # Base URL for links rendered into email bodies. Points at the frontend.
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173")

    # Token TTLs (verification + password reset).
    EMAIL_VERIFICATION_TTL = timedelta(hours=24)
    PASSWORD_RESET_TTL = timedelta(hours=1)
