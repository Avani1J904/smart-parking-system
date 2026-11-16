"""
BOOKINGS  -  reserve, view, cancel, history, receipts   (SRS FR-08, FR-09, FR-11 | SDD 10.2)

    GET    /api/bookings/quote            price preview before booking
    POST   /api/bookings                  reserve a slot (held for 10 minutes until paid)
    GET    /api/bookings/history          my bookings (search, status, month, paging)
    GET    /api/bookings                  same as /history  (name used in the SRS)
    GET    /api/bookings/<id>             one booking
    DELETE /api/bookings/<id>             cancel (refund if already paid)
    GET    /api/bookings/<id>/receipt     receipt for a paid booking
    POST   /api/bookings/<id>/rating      rate a completed booking (1-5)

THE BOOKING FLOW IN ONE PICTURE
    Find slot -> POST /api/bookings  -> booking is PENDING, slot HELD 10 minutes
              -> POST /api/payments/create + /verify
              -> booking becomes CONFIRMED and gets a QR pass
    If nobody pays within 10 minutes the hold lapses and the slot is free again.
"""
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, request

from ..auth_utils import login_required
from ..db import get_db, write_transaction
from ..errors import ApiError
from ..serializers import booking_dict, payment_dict
from ..services import (BOOKING_COLUMNS, BOOKING_FROM, SLOT_SELECT, booking_is_in_future, build_window,
                        calculate_price, check_booking_window, get_booking_or_404, slot_effective_statuses)
from ..utils import Validator, get_json_body, get_page_args, now_local, page_info, to_api, to_db

bp = Blueprint("bookings", __name__, url_prefix="/api/bookings")

VEHICLE_ALIASES = {"EV_CAR": "EV"}   # the booking form says "EV Car"


def _slot_or_404(db, slot_id):
    slot = db.execute(SLOT_SELECT + " WHERE s.slot_id = ?", (slot_id,)).fetchone()
    if slot is None:
        raise ApiError(404, "SLOT_NOT_FOUND", "That parking slot does not exist.")
    return slot


@bp.get("/quote")
def quote():
    """Price preview used by the 'Booking Summary' panel. Nothing is saved."""
    v = Validator(request.args)
    slot_id = v.integer("slot_id", "Slot", minimum=1)
    hours = v.integer("duration_hours", "Duration", minimum=1, maximum=current_app.config["MAX_DURATION_HOURS"])
    v.done()
    slot = _slot_or_404(get_db(), slot_id)
    price = calculate_price(slot["rate_per_hour"], hours, current_app.config["SERVICE_FEE"])
    return jsonify({"slot_id": slot_id, "slot_no": slot["slot_no"], "rate_per_hour": slot["rate_per_hour"],
                    "duration_hours": hours, "currency": "INR", **price})


@bp.post("")
@login_required
def create_booking():
    cfg = current_app.config
    v = Validator(get_json_body())
    slot_id = v.integer("slot_id", "Slot", minimum=1)
    vehicle_type = v.choice("vehicle_type", "Vehicle type", {"CAR", "BIKE", "EV"}, aliases=VEHICLE_ALIASES)
    vehicle_no = v.vehicle_no()
    day = v.date("date", "Date")
    start_time = v.time("start_time", "Start time")
    hours = v.integer("duration_hours", "Duration", minimum=1, maximum=cfg["MAX_DURATION_HOURS"])
    note = v.text("special_request", "Special request", required=False, max_len=250)
    v.done()

    now = now_local()
    start, end = build_window(day, start_time, hours)
    check_booking_window(start, now, cfg["MAX_ADVANCE_DAYS"])

    db = get_db()
    # Everything below happens as ONE locked step, so two people cannot grab the same slot.
    with write_transaction(db):
        slot = _slot_or_404(db, slot_id)

        if slot["vehicle_type"] != vehicle_type:
            raise ApiError(422, "VEHICLE_MISMATCH",
                           f"Slot {slot['slot_no']} is for {slot['vehicle_type']} vehicles, not {vehicle_type}.",
                           {"vehicle_type": "This slot does not fit that vehicle type."})

        # Final availability check (SDD 5.4 / SRS 11): the screen may be out of date.
        status = slot_effective_statuses(db, [slot], start, end, now)[slot_id]
        if status != "AVAILABLE":
            raise ApiError(409, "SLOT_TAKEN",
                           "Sorry, this slot is no longer available for that time. Please pick another slot.",
                           {"slot_status": status})

        pending = db.execute("SELECT COUNT(*) FROM bookings WHERE user_id = ? AND status = 'PENDING'",
                             (g.user["user_id"],)).fetchone()[0]
        if pending >= cfg["MAX_PENDING_PER_USER"]:
            raise ApiError(429, "TOO_MANY_PENDING",
                           "You have several unpaid bookings. Please pay for or cancel them first.")

        price = calculate_price(slot["rate_per_hour"], hours, cfg["SERVICE_FEE"])
        new_id = db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM bookings").fetchone()[0]
        code = f"PK-{now.year}-{new_id:05d}"                   # e.g. PK-2026-00188
        db.execute(
            """INSERT INTO bookings (id, booking_id, user_id, slot_id, vehicle_type, vehicle_no, start_time, end_time,
                                     duration_hours, special_request, parking_fee, service_fee, total_amount,
                                     status, hold_expires_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING', ?, ?)""",
            (new_id, code, g.user["user_id"], slot_id, vehicle_type, vehicle_no, to_db(start), to_db(end),
             hours, note, price["parking_fee"], price["service_fee"], price["total_amount"],
             to_db(now + timedelta(minutes=cfg["HOLD_MINUTES"])), to_db(now)),
        )

    booking = get_booking_or_404(db, code, g.user)
    return jsonify({"booking": booking_dict(booking),
                    "message": f"Slot held for {cfg['HOLD_MINUTES']} minutes. Complete payment to confirm."}), 201


