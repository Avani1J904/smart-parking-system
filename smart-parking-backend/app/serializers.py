"""
Turn database rows into the JSON the frontend receives.

Keeping this in one place means every endpoint describes a booking/user/slot
in exactly the same way. Secrets (password hashes) are never included.
"""
from .utils import to_api


def user_dict(row):
    return {
        "user_id": row["user_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "mobile": row["mobile"],
        "role": row["role"],
        "city": row["city"],
        "vehicle_no": row["vehicle_no"],
        "notifications_enabled": bool(row["notifications_enabled"]),
        "member_since": row["created_at"][:4],
    }


def slot_dict(row, status):
    return {
        "slot_id": row["slot_id"],
        "slot_no": row["slot_no"],
        "status": status,                       # AVAILABLE / OCCUPIED / RESERVED / OUT_OF_SERVICE
        "vehicle_type": row["vehicle_type"],    # CAR / BIKE / EV
        "rate_per_hour": row["rate_per_hour"],
        "has_charger": bool(row["has_charger"]),
        "description": row["description"],
        "zone_id": row["zone_id"],
        "zone_name": row["zone_name"],
        "floor": row["floor"],
        "location_id": row["location_id"],
        "location_name": row["location_name"],
    }


def booking_dict(row, include_user=False):
    """
    The booking contract from SDD section 9.2, plus a few extra fields the
    History / Dashboard pages need.
    """
    data = {
        "booking_id": row["booking_id"],
        "status": row["status"],
        "location_id": row["location_id"],
        "location": row["location_name"],
        "zone": row["zone_name"],
        "floor": row["floor"],
        "slot_id": row["slot_id"],
        "slot_no": row["slot_no"],
        "vehicle_type": row["vehicle_type"],
        "vehicle_no": row["vehicle_no"],
        "start_time": to_api(row["start_time"]),
        "end_time": to_api(row["end_time"]),
        "duration_hours": row["duration_hours"],
        "parking_fee": row["parking_fee"],
        "service_fee": row["service_fee"],
        "total_amount": row["total_amount"],
        "currency": "INR",
        "payment_status": row["payment_status"] or "NOT_STARTED",
        "payment_method": row["payment_method"],
        "qr_token": row["qr_token"],
        "hold_expires_at": to_api(row["hold_expires_at"]) if row["status"] == "PENDING" else None,
        "special_request": row["special_request"],
        "rating": row["rating"],
        "created_at": to_api(row["created_at"]),
    }
    if include_user:
        data["user_id"] = row["user_id"]
        data["user_name"] = row["user_name"]
        data["user_email"] = row["user_email"]
    return data


def payment_dict(row):
    return {
        "payment_id": row["payment_id"],
        "method": row["method"],
        "transaction_ref": row["transaction_ref"],
        "amount": row["amount"],
        "currency": "INR",
        "status": row["status"],
        "created_at": to_api(row["created_at"]),
        "paid_at": to_api(row["paid_at"]),
    }
