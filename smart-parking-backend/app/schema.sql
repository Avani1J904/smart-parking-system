-- =============================================================================
--  DATABASE DESIGN  (SDD section 8 - Data Design)
--
--  parking_locations 1--N parking_zones 1--N parking_slots 1--N bookings 1--N payments
--  users 1--N bookings
--
--  "IF NOT EXISTS" means it is safe to run this file every time the app starts.
-- =============================================================================

-- Registered people. role = USER (driver) or ADMIN (operator).
CREATE TABLE IF NOT EXISTS users (
    user_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name             TEXT    NOT NULL,
    email                 TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    mobile                TEXT    NOT NULL,                  -- 10 digits
    password_hash         TEXT    NOT NULL,                  -- NEVER the real password
    role                  TEXT    NOT NULL DEFAULT 'USER' CHECK (role IN ('USER', 'ADMIN')),
    city                  TEXT,
    vehicle_no            TEXT,                              -- default vehicle shown on Profile page
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT    NOT NULL
);

-- A parking facility, e.g. "City Center Parking".
CREATE TABLE IF NOT EXISTS parking_locations (
    location_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    address     TEXT
);

-- A section of a location, e.g. "Zone A - Ground Floor".
-- (total slots is calculated by counting slots, so it can never go out of date)
CREATE TABLE IF NOT EXISTS parking_zones (
    zone_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id INTEGER NOT NULL REFERENCES parking_locations(location_id),
    zone_name   TEXT NOT NULL,
    floor       TEXT,
    UNIQUE (location_id, zone_name)
);

-- One parking space.
--   status is the slot's BASE state (set by admin / sensors):
--     AVAILABLE      normal, can be booked
--     OCCUPIED       a vehicle is physically there right now (sensor / gate reading)
--     RESERVED       permanently kept aside (e.g. priority / disabled parking)
--     OUT_OF_SERVICE closed for maintenance
--   Whether a slot is free at a particular TIME also depends on bookings - the
--   API works that out (see services.slot_effective_statuses).
CREATE TABLE IF NOT EXISTS parking_slots (
    slot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id       INTEGER NOT NULL REFERENCES parking_zones(zone_id),
    slot_no       TEXT    NOT NULL,                          -- e.g. "A-14"
    vehicle_type  TEXT    NOT NULL CHECK (vehicle_type IN ('CAR', 'BIKE', 'EV')),
    status        TEXT    NOT NULL DEFAULT 'AVAILABLE'
                  CHECK (status IN ('AVAILABLE', 'OCCUPIED', 'RESERVED', 'OUT_OF_SERVICE')),
    rate_per_hour INTEGER NOT NULL,                          -- Rs. per hour
    has_charger   INTEGER NOT NULL DEFAULT 0,
    description   TEXT,                                      -- "Near Entry", "Covered", ...
    UNIQUE (zone_id, slot_no)
);

-- A reservation.
--   id          internal number used for joins
--   booking_id  the friendly code shown to people, e.g. "PK-2026-00188"
-- Times are local (India) ISO text, e.g. "2026-09-22T19:00:00".
CREATE TABLE IF NOT EXISTS bookings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id      TEXT    NOT NULL UNIQUE,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    slot_id         INTEGER NOT NULL REFERENCES parking_slots(slot_id),
    vehicle_type    TEXT    NOT NULL,
    vehicle_no      TEXT    NOT NULL,
    start_time      TEXT    NOT NULL,
    end_time        TEXT    NOT NULL,
    duration_hours  INTEGER NOT NULL,
    special_request TEXT,
    parking_fee     INTEGER NOT NULL,                        -- rate x hours
    service_fee     INTEGER NOT NULL,
    total_amount    INTEGER NOT NULL,                        -- parking_fee + service_fee (set by SERVER)
    status          TEXT    NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'CONFIRMED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),
    hold_expires_at TEXT,                                    -- PENDING bookings only
    qr_token        TEXT,                                    -- created once payment succeeds
    rating          INTEGER CHECK (rating BETWEEN 1 AND 5),
    cancel_reason   TEXT,                                    -- USER_CANCELLED / HOLD_EXPIRED / ADMIN_CANCELLED
    created_at      TEXT    NOT NULL,
    cancelled_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_bookings_slot_time ON bookings (slot_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_bookings_user      ON bookings (user_id);

-- One row per payment ATTEMPT. A booking can have several attempts (e.g. first
-- one failed, second one worked) but at most one ends as SUCCESS.
-- We store only a reference number - never card numbers or UPI PINs.
CREATE TABLE IF NOT EXISTS payments (
    payment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id      INTEGER NOT NULL REFERENCES bookings(id),
    method          TEXT    NOT NULL CHECK (method IN ('UPI', 'CARD')),
    transaction_ref TEXT    NOT NULL UNIQUE,
    amount          INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'INITIATED'
                    CHECK (status IN ('INITIATED', 'SUCCESS', 'FAILED', 'REFUNDED')),
    created_at      TEXT    NOT NULL,
    paid_at         TEXT
);

-- Login tokens that were logged out before they expired.
CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL
);
