"""
DEMO DATA  -  fills an empty database so every page has something to show.

Mirrors the frontend prototype: three locations (City Center, Mall, Railway),
Zone A with slots A-01 ... A-32, a demo driver "Aarav Sharma", and an admin.

Demo logins (also listed in README.md):
    Admin :  admin@parkease.com   /  Admin@123
    Driver:  aarav@example.com    /  User@1234
"""
import random
import secrets
from datetime import timedelta

from werkzeug.security import generate_password_hash

from .services import calculate_price
from .utils import now_local, to_db

# Hourly rates (Rs.) per location and vehicle type. City Center car = Rs. 60 like the prototype.
RATES = {
    "City Center Parking": {"CAR": 60, "BIKE": 20, "EV": 80},
    "Mall Parking":        {"CAR": 80, "BIKE": 25, "EV": 100},
    "Railway Parking":     {"CAR": 40, "BIKE": 15, "EV": 60},
}

# The first 12 slots of Zone A are copied from the Find Parking page of the frontend.
# (vehicle type, description, has charger, base status)
ZONE_A_FIRST_12 = [
    ("CAR", "Near Entry", 0, "AVAILABLE"), ("CAR", "Standard", 0, "OCCUPIED"), ("CAR", "Covered", 0, "AVAILABLE"),
    ("EV", "Charger nearby", 1, "AVAILABLE"), ("CAR", "Standard", 0, "OCCUPIED"), ("BIKE", "Two-wheeler", 0, "AVAILABLE"),
    ("CAR", "Priority", 0, "RESERVED"), ("CAR", "Standard", 0, "AVAILABLE"), ("CAR", "Covered", 0, "AVAILABLE"),
    ("CAR", "Standard", 0, "OCCUPIED"), ("EV", "Charger nearby", 1, "AVAILABLE"), ("CAR", "Near Exit", 0, "AVAILABLE"),
]

# (location, address, [(zone name, floor, slot prefix, how many slots, style), ...])
LAYOUT = [
    ("City Center Parking", "Main Gate, MG Road, Indore",
     [("Zone A", "Ground Floor", "A", 32, "zone_a"), ("Zone B", "First Floor", "B", 20, "cars"),
      ("EV Zone", "Ground Floor", "E", 8, "ev")]),
    ("Mall Parking", "Mall Road, Indore", [("Zone C", "Basement 1", "C", 24, "cars")]),
    ("Railway Parking", "Station Road, Indore", [("Zone R", "Open Lot", "R", 20, "mixed")]),
]


def _slot_specs(prefix, count, style):
    """Return [(slot_no, vehicle_type, description, has_charger, status), ...] for one zone."""
    specs = []
    for i in range(1, count + 1):
        if style == "zone_a" and i <= len(ZONE_A_FIRST_12):
            vtype, desc, charger, status = ZONE_A_FIRST_12[i - 1]
        elif style == "ev":
            vtype, desc, charger, status = "EV", "Charger bay", 1, "AVAILABLE"
        elif style == "mixed" and i % 3 == 0:
            vtype, desc, charger, status = "BIKE", "Two-wheeler", 0, "AVAILABLE"
        else:
            vtype, desc, charger, status = "CAR", ("Covered" if i % 5 == 0 else "Standard"), 0, "AVAILABLE"
        specs.append((f"{prefix}-{i:02d}", vtype, desc, charger, status))
    return specs