@bp.get("/history")
@bp.get("")
@login_required
def history():
    """
    Filters (all optional):
        status=ACTIVE|COMPLETED|CANCELLED|CONFIRMED|PENDING
        month=2026-09            only bookings starting in that month
        q=text                   searches booking id, location, slot number, vehicle number
        page, per_page           paging
    """
    v = Validator(request.args)
    status = v.choice("status", "Status", {"PENDING", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED"}, required=False)
    month = v.text("month", "Month", required=False, max_len=7)
    search = v.text("q", "Search", required=False, max_len=40)
    if month and not _valid_month(month):
        v.errors["month"] = "Month must look like 2026-09."
    v.done()
    page, per_page, offset = get_page_args()

    # Unpaid bookings whose 10-minute hold ran out are not shown - they never really happened.
    where = ["b.user_id = ?", "NOT (b.status = 'CANCELLED' AND b.cancel_reason = 'HOLD_EXPIRED')"]
    params = [g.user["user_id"]]
    if status:
        where.append("b.status = ?")
        params.append(status)
    if month:
        where.append("substr(b.start_time, 1, 7) = ?")
        params.append(month)
    if search:
        like = f"%{search}%"
        where.append("(b.booking_id LIKE ? OR l.name LIKE ? OR s.slot_no LIKE ? OR b.vehicle_no LIKE ?)")
        params += [like] * 4

    db = get_db()
    clause = " WHERE " + " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) {BOOKING_FROM} {clause}", params).fetchone()[0]
    rows = db.execute(f"SELECT {BOOKING_COLUMNS} {BOOKING_FROM} {clause} ORDER BY b.start_time DESC LIMIT ? OFFSET ?",
                      params + [per_page, offset]).fetchall()
    return jsonify({"bookings": [booking_dict(r) for r in rows], "pagination": page_info(page, per_page, total)})


def _valid_month(text):
    try:
        from datetime import datetime
        datetime.strptime(text, "%Y-%m")
        return True
    except ValueError:
        return False


@bp.get("/<booking_id>")
@login_required
def get_booking(booking_id):
    db = get_db()
    row = get_booking_or_404(db, booking_id, g.user)
    payments = db.execute("SELECT * FROM payments WHERE booking_id = ? ORDER BY payment_id", (row["id"],)).fetchall()
    return jsonify({"booking": booking_dict(row), "payments": [payment_dict(p) for p in payments]})


@bp.delete("/<booking_id>")
@login_required
def cancel_booking(booking_id):
    db = get_db()
    with write_transaction(db):
        row = get_booking_or_404(db, booking_id, g.user)
        if row["status"] not in ("PENDING", "CONFIRMED") or not booking_is_in_future(row):
            raise ApiError(409, "CANNOT_CANCEL",
                           "Only bookings that have not started yet can be cancelled.", {"status": row["status"]})

        refunded = False
        paid = db.execute("SELECT payment_id FROM payments WHERE booking_id = ? AND status = 'SUCCESS'",
                          (row["id"],)).fetchone()
        if paid:   # money was taken -> give it back (pretend gateway: instant full refund)
            db.execute("UPDATE payments SET status = 'REFUNDED' WHERE payment_id = ?", (paid["payment_id"],))
            refunded = True
        db.execute("UPDATE payments SET status = 'FAILED' WHERE booking_id = ? AND status = 'INITIATED'", (row["id"],))

        reason = "ADMIN_CANCELLED" if g.user["role"] == "ADMIN" and row["user_id"] != g.user["user_id"] else "USER_CANCELLED"
        db.execute("UPDATE bookings SET status = 'CANCELLED', cancel_reason = ?, cancelled_at = ?, qr_token = NULL "
                   "WHERE id = ?", (reason, to_db(now_local()), row["id"]))

    updated = get_booking_or_404(db, booking_id, g.user)
    return jsonify({"booking": booking_dict(updated), "refunded": refunded,
                    "message": "Booking cancelled." + (" Your payment will be refunded." if refunded else "")})


@bp.get("/<booking_id>/receipt")
@login_required
def receipt(booking_id):
    db = get_db()
    row = get_booking_or_404(db, booking_id, g.user)
    pay = db.execute("SELECT * FROM payments WHERE booking_id = ? AND status IN ('SUCCESS', 'REFUNDED') "
                     "ORDER BY payment_id DESC LIMIT 1", (row["id"],)).fetchone()
    if pay is None:
        raise ApiError(409, "NO_RECEIPT", "A receipt is available only after a successful payment.")
    return jsonify({
        "receipt_no": f"RC-{row['booking_id']}",
        "issued_to": {"name": row["user_name"], "email": row["user_email"]},
        "booking": booking_dict(row),
        "payment": payment_dict(pay),
        "issued_at": to_api(to_db(now_local())),
    })


@bp.post("/<booking_id>/rating")
@login_required
def rate_booking(booking_id):
    v = Validator(get_json_body())
    rating = v.integer("rating", "Rating", minimum=1, maximum=5)
    v.done()
    db = get_db()
    row = get_booking_or_404(db, booking_id, g.user)
    if row["user_id"] != g.user["user_id"]:
        raise ApiError(403, "FORBIDDEN", "You can only rate your own bookings.")
    if row["status"] != "COMPLETED":
        raise ApiError(409, "NOT_COMPLETED", "You can rate a booking once the parking time is over.")
    db.execute("UPDATE bookings SET rating = ? WHERE id = ?", (rating, row["id"]))
    return jsonify({"booking": booking_dict(get_booking_or_404(db, booking_id, g.user))})
