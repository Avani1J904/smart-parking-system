"""
Settings for the backend.

Every value can be changed with an environment variable (see .env.example),
and every value has a sensible default so the project runs with zero setup.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    # --- Security -----------------------------------------------------------
    # Signs login tokens. The default is for local demos ONLY.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-change-me-before-real-use-0123456789")
    TOKEN_HOURS = int(os.environ.get("TOKEN_HOURS", 12))  # how long a login lasts

    # --- Database -----------------------------------------------------------
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "instance" / "parking.db"))
    AUTO_SEED = True  # fill an empty database with demo data on first start

    # --- Business rules (from the SRS / SDD) --------------------------------
    SERVICE_FEE = int(os.environ.get("SERVICE_FEE", 10))      # flat Rs. fee added to every booking
    HOLD_MINUTES = int(os.environ.get("HOLD_MINUTES", 10))    # slot is held this long during checkout
    MAX_DURATION_HOURS = 12                                   # longest single booking
    MAX_ADVANCE_DAYS = 30                                     # how far ahead a user may book
    MAX_PENDING_PER_USER = 3                                  # stops one user hoarding slots

    # --- Time ---------------------------------------------------------------
    # The whole system uses ONE local time zone (India, UTC+05:30), matching the
    # SDD example "2026-09-22T19:00:00+05:30". Times are stored without an offset
    # and the offset is added when sending data out.
    TZ_OFFSET_MINUTES = 330

    # --- Browser access -----------------------------------------------------
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
    FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "")
