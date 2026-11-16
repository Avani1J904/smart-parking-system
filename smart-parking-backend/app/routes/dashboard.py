"""
USER DASHBOARD  -  everything the dashboard page shows, in ONE call   (SRS FR-03 | SDD 10.3)

    GET /api/dashboard

Returns:
    stats            active bookings, total bookings, total spent, average rating
    active_booking   the booking in progress now, or the next upcoming one (or null)
    quick_stats      this month's booked hours and average stay
    recent_bookings  the last three bookings

Not included (they need real gate/sensor data, listed as future work in the SRS):
    "on-time exit %" and "parking usage %".
"""
from flask import Blueprint, g, jsonify

from ..auth_utils import login_required
from ..db import get_db
from ..serializers import booking_dict
from ..services import BOOKING_COLUMNS, BOOKING_FROM
from ..utils import now_local

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")

# Bookings that really happened or will happen (not cancelled / unpaid).
REAL = "b.user_id = ? AND b.status IN ('CONFIRMED', 'ACTIVE', 'COMPLETED')"


@bp.get("")
@login_required
def dashboard():
    db = get_db()
    uid = g.user["user_id"]
    month = now_local().strftime("%Y-%m")

    totals = db.execute(
        f"""SELECT COUNT(*) AS total_bookings,
                   COALESCE(SUM(b.total_amount), 0) AS total_spent,
                   SUM(CASE WHEN b.status IN ('CONFIRMED', 'ACTIVE') THEN 1 ELSE 0 END) AS active_bookings,
                   AVG(b.rating) AS average_rating
            FROM bookings b WHERE {REAL}""", (uid,)).fetchone()

    month_stats = db.execute(
        f"""SELECT COALESCE(SUM(b.duration_hours), 0) AS booked_hours, AVG(b.duration_hours) AS avg_stay
            FROM bookings b WHERE {REAL} AND substr(b.start_time, 1, 7) = ?""", (uid, month)).fetchone()

    # "Active" first (under way now), otherwise the soonest upcoming confirmed one.
    active = db.execute(
        f"""SELECT {BOOKING_COLUMNS} {BOOKING_FROM}
            WHERE b.user_id = ? AND b.status IN ('ACTIVE', 'CONFIRMED')
            ORDER BY CASE b.status WHEN 'ACTIVE' THEN 0 ELSE 1 END, b.start_time LIMIT 1""", (uid,)).fetchone()

    recent = db.execute(
        f"""SELECT {BOOKING_COLUMNS} {BOOKING_FROM}
            WHERE b.user_id = ? AND NOT (b.status = 'CANCELLED' AND b.cancel_reason = 'HOLD_EXPIRED')
            ORDER BY b.start_time DESC LIMIT 3""", (uid,)).fetchall()

    return jsonify({
        "user": {"full_name": g.user["full_name"], "first_name": g.user["full_name"].split()[0]},
        "stats": {
            "active_bookings": totals["active_bookings"] or 0,
            "total_bookings": totals["total_bookings"],
            "total_spent": totals["total_spent"],
            "average_rating": round(totals["average_rating"], 1) if totals["average_rating"] else None,
        },
        "active_booking": booking_dict(active) if active else None,
        "quick_stats": {
            "month": month,
            "booked_hours": month_stats["booked_hours"],
            "average_stay_hours": round(month_stats["avg_stay"], 1) if month_stats["avg_stay"] else 0,
        },
        "recent_bookings": [booking_dict(r) for r in recent],
    })