def seed_database(db):
    """Insert demo users, parking inventory and bookings. Safe to call once on an empty database."""
    now = now_local()
    rng = random.Random(42)  # fixed seed -> the same demo data every time

    # ---- users ------------------------------------------------------------------
    def add_user(name, email, mobile, password, role="USER", city="Indore", vehicle=None):
        return db.execute(
            """INSERT INTO users (full_name, email, mobile, password_hash, role, city, vehicle_no, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, email, mobile, generate_password_hash(password), role, city, vehicle, to_db(now))).lastrowid

    add_user("Parking Admin", "admin@parkease.com", "9000000001", "Admin@123", role="ADMIN")
    aarav = add_user("Aarav Sharma", "aarav@example.com", "9123456789", "User@1234", vehicle="MP09AB1234")
    riya = add_user("Riya Sharma", "riya@example.com", "9123456780", "User@1234", vehicle="MP09CD8899")
    arjun = add_user("Arjun Mehta", "arjun@example.com", "9123456781", "User@1234", vehicle="MP09XY1100")
    others = [riya, arjun]

    # ---- locations, zones, slots ---------------------------------------------------
    slot_ids = {}  # slot_no -> slot_id, only needed for the City Center zones below
    car_slots_city = []
    for loc_name, address, zones in LAYOUT:
        loc_id = db.execute("INSERT INTO parking_locations (name, address) VALUES (?, ?)", (loc_name, address)).lastrowid
        for zone_name, floor, prefix, count, style in zones:
            zone_id = db.execute("INSERT INTO parking_zones (location_id, zone_name, floor) VALUES (?, ?, ?)",
                                 (loc_id, zone_name, floor)).lastrowid
            for slot_no, vtype, desc, charger, status in _slot_specs(prefix, count, style):
                sid = db.execute(
                    """INSERT INTO parking_slots (zone_id, slot_no, vehicle_type, status, rate_per_hour, has_charger, description)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (zone_id, slot_no, vtype, status, RATES[loc_name][vtype], charger, desc)).lastrowid
                if loc_name == "City Center Parking":
                    slot_ids[slot_no] = sid
                    if vtype == "CAR" and status == "AVAILABLE":
                        car_slots_city.append(sid)

    # ---- bookings ------------------------------------------------------------------
    def slot_row(slot_id):
        return db.execute("SELECT vehicle_type, rate_per_hour FROM parking_slots WHERE slot_id = ?", (slot_id,)).fetchone()

    def conflicts(slot_id, start, end):
        return db.execute("SELECT 1 FROM bookings WHERE slot_id = ? AND status != 'CANCELLED' AND start_time < ? AND end_time > ?",
                          (slot_id, to_db(end), to_db(start))).fetchone() is not None

    def add_booking(user_id, slot_id, vehicle_no, start, hours, status="CONFIRMED", rating=None):
        """Insert a finished, paid booking (statuses update themselves as time passes)."""
        end = start + timedelta(hours=hours)
        if conflicts(slot_id, start, end):
            return
        slot = slot_row(slot_id)
        price = calculate_price(slot["rate_per_hour"], hours, 10)
        next_id = db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM bookings").fetchone()[0]
        code = f"PK-{start.year}-{next_id:05d}"
        paid = status != "CANCELLED"
        db.execute(
            """INSERT INTO bookings (id, booking_id, user_id, slot_id, vehicle_type, vehicle_no, start_time, end_time,
                                     duration_hours, parking_fee, service_fee, total_amount, status, qr_token, rating,
                                     cancel_reason, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (next_id, code, user_id, slot_id, slot["vehicle_type"], vehicle_no, to_db(start), to_db(end), hours,
             price["parking_fee"], price["service_fee"], price["total_amount"], status,
             secrets.token_urlsafe(18) if paid else None, rating,
             None if paid else "USER_CANCELLED", to_db(start - timedelta(days=1))))
        if paid:
            db.execute(
                """INSERT INTO payments (booking_id, method, transaction_ref, amount, status, created_at, paid_at)
                   VALUES (?, 'UPI', ?, ?, 'SUCCESS', ?, ?)""",
                (next_id, "TXN" + secrets.token_hex(6).upper(), price["total_amount"],
                 to_db(start - timedelta(days=1)), to_db(start - timedelta(days=1))))

    def at(day_offset, hour, minute=0):
        return (now + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Aarav's history (past ones become COMPLETED automatically) + one upcoming on A-14 like the prototype.
    add_booking(aarav, slot_ids["A-08"], "MP09AB1234", at(-5, 17, 30), 3, rating=5)
    add_booking(aarav, slot_ids["A-09"], "MP09AB1234", at(-12, 10), 2, rating=5)
    add_booking(aarav, slot_ids["A-12"], "MP09CD8899", at(-20, 16), 2, rating=4)
    add_booking(aarav, slot_ids["A-03"], "MP09AB1234", at(-8, 12), 2, status="CANCELLED")
    add_booking(aarav, slot_ids["A-14"], "MP09AB1234", at(1, 19), 2)

    # Lots of other people's bookings today, so the admin chart and counters look alive.
    for _ in range(30):
        add_booking(rng.choice(others), rng.choice(car_slots_city), f"MP09ZZ{rng.randint(1000, 9999)}",
                    at(0, rng.randint(8, 19)), rng.randint(1, 4))
    for _ in range(12):  # and a few tomorrow
        add_booking(rng.choice(others), rng.choice(car_slots_city), f"MP09YY{rng.randint(1000, 9999)}",
                    at(1, rng.randint(8, 17)), rng.randint(1, 3))


def database_is_empty(db):
    return db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
