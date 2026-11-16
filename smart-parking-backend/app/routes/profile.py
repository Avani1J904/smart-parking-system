"""
PROFILE  -  view and update my account   (SRS FR-12 | SDD 5.7)

    GET /api/profile    my details
    PUT /api/profile    change any of: full_name, email, mobile, city, vehicle_no, notifications_enabled
"""
from flask import Blueprint, g, jsonify

from ..auth_utils import login_required
from ..db import get_db
from ..errors import ApiError
from ..serializers import user_dict
from ..utils import Validator, get_json_body

bp = Blueprint("profile", __name__, url_prefix="/api/profile")


def _profile_response(db):
    user = db.execute("SELECT * FROM users WHERE user_id = ?", (g.user["user_id"],)).fetchone()
    count = db.execute("SELECT COUNT(*) FROM bookings WHERE user_id = ? AND status IN ('CONFIRMED','ACTIVE','COMPLETED')",
                       (user["user_id"],)).fetchone()[0]
    return jsonify({"user": user_dict(user), "total_bookings": count})


@bp.get("")
@login_required
def get_profile():
    return _profile_response(get_db())


@bp.put("")
@login_required
def update_profile():
    body = get_json_body()
    v = Validator(body)
    changes = {}
    # Only fields that were actually sent are changed.
    if "full_name" in body:
        changes["full_name"] = v.text("full_name", "Full name", max_len=80)
    if "email" in body:
        changes["email"] = v.email()
    if "mobile" in body:
        changes["mobile"] = v.mobile()
    if "city" in body:
        changes["city"] = v.text("city", "City", required=False, max_len=60)
    if "vehicle_no" in body:
        changes["vehicle_no"] = v.vehicle_no(required=False)
    if "notifications_enabled" in body:
        flag = v.boolean("notifications_enabled", "Notifications")
        changes["notifications_enabled"] = None if flag is None else int(flag)
    v.done()

    if not changes:
        raise ApiError(422, "VALIDATION_ERROR", "Nothing to update. Send at least one field to change.")

    db = get_db()
    if "email" in changes:
        clash = db.execute("SELECT 1 FROM users WHERE email = ? AND user_id != ?",
                           (changes["email"], g.user["user_id"])).fetchone()
        if clash:
            raise ApiError(409, "EMAIL_EXISTS", "Another account already uses this email.",
                           {"email": "This email is already registered."})

    # Column names come from our own fixed list above (never from the user), so this is safe.
    assignments = ", ".join(f"{column} = ?" for column in changes)
    db.execute(f"UPDATE users SET {assignments} WHERE user_id = ?", [*changes.values(), g.user["user_id"]])
    return _profile_response(db)
