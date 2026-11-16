"""
PAYMENTS  -  start and verify a payment   (SRS FR-10 | SDD 5.5, 12.2)

    POST /api/payments/create   start a payment for a PENDING booking
    POST /api/payments/verify   check the result; on success the booking is CONFIRMED + QR pass issued

Safety rules followed here:
  * The amount comes from OUR database, never from the browser.
  * A booking is only marked paid after the gateway check passes.
  * We never store card numbers or UPI PINs - only a reference number.
"""
import secrets

from flask import Blueprint, g, jsonify

from .. import payment_gateway
from ..auth_utils import login_required
from ..db import get_db, write_transaction
from ..errors import ApiError
from ..serializers import booking_dict, payment_dict
from ..services import get_booking_or_404
from ..utils import Validator, get_json_body, now_local, to_db

bp = Blueprint("payments", __name__, url_prefix="/api/payments")


def _explain_unpayable(booking):
    """Why can't this booking be paid? Give a helpful message."""
    if booking["status"] == "CANCELLED" and booking["cancel_reason"] == "HOLD_EXPIRED":
        return ApiError(409, "HOLD_EXPIRED", "Your 10-minute hold on this slot has expired. Please book again.")
    if booking["status"] in ("CONFIRMED", "ACTIVE", "COMPLETED"):
        return ApiError(409, "ALREADY_PAID", "This booking has already been paid for.")
    return ApiError(409, "BOOKING_NOT_PAYABLE", f"A {booking['status'].lower()} booking cannot be paid.")


@bp.post("/create")
@login_required
def create_payment():
    v = Validator(get_json_body())
    code = v.text("booking_id", "Booking ID", max_len=30)
    method = v.choice("method", "Payment method", {"UPI", "CARD"})
    v.done()

    db = get_db()
    with write_transaction(db):
        booking = get_booking_or_404(db, code, g.user)
        if booking["user_id"] != g.user["user_id"]:
            raise ApiError(403, "FORBIDDEN", "You can only pay for your own bookings.")
        if booking["status"] != "PENDING":
            raise _explain_unpayable(booking)

        # Pressing "Pay" twice must not create two payments: reuse the open one.
        payment = db.execute("SELECT * FROM payments WHERE booking_id = ? AND status = 'INITIATED'",
                             (booking["id"],)).fetchone()
        created = payment is None
        if created:
            cur = db.execute(
                """INSERT INTO payments (booking_id, method, transaction_ref, amount, status, created_at)
                   VALUES (?, ?, ?, ?, 'INITIATED', ?)""",
                (booking["id"], method, payment_gateway.create_order(method, booking["total_amount"]),
                 booking["total_amount"], to_db(now_local())))   # amount = server's own figure
            payment_id = cur.lastrowid
        else:
            payment_id = payment["payment_id"]
            db.execute("UPDATE payments SET method = ? WHERE payment_id = ?", (method, payment_id))
        payment = db.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()

    return jsonify({"payment": payment_dict(payment), "booking_id": booking["booking_id"],
                    "message": "Payment started. Complete it to confirm your booking."}), (201 if created else 200)


@bp.post("/verify")
@login_required
def verify_payment():
    body = get_json_body()
    v = Validator(body)
    payment_id = v.integer("payment_id", "Payment ID", minimum=1)
    v.done()

    db = get_db()
    payment = db.execute(
        "SELECT p.*, b.booking_id AS booking_code FROM payments p JOIN bookings b ON b.id = p.booking_id "
        "WHERE p.payment_id = ?", (payment_id,)).fetchone()
    booking = get_booking_or_404(db, payment["booking_code"], g.user) if payment else None
    if payment is None or booking["user_id"] != g.user["user_id"]:
        raise ApiError(404, "PAYMENT_NOT_FOUND", "We could not find that payment.")

    # Asking twice is harmless: report the existing result.
    if payment["status"] == "SUCCESS":
        return jsonify({"payment": payment_dict(payment), "booking": booking_dict(booking),
                        "message": "This payment was already confirmed."})
    if payment["status"] != "INITIATED":
        raise ApiError(409, "PAYMENT_CLOSED", f"This payment is {payment['status'].lower()}. Please start a new one.")
    if booking["status"] != "PENDING":
        raise _explain_unpayable(booking)

    ok, reason = payment_gateway.verify_payment(payment["method"], body)

    with write_transaction(db):
        if ok:
            db.execute("UPDATE payments SET status = 'SUCCESS', paid_at = ? WHERE payment_id = ?",
                       (to_db(now_local()), payment_id))
            # Payment confirmed -> booking confirmed, hold no longer needed, QR pass issued.
            db.execute("UPDATE bookings SET status = 'CONFIRMED', hold_expires_at = NULL, qr_token = ? WHERE id = ?",
                       (secrets.token_urlsafe(18), booking["id"]))
        else:
            db.execute("UPDATE payments SET status = 'FAILED' WHERE payment_id = ?", (payment_id,))

    payment = db.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
    booking = get_booking_or_404(db, booking["booking_id"], g.user)
    if not ok:
        # The booking stays PENDING, so the user can retry until the hold expires.
        raise ApiError(402, "PAYMENT_FAILED", reason, {"payment_status": "FAILED", "booking_status": booking["status"]})
    return jsonify({"payment": payment_dict(payment), "booking": booking_dict(booking),
                    "message": f"Payment successful. Booking {booking['booking_id']} confirmed."})
