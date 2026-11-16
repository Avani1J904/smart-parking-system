"""
BUSINESS RULES - the "brain" of the parking system.

Routes (in app/routes/) only receive requests and send answers. The rules about
prices, availability and booking lifecycle live here, so they are easy to find.
"""
from datetime import timedelta

from .errors import ApiError
from .utils import from_db, now_local, to_db

# ----------------------------------------------------------------------------
# Reusable SQL pieces
# ----------------------------------------------------------------------------
SLOT_SELECT = """
SELECT s.slot_id, s.slot_no, s.vehicle_type, s.status AS base_status, s.rate_per_hour,
       s.has_charger, s.description,
       z.zone_id, z.zone_name, z.floor,
       l.location_id, l.name AS location_name
FROM parking_slots s
JOIN parking_zones z     ON z.zone_id = s.zone_id
JOIN parking_locations l ON l.location_id = z.location_id
"""

BOOKING_COLUMNS = """
b.*, s.slot_no, z.zone_name, z.floor, l.location_id, l.name AS location_name,
u.full_name AS user_name, u.email AS user_email,
(SELECT p.status FROM payments p WHERE p.booking_id = b.id ORDER BY p.payment_id DESC LIMIT 1) AS payment_status,
(SELECT p.method FROM payments p WHERE p.booking_id = b.id ORDER BY p.payment_id DESC LIMIT 1) AS payment_method
"""

BOOKING_FROM = """
FROM bookings b
JOIN parking_slots s     ON s.slot_id = b.slot_id
JOIN parking_zones z     ON z.zone_id = s.zone_id
JOIN parking_locations l ON l.location_id = z.location_id
JOIN users u             ON u.user_id = b.user_id
"""

# Bookings that count as "this slot is taken" for an upcoming time window.
# (PENDING ones count too, but only while their 10-minute hold is alive.)
BLOCKING_STATUSES = ("CONFIRMED", "ACTIVE")


# ----------------------------------------------------------------------------
# Booking life-cycle:  PENDING -> CONFIRMED -> ACTIVE -> COMPLETED   (or CANCELLED)
# ----------------------------------------------------------------------------
def sync_booking_statuses(db, now=None):
    """
    Bring booking statuses up to date with the clock. Runs at the start of every
    API request, so no background job is needed.

      PENDING    + hold ran out        -> CANCELLED (reason HOLD_EXPIRED): slot is free again
      CONFIRMED  + start time reached  -> ACTIVE
      CONFIRMED/ACTIVE + end time over -> COMPLETED
    """
    now = now or now_local()
    t = to_db(now)
    db.execute(
        """UPDATE payments SET status = 'FAILED'
           WHERE status = 'INITIATED' AND booking_id IN
                 (SELECT id FROM bookings WHERE status = 'PENDING' AND hold_expires_at < ?)""", (t,))
    db.execute(
        """UPDATE bookings SET status = 'CANCELLED', cancel_reason = 'HOLD_EXPIRED', cancelled_at = ?
           WHERE status = 'PENDING' AND hold_expires_at < ?""", (t, t))
    db.execute(
        "UPDATE bookings SET status = 'ACTIVE' WHERE status = 'CONFIRMED' AND start_time <= ? AND end_time > ?", (t, t))
    db.execute(
        "UPDATE bookings SET status = 'COMPLETED' WHERE status IN ('CONFIRMED', 'ACTIVE') AND end_time <= ?", (t,))


# ----------------------------------------------------------------------------
# Money
# ----------------------------------------------------------------------------
def calculate_price(rate_per_hour, hours, service_fee):
    """
    The SERVER always works out the price (SDD 12.2) - a total sent by the browser
    is never trusted.   total = rate x hours + service fee
    """
    parking_fee = rate_per_hour * hours
    return {
        "parking_fee": parking_fee,
        "service_fee": service_fee,
        "total_amount": parking_fee + service_fee,
    }


# ----------------------------------------------------------------------------
# Time windows
# ----------------------------------------------------------------------------
def build_window(date_value, time_value, hours):
    """Combine a date, a start time and a duration into (start, end)."""
    from datetime import datetime
    start = datetime.combine(date_value, time_value)
    return start, start + timedelta(hours=hours)


def check_booking_window(start, now, max_days):
    """A booking must not start in the past, nor too far in the future."""
    if start < now - timedelta(minutes=5):
        raise ApiError(422, "VALIDATION_ERROR", "The start time is in the past.",
                       {"start_time": "Please choose a time that has not passed yet."})
    if start > now + timedelta(days=max_days):
        raise ApiError(422, "VALIDATION_ERROR", f"Bookings can be made at most {max_days} days ahead.",
                       {"date": f"Please choose a date within the next {max_days} days."})


# ----------------------------------------------------------------------------
# Availability  (SRS FR-05: Available / Occupied / Reserved)
# ----------------------------------------------------------------------------
def slot_effective_statuses(db, slots, start, end, now=None):
    """
    Work out each slot's status FOR A TIME WINDOW. Returns {slot_id: status}.

    Rules, in order:
      1. Slot closed for maintenance             -> OUT_OF_SERVICE
      2. Slot permanently set aside (priority)   -> RESERVED
      3. A booking overlaps the window           -> OCCUPIED if that booking is under way
                                                    right now, otherwise RESERVED
      4. Sensor says a vehicle is there AND the window includes "now" -> OCCUPIED
      5. Otherwise                               -> AVAILABLE

    Two time ranges overlap when each one starts before the other one ends:
        booking.start < window.end   AND   booking.end > window.start
    """
    now = now or now_local()
    rows = db.execute(
        """SELECT slot_id, status FROM bookings
           WHERE start_time < ? AND end_time > ?
             AND (status IN ('CONFIRMED', 'ACTIVE') OR (status = 'PENDING' AND hold_expires_at > ?))""",
        (to_db(end), to_db(start), to_db(now)),
    ).fetchall()

    busy = {}  # slot_id -> "OCCUPIED" or "RESERVED"
    for row in rows:
        if row["status"] == "ACTIVE":
            busy[row["slot_id"]] = "OCCUPIED"
        else:
            busy.setdefault(row["slot_id"], "RESERVED")

    window_includes_now = start <= now < end
    result = {}
    for slot in slots:
        base = slot["base_status"]
        if base == "OUT_OF_SERVICE":
            status = "OUT_OF_SERVICE"
        elif base == "RESERVED":
            status = "RESERVED"
        elif slot["slot_id"] in busy:
            status = busy[slot["slot_id"]]
        elif base == "OCCUPIED" and window_includes_now:
            status = "OCCUPIED"
        else:
            status = "AVAILABLE"
        result[slot["slot_id"]] = status
    return result


def now_window(now=None):
    """A tiny window meaning 'right now' - used for live counts."""
    now = now or now_local()
    return now, now + timedelta(minutes=1)


# ----------------------------------------------------------------------------
# Booking lookups
# ----------------------------------------------------------------------------
def get_booking_or_404(db, booking_code, user):
    """
    Fetch a booking by its friendly code. Drivers can only see their own bookings;
    for anyone else's we answer "not found" (we don't even confirm it exists).
    """
    row = db.execute(f"SELECT {BOOKING_COLUMNS} {BOOKING_FROM} WHERE b.booking_id = ?", (booking_code,)).fetchone()
    if row is None or (row["user_id"] != user["user_id"] and user["role"] != "ADMIN"):
        raise ApiError(404, "BOOKING_NOT_FOUND", "We could not find that booking.")
    return row


def booking_is_in_future(row, now=None):
    return from_db(row["start_time"]) > (now or now_local())
