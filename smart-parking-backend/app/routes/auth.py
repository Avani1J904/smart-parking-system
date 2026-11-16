"""
AUTHENTICATION  -  Register, Login, Logout   (SRS FR-01, FR-02 | SDD 9, 11)

    POST /api/auth/register   create an account
    POST /api/auth/login      get a login token
    POST /api/auth/logout     cancel the current token
    GET  /api/auth/me         who am I?
"""
import time

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from ..auth_utils import create_token, login_required, revoke_current_token
from ..db import get_db
from ..errors import ApiError
from ..serializers import user_dict
from ..utils import Validator, get_json_body, now_local, to_db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# --- Simple brute-force guard -------------------------------------------------
# After 5 wrong passwords for the same email from the same address, wait 5 minutes.
# (Kept in memory: fine for one server process; use Redis or the DB for many.)
_failed_logins = {}
MAX_ATTEMPTS, LOCK_SECONDS = 5, 300


def _attempt_key(email):
    return (request.remote_addr, email)


def _is_locked(key):
    recent = [t for t in _failed_logins.get(key, []) if time.time() - t < LOCK_SECONDS]
    _failed_logins[key] = recent
    return len(recent) >= MAX_ATTEMPTS


@bp.post("/register")
def register():
    v = Validator(get_json_body())
    full_name = v.text("full_name", "Full name", max_len=80)
    email = v.email()
    mobile = v.mobile()
    password = v.password()
    v.done()

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise ApiError(409, "EMAIL_EXISTS", "An account with this email already exists. Try logging in.",
                       {"email": "This email is already registered."})

    # The password is turned into an irreversible "hash" (with a random salt)
    # before saving. Even we can never read it back (SDD 11.2).
    cur = db.execute(
        """INSERT INTO users (full_name, email, mobile, password_hash, role, created_at)
           VALUES (?, ?, ?, ?, 'USER', ?)""",
        (full_name, email, mobile, generate_password_hash(password), to_db(now_local())),
    )
    user = db.execute("SELECT * FROM users WHERE user_id = ?", (cur.lastrowid,)).fetchone()
    token, expires_in = create_token(user)
    return jsonify({"user": user_dict(user), "token": token, "token_type": "Bearer", "expires_in": expires_in}), 201


@bp.post("/login")
def login():
    v = Validator(get_json_body())
    email = v.email()
    password = v.text("password", "Password", max_len=128)
    v.done()

    key = _attempt_key(email)
    if _is_locked(key):
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "Too many failed attempts. Please wait a few minutes and try again.")

    user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        _failed_logins.setdefault(key, []).append(time.time())
        # Same message for "no such email" and "wrong password" so attackers can't tell which.
        raise ApiError(401, "INVALID_CREDENTIALS", "Incorrect email or password.")

    _failed_logins.pop(key, None)
    token, expires_in = create_token(user)
    return jsonify({"user": user_dict(user), "token": token, "token_type": "Bearer", "expires_in": expires_in})


@bp.post("/logout")
@login_required
def logout():
    revoke_current_token()
    return jsonify({"message": "Logged out successfully."})


@bp.get("/me")
@login_required
def me():
    return jsonify({"user": user_dict(g.user)})
