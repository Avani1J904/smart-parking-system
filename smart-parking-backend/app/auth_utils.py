"""
Login tokens and "who is calling?" checks.

How login works, in plain words:
  1. The user sends email + password to POST /api/auth/login.
  2. If correct, we reply with a TOKEN (a signed pass that says "this is user 7").
  3. For every later request the browser sends:   Authorization: Bearer <token>
  4. The decorators below check the pass before the real work starts.

The frontend hiding a page is NOT security - these server checks are (SDD 11.1).
"""
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, request

from .db import get_db
from .errors import ApiError
from .utils import now_local, to_db


def create_token(user):
    """Make a signed token for this user. Returns (token, seconds_until_expiry)."""
    lifetime = timedelta(hours=current_app.config["TOKEN_HOURS"])
    issued = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["user_id"]),
        "role": user["role"],
        "jti": uuid.uuid4().hex,          # unique id, lets us revoke it on logout
        "iat": issued,
        "exp": issued + lifetime,
    }
    token = jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")
    return token, int(lifetime.total_seconds())


def _authenticate():
    """Read the Authorization header and return the user row, or raise 401."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or len(header) < 8:
        raise ApiError(401, "AUTH_REQUIRED", "Please log in to continue.")
    token = header[7:].strip()

    try:
        claims = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "Your session has expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise ApiError(401, "INVALID_TOKEN", "Your login is not valid. Please log in again.")

    db = get_db()
    if db.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (claims["jti"],)).fetchone():
        raise ApiError(401, "INVALID_TOKEN", "You have been logged out. Please log in again.")

    # Always re-read the user from the database so role changes / deletions apply at once.
    user = db.execute("SELECT * FROM users WHERE user_id = ?", (claims["sub"],)).fetchone()
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "This account no longer exists.")

    g.token_claims = claims
    return user


def login_required(view):
    """Put above a route to allow only logged-in users. The user is then in `g.user`."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        g.user = _authenticate()
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    """Like login_required, but only ADMIN accounts get through (403 otherwise)."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        g.user = _authenticate()
        if g.user["role"] != "ADMIN":
            raise ApiError(403, "FORBIDDEN", "Only administrators can do this.")
        return view(*args, **kwargs)
    return wrapper


def revoke_current_token():
    """Used by logout: remember this token's id so it can't be used again."""
    claims = g.token_claims
    expires = datetime.fromtimestamp(claims["exp"], timezone.utc).replace(tzinfo=None)
    db = get_db()
    db.execute("INSERT OR IGNORE INTO revoked_tokens (jti, expires_at) VALUES (?, ?)",
               (claims["jti"], to_db(expires)))
    # Tidy up: tokens that have expired anyway no longer need to be remembered.
    db.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (to_db(now_local() - timedelta(days=1)),))
