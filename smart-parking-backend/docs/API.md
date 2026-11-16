# API Reference

Base address while developing: `http://localhost:5000`

**Conventions**

- Requests and responses are JSON.
- Endpoints marked 🔒 need a login token: send `Authorization: Bearer <token>`. Endpoints marked 🛡 need an **admin** token.
- Times look like `2026-09-22T19:00:00+05:30` (India time). Money is in rupees (INR), whole numbers.
- **Errors** always look like this:

```json
{ "error": { "code": "SLOT_TAKEN",
             "message": "Sorry, this slot is no longer available for that time. Please pick another slot.",
             "details": { "slot_status": "RESERVED" } } }
```

`details` is present for form problems and maps each field to its message, e.g. `{ "email": "Email is not a valid email address." }`.

| HTTP | Meaning |
|---|---|
| 200 / 201 | OK / created |
| 400 | body is not valid JSON |
| 401 | not logged in, or token expired / logged out |
| 402 | payment declined |
| 403 | logged in but not allowed (e.g. a driver calling an admin endpoint) |
| 404 | not found (also used for other people's bookings) |
| 409 | conflict: slot taken, already paid, cannot cancel, email exists |
| 422 | a form field is wrong (see `details`) |
| 429 | too many attempts |

---

## Summary

| Method | URL | Who | Purpose |
|---|---|---|---|
| POST | `/api/auth/register` | anyone | create account |
| POST | `/api/auth/login` | anyone | get token |
| POST | `/api/auth/logout` | 🔒 | end session |
| GET | `/api/auth/me` | 🔒 | current user |
| GET | `/api/parking/locations` | anyone | locations, zones, free-slot counts |
| GET | `/api/parking/slots` | anyone | slot grid with status for a time window |
| GET | `/api/bookings/quote` | anyone | price preview |
| POST | `/api/bookings` | 🔒 | reserve a slot (held 10 min) |
| GET | `/api/bookings/history` (also `/api/bookings`) | 🔒 | my bookings |
| GET | `/api/bookings/{id}` | 🔒 | one booking + its payments |
| DELETE | `/api/bookings/{id}` | 🔒 | cancel |
| GET | `/api/bookings/{id}/receipt` | 🔒 | receipt (after payment) |
| POST | `/api/bookings/{id}/rating` | 🔒 | rate a completed booking |
| POST | `/api/payments/create` | 🔒 | start payment |
| POST | `/api/payments/verify` | 🔒 | finish payment → booking confirmed |
| GET | `/api/dashboard` | 🔒 | everything for the user dashboard |
| GET / PUT | `/api/profile` | 🔒 | read / update profile |
| GET | `/api/admin/summary` (alias `/overview`) | 🛡 | KPIs, zones, occupancy chart |
| GET | `/api/admin/bookings` | 🛡 | all bookings |
| GET | `/api/admin/users` | 🛡 | all users |
| PUT | `/api/admin/slots/{id}` | 🛡 | change slot status / rate |
| GET | `/api/health` | anyone | "is the server alive?" |

---

## Authentication

### `POST /api/auth/register`

```json
{ "full_name": "Aarav Sharma", "email": "aarav@example.com", "mobile": "91234 56789", "password": "Secret123" }
```

Rules: email must be valid and unused (`409 EMAIL_EXISTS` otherwise); mobile = 10-digit Indian number (`+91`/spaces allowed);
password = 8+ characters with at least one letter and one number.

`201` →
```json
{ "user": { "user_id": 5, "full_name": "Aarav Sharma", "email": "aarav@example.com", "mobile": "9123456789",
            "role": "USER", "city": null, "vehicle_no": null, "notifications_enabled": true, "member_since": "2026" },
  "token": "eyJhbGciOi...", "token_type": "Bearer", "expires_in": 43200 }
```

### `POST /api/auth/login`

```json
{ "email": "aarav@example.com", "password": "User@1234" }
```
Same response as register (`200`). Wrong details → `401 INVALID_CREDENTIALS`. Five misses in a row → `429 TOO_MANY_ATTEMPTS` for 5 minutes.

### `POST /api/auth/logout` 🔒 · `GET /api/auth/me` 🔒

Logout cancels the token. `me` returns `{ "user": {...} }`.

---

## Parking discovery (public)

### `GET /api/parking/locations`

```json
{ "locations": [ { "location_id": 1, "name": "City Center Parking", "address": "Main Gate, MG Road, Indore",
                   "total_slots": 60, "available_slots": 56,
                   "zones": [ { "zone_id": 1, "zone_name": "Zone A", "floor": "Ground Floor", "total_slots": 32, "available_slots": 28 } ] } ] }
```
`available_slots` = free **right now**.

### `GET /api/parking/slots`

Options (all optional): `location_id`, `zone_id`, `date=2026-09-22` (default today), `start_time=19:00` (default now),
`duration_hours=2` (default 2), `vehicle_type=CAR|BIKE|EV`, `status=AVAILABLE`, `q=covered` (searches slot number / type / description).

Example: `/api/parking/slots?location_id=1&zone_id=1&date=2026-09-22&start_time=19:00&duration_hours=2`

```json
{ "window": { "start_time": "2026-09-22T19:00:00+05:30", "end_time": "2026-09-22T21:00:00+05:30", "duration_hours": 2 },
  "service_fee": 10,
  "summary": { "total": 32, "available": 31, "occupied": 0, "reserved": 1, "out_of_service": 0 },
  "slots": [ { "slot_id": 1, "slot_no": "A-01", "status": "AVAILABLE", "vehicle_type": "CAR", "rate_per_hour": 60,
               "has_charger": false, "description": "Near Entry", "zone_id": 1, "zone_name": "Zone A",
               "floor": "Ground Floor", "location_id": 1, "location_name": "City Center Parking" } ] }
```

**Status meanings (for the chosen time):** `AVAILABLE` free · `RESERVED` someone booked it (or it is kept for priority use) ·
`OCCUPIED` a vehicle is parked there now · `OUT_OF_SERVICE` closed for maintenance.

---

## Bookings

### `GET /api/bookings/quote?slot_id=14&duration_hours=2`

```json
{ "slot_id": 14, "slot_no": "A-14", "rate_per_hour": 60, "duration_hours": 2, "currency": "INR",
  "parking_fee": 120, "service_fee": 10, "total_amount": 130 }
```

### `POST /api/bookings` 🔒

```json
{ "slot_id": 14, "vehicle_type": "CAR", "vehicle_no": "MP09 AB 1234",
  "date": "2026-09-22", "start_time": "19:00", "duration_hours": 2, "special_request": "Near the lift" }
```
`vehicle_type`: `CAR`, `BIKE`, `EV` (also accepts "EV Car"). Duration 1–12 hours. Date within the next 30 days; start must not be in the past.

`201` →
```json
{ "message": "Slot held for 10 minutes. Complete payment to confirm.",
  "booking": { "booking_id": "PK-2026-00188", "status": "PENDING", "location": "City Center Parking", "zone": "Zone A",
               "slot_id": 14, "slot_no": "A-14", "vehicle_type": "CAR", "vehicle_no": "MP09AB1234",
               "start_time": "2026-09-22T19:00:00+05:30", "end_time": "2026-09-22T21:00:00+05:30", "duration_hours": 2,
               "parking_fee": 120, "service_fee": 10, "total_amount": 130, "currency": "INR",
               "payment_status": "NOT_STARTED", "qr_token": null,
               "hold_expires_at": "2026-09-22T18:41:00+05:30" } }
```
Errors: `409 SLOT_TAKEN` · `422 VEHICLE_MISMATCH` · `422 VALIDATION_ERROR` · `429 TOO_MANY_PENDING` (3 unpaid bookings already).

This matches the SDD §9.2 contract (`booking_id`, `slot_no`, `status`, `start_time`, `end_time`, `total_amount`, `payment_status`, `qr_token`).

### `GET /api/bookings/history` 🔒 (same as `GET /api/bookings`)

Options: `status=ACTIVE|CONFIRMED|COMPLETED|CANCELLED|PENDING`, `month=2026-09`, `q=` (booking id, location, slot, vehicle no.), `page`, `per_page` (default 10).

```json
{ "bookings": [ { "...": "same booking object as above" } ],
  "pagination": { "page": 1, "per_page": 10, "total": 4, "pages": 1 } }
```
Unpaid bookings that timed out are not listed.

### `GET /api/bookings/{booking_id}` 🔒
`{ "booking": {...}, "payments": [ {...} ] }` — someone else's booking gives `404`.

### `DELETE /api/bookings/{booking_id}` 🔒
Only before the start time (`409 CANNOT_CANCEL` otherwise). A paid booking is refunded: `{ "booking": {...}, "refunded": true, "message": "..." }`.

### `GET /api/bookings/{booking_id}/receipt` 🔒
Receipt with booking + payment details. `409 NO_RECEIPT` if never paid.

### `POST /api/bookings/{booking_id}/rating` 🔒
`{ "rating": 5 }` (1–5), only for `COMPLETED` bookings. Feeds the dashboard's "Parking Rating".

**Booking status life-cycle:** `PENDING` → `CONFIRMED` → `ACTIVE` → `COMPLETED`, or `CANCELLED` at any point before start.
The server moves them along with the clock; nothing to schedule.

---

## Payments 🔒

### `POST /api/payments/create`
```json
{ "booking_id": "PK-2026-00188", "method": "UPI" }
```
`201` → `{ "payment": { "payment_id": 12, "method": "UPI", "transaction_ref": "TXN3F9A1C77B2D0", "amount": 130, "status": "INITIATED", ... }, "booking_id": "PK-2026-00188" }`

The `amount` is always the server's figure. Calling it twice returns the same open payment (`200`).
Errors: `409 HOLD_EXPIRED` (10 minutes passed — book again) · `409 ALREADY_PAID`.

### `POST /api/payments/verify`
```json
{ "payment_id": 12, "upi_id": "aarav@upi" }
```
or for cards `{ "payment_id": 12, "card_token": "tok_ok" }`.

`200` → `{ "payment": { "status": "SUCCESS", ... }, "booking": { "status": "CONFIRMED", "qr_token": "...", ... } }`

Declined → `402 PAYMENT_FAILED` (booking stays `PENDING`). That payment is then closed; call **create** again to retry before the hold ends.
Demo values: `fail@upi` / `tok_fail` are declined; anything valid else succeeds.

---

## Dashboard & profile 🔒

### `GET /api/dashboard`
```json
{ "user": { "full_name": "Aarav Sharma", "first_name": "Aarav" },
  "stats": { "active_bookings": 1, "total_bookings": 4, "total_spent": 580, "average_rating": 4.7 },
  "active_booking": { "...": "booking object, or null" },
  "quick_stats": { "month": "2026-11", "booked_hours": 7, "average_stay_hours": 2.3 },
  "recent_bookings": [ { "...": "up to 3 booking objects" } ] }
```
`active_booking` = the one in progress, otherwise the next upcoming paid one.

### `GET /api/profile` · `PUT /api/profile`
Send only what changed: `full_name`, `email`, `mobile`, `city`, `vehicle_no`, `notifications_enabled` (true/false).
Returns `{ "user": {...}, "total_bookings": 4 }`. Email already used by someone else → `409`.

---

## Admin 🛡

### `GET /api/admin/summary`
Options: `location_id`, `date=YYYY-MM-DD` (default today).
```json
{ "date": "2026-09-22", "total_slots": 104, "occupied_slots": 3, "available_slots": 100, "reserved_slots": 1,
  "out_of_service_slots": 0, "daily_bookings": 27, "daily_revenue": 4290, "currency": "INR",
  "zones": [ { "zone_id": 1, "zone_name": "Zone A", "location_name": "City Center Parking", "total_slots": 32, "free_slots": 28 } ],
  "occupancy_trend": { "labels": ["8 AM","10 AM","12 PM","2 PM","4 PM","6 PM","8 PM"], "values": [3,9,10,6,4,3,1] } }
```
`occupancy_trend` plugs straight into the Chart.js chart on the admin page.

### `GET /api/admin/bookings`
Options: `status`, `q` (id / user name / email / location / slot), `date`, `location_id`, `page`, `per_page`.
Each booking also carries `user_id`, `user_name`, `user_email`.

### `GET /api/admin/users`  — paged list of users.

### `PUT /api/admin/slots/{slot_id}`
```json
{ "status": "OUT_OF_SERVICE", "rate_per_hour": 70, "description": "Covered" }
```
Any one or more. Returns the slot plus `upcoming_bookings_affected` — existing bookings are **not** cancelled
automatically; the admin is told how many people to contact.
