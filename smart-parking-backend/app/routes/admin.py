"""
ADMIN  -  monitoring and slot management   (SRS FR-13, FR-14, UC-08, UC-09 | SDD 5.8, 10.4)

Every endpoint here needs an ADMIN account (anyone else gets 403).

    GET /api/admin/summary        KPIs, zone status, occupancy trend   (alias: /api/admin/overview)
    GET /api/admin/bookings       all bookings, newest first, with filters + paging
    GET /api/admin/users          all registered users
    PUT /api/admin/slots/<id>     change a slot's status or hourly rate
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from ..auth_utils import admin_required
from ..db import get_db
from ..errors import ApiError
from ..serializers import booking_dict, user_dict
from ..services import (BOOKING_COLUMNS, BOOKING_FROM, SLOT_SELECT, now_window, slot_effective_statuses)
from ..utils import Validator, get_json_body, get_page_args, now_local, page_info, to_db

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

COUNTED = "('CONFIRMED', 'ACTIVE', 'COMPLETED')"   # bookings that are real and paid


def _hour_label(hour):
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


@bp.get("/summary")
@bp.get("/overview")
@admin_required
def summary():
    """
    Optional ?location_id=1 limits everything to one location.
    Optional ?date=2026-09-22 chooses the day for the booking/revenue/trend numbers (default today).
    """
    v = Validator(request.args)
    location_id = v.integer("location_id", "Location", minimum=1, required=False)
    day = v.date("date", "Date", required=False)
    v.done()

    db = get_db()
    now = now_local()
    day = day or now.date()
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    # -- slots & zones, right now -------------------------------------------
    sql, params = SLOT_SELECT, []
    if location_id:
        sql += " WHERE l.location_id = ?"
        params.append(location_id)
    slots = db.execute(sql + " ORDER BY l.location_id, z.zone_id, s.slot_id", params).fetchall()
    start, end = now_window(now)
    statuses = slot_effective_statuses(db, slots, start, end, now)

    zones = {}
    for s in slots:
        z = zones.setdefault(s["zone_id"], {"zone_id": s["zone_id"], "zone_name": s["zone_name"],
                                            "location_name": s["location_name"], "total_slots": 0, "free_slots": 0})
        z["total_slots"] += 1
        z["free_slots"] += int(statuses[s["slot_id"]] == "AVAILABLE")
    counts = list(statuses.values())

    # -- bookings & revenue for the chosen day --------------------------------
    loc_sql = " AND l.location_id = ?" if location_id else ""
    loc_params = [location_id] if location_id else []
    row = db.execute(
        f"""SELECT COUNT(*) AS bookings, COALESCE(SUM(b.total_amount), 0) AS revenue
            {BOOKING_FROM}
            WHERE b.status IN {COUNTED} AND b.start_time >= ? AND b.start_time < ?{loc_sql}""",
        [to_db(day_start), to_db(day_end), *loc_params]).fetchone()

    # -- occupancy trend: how many slots are in use at 8 AM, 10 AM ... 8 PM ---
    labels, values = [], []
    for hour in range(8, 21, 2):
        h_start = day_start + timedelta(hours=hour)
        used = db.execute(
            f"""SELECT COUNT(DISTINCT b.slot_id) {BOOKING_FROM}
                WHERE b.status IN {COUNTED} AND b.start_time < ? AND b.end_time > ?{loc_sql}""",
            [to_db(h_start + timedelta(hours=1)), to_db(h_start), *loc_params]).fetchone()[0]
        labels.append(_hour_label(hour))
        values.append(used)

    return jsonify({
        "date": day.isoformat(),
        "total_slots": len(slots),
        "occupied_slots": counts.count("OCCUPIED"),
        "available_slots": counts.count("AVAILABLE"),
        "reserved_slots": counts.count("RESERVED"),
        "out_of_service_slots": counts.count("OUT_OF_SERVICE"),
        "daily_bookings": row["bookings"],
        "daily_revenue": row["revenue"],
        "currency": "INR",
        "zones": list(zones.values()),
        "occupancy_trend": {"labels": labels, "values": values},
    })


@bp.get("/bookings")
@admin_required
def list_bookings():
    """Filters: status, q (id / user / location / slot), date=YYYY-MM-DD, location_id, page, per_page."""
    v = Validator(request.args)
    status = v.choice("status", "Status", {"PENDING", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED"}, required=False)
    search = v.text("q", "Search", required=False, max_len=40)
    day = v.date("date", "Date", required=False)
    location_id = v.integer("location_id", "Location", minimum=1, required=False)
    v.done()
    page, per_page, offset = get_page_args()

    where, params = ["1 = 1"], []
    if status:
        where.append("b.status = ?")
        params.append(status)
    if day:
        where.append("substr(b.start_time, 1, 10) = ?")
        params.append(day.isoformat())
    if location_id:
        where.append("l.location_id = ?")
        params.append(location_id)
    if search:
        like = f"%{search}%"
        where.append("(b.booking_id LIKE ? OR u.full_name LIKE ? OR u.email LIKE ? OR l.name LIKE ? OR s.slot_no LIKE ?)")
        params += [like] * 5

    db = get_db()
    clause = " WHERE " + " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) {BOOKING_FROM} {clause}", params).fetchone()[0]
    rows = db.execute(f"SELECT {BOOKING_COLUMNS} {BOOKING_FROM} {clause} ORDER BY b.created_at DESC, b.id DESC LIMIT ? OFFSET ?",
                      params + [per_page, offset]).fetchall()
    return jsonify({"bookings": [booking_dict(r, include_user=True) for r in rows],
                    "pagination": page_info(page, per_page, total)})


@bp.get("/users")
@admin_required
def list_users():
    page, per_page, offset = get_page_args()
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    rows = db.execute("SELECT * FROM users ORDER BY user_id LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    return jsonify({"users": [user_dict(r) for r in rows], "pagination": page_info(page, per_page, total)})


@bp.put("/slots/<int:slot_id>")
@admin_required
def update_slot(slot_id):
    """Change a slot's base status (e.g. close it for maintenance) and/or its hourly rate."""
    body = get_json_body()
    v = Validator(body)
    changes = {}
    if "status" in body:
        changes["status"] = v.choice("status", "Status", {"AVAILABLE", "OCCUPIED", "RESERVED", "OUT_OF_SERVICE"})
    if "rate_per_hour" in body:
        changes["rate_per_hour"] = v.integer("rate_per_hour", "Rate per hour", minimum=0, maximum=10000)
    if "description" in body:
        changes["description"] = v.text("description", "Description", required=False, max_len=60)
    v.done()
    if not changes:
        raise ApiError(422, "VALIDATION_ERROR", "Send at least one of: status, rate_per_hour, description.")

    db = get_db()
    if db.execute("SELECT 1 FROM parking_slots WHERE slot_id = ?", (slot_id,)).fetchone() is None:
        raise ApiError(404, "SLOT_NOT_FOUND", "That parking slot does not exist.")

    assignments = ", ".join(f"{column} = ?" for column in changes)   # column names are fixed above, not user input
    db.execute(f"UPDATE parking_slots SET {assignments} WHERE slot_id = ?", [*changes.values(), slot_id])

    # Closing a slot does NOT silently cancel people's bookings - we tell the admin how many are affected.
    affected = 0
    if changes.get("status") == "OUT_OF_SERVICE":
        affected = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE slot_id = ? AND status IN ('PENDING', 'CONFIRMED') AND start_time > ?",
            (slot_id, to_db(now_local()))).fetchone()[0]

    slot = db.execute(SLOT_SELECT + " WHERE s.slot_id = ?", (slot_id,)).fetchone()
    return jsonify({
        "slot": {"slot_id": slot["slot_id"], "slot_no": slot["slot_no"], "status": slot["base_status"],
                 "rate_per_hour": slot["rate_per_hour"], "description": slot["description"]},
        "upcoming_bookings_affected": affected,
    })
