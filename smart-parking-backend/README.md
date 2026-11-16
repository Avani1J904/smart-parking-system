# Smart Parking Management System — Backend

The "engine room" behind the ParkEase website. The frontend (HTML pages) is what people **see**;
this backend is what **remembers and decides**: who is registered, which slots are free, who booked
what, and whether a payment went through.

Built with **Python + Flask + SQLite**, following your three documents
(Proposal, SRS v1.0 and SDD v1.0). No database server needs installing — SQLite is just one file.

---

## 1. Run it in 3 steps

You need **Python 3.9 or newer** ([python.org](https://www.python.org/downloads/)).

```bash
# 1. open a terminal in this folder, then install the two libraries
pip install -r requirements.txt

# 2. start the server
python run.py

# 3. check it works – open this link in your browser
http://localhost:5000/api/parking/locations
```

You should see a list of parking locations. That's it — the first start automatically creates the
database and fills it with demo data. Press **Ctrl + C** in the terminal to stop.

> Windows tip: if `python` isn't recognised, try `py run.py` and `py -m pip install -r requirements.txt`.

### Demo accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@parkease.com` | `Admin@123` |
| Driver | `aarav@example.com` | `User@1234` |
| Driver | `riya@example.com` | `User@1234` |

### Want one address for website + API? (optional)

Point the backend at your frontend folder and it serves the pages too:

```bash
# Mac / Linux
FRONTEND_DIR=/path/to/frontend python run.py
# Windows PowerShell
$env:FRONTEND_DIR = "C:\path\to\frontend"; python run.py
```

Then open `http://localhost:5000/`.

---

## 2. Connecting the frontend

The frontend you received is a **prototype**: its buttons show demo messages and don't call any
server yet (the SRS and SDD describe it that way on purpose). The backend is ready for it:

- `docs/frontend-api-helper.js` is a small file you copy into the frontend. It gives you simple
  calls such as `SPMS.login(...)`, `SPMS.slots(...)`, `SPMS.createBooking(...)`.
  It has been tested against this server.
- `docs/FRONTEND_INTEGRATION.md` shows which page should call which endpoint.

---

## 3. What is where?

```
smart-parking-backend/
├── run.py                 ← START HERE: starts the server
├── manage.py              ← reset the database / add an admin
├── requirements.txt       ← the 2 libraries needed
├── .env.example           ← optional settings (secret key, fees, ...)
│
├── app/
│   ├── __init__.py        ← builds the app and plugs everything together
│   ├── config.py          ← settings: service fee ₹10, 10-minute hold, ...
│   ├── schema.sql         ← the DATABASE design (all tables, in readable SQL)
│   ├── db.py              ← opens the database; "all-or-nothing" transactions
│   ├── services.py        ← THE RULES: prices, availability, booking life-cycle
│   ├── auth_utils.py      ← login tokens, "who is calling?" checks
│   ├── payment_gateway.py ← a PRETEND payment company (swap for a real one later)
│   ├── utils.py           ← input checking (validation), time and paging helpers
│   ├── serializers.py     ← shapes the JSON sent to the frontend
│   ├── errors.py          ← one consistent error format
│   ├── seed.py            ← demo data (3 locations, 104 slots, sample bookings)
│   └── routes/            ← the endpoints, one file per area
│       ├── auth.py        register · login · logout
│       ├── parking.py     locations · live slot grid
│       ├── bookings.py    book · history · cancel · receipt · rating
│       ├── payments.py    create · verify
│       ├── dashboard.py   user dashboard numbers
│       ├── profile.py     view / edit profile
│       └── admin.py       admin KPIs · all bookings · users · slot control
│
├── tests/test_api.py      ← 28 automated tests (also good "documentation by example")
└── docs/
    ├── API.md                     ← every endpoint with example requests/responses
    ├── FRONTEND_INTEGRATION.md    ← which page calls what
    └── frontend-api-helper.js     ← drop-in JavaScript for the frontend
```

**Rule of thumb for reading the code:** a *route* receives the request → asks *services* what the
rules say → reads/writes the database → returns JSON. Every file starts with a plain-English note
explaining its job.

---

## 4. How a booking works

```
 Driver                         Backend                                   Database
   │  1. choose location/time     │                                          │
   │ ───────────────────────────► │  GET /api/parking/slots                  │
   │ ◄─────────────────────────── │  slots: Available / Occupied / Reserved  │
   │  2. pick slot + vehicle      │                                          │
   │ ───────────────────────────► │  POST /api/bookings                      │
   │                              │  • re-checks the slot is free  (no double booking)
   │                              │  • works out the price itself            │
   │ ◄─────────────────────────── │  booking = PENDING, slot HELD 10 minutes │
   │  3. pay                      │                                          │
   │ ───────────────────────────► │  POST /api/payments/create  → /verify    │
   │ ◄─────────────────────────── │  booking = CONFIRMED + QR pass           │
   │                              │                                          │
   │     later, automatically:   CONFIRMED → ACTIVE (start time) → COMPLETED (end time)
   │     not paid in 10 minutes: PENDING → CANCELLED, slot is free again
```

### The rules, in plain words

| Rule | Where it comes from |
|---|---|
| A slot can't be booked twice for overlapping times. The final check happens on the server inside a locked step, so two people clicking at the same instant can't both win. | SRS §11, SDD §8.3 |
| **Price = hourly rate × hours + ₹10 service fee.** (₹60 × 2 + ₹10 = **₹130**, exactly like the frontend.) The browser's own total is ignored. | SRS FR-09, SDD §12.2 |
| A new booking is **held for 10 minutes** while the user pays. | Booking page text |
| A booking is "paid" only after the payment check passes. | SRS §11 |
| Slot status shown for a time window: **Available / Occupied / Reserved** (+ *Out of service* for maintenance). | SRS FR-05 |
| The vehicle type must fit the slot (a bike can't take a car bay). Vehicle numbers are tidied (`mp09 ab 1234` → `MP09AB1234`). | SRS §11 |
| Passwords are stored only as salted hashes. Logging out cancels the token. 5 wrong passwords → a 5-minute pause. | SDD §11 |
| Drivers see only **their own** bookings. Admin endpoints return 403 to everyone else. | SDD §14.2 |
| Cancelling a not-yet-started booking is allowed; if it was paid it is refunded. | SRS §7.2 (`DELETE /api/bookings/{id}`) |

---

## 5. Which requirement is covered where

| SRS requirement | Endpoint(s) |
|---|---|
| FR-01 Registration · FR-02 Login | `POST /api/auth/register`, `POST /api/auth/login` |
| FR-03 Dashboard | `GET /api/dashboard` |
| FR-04 Parking search · FR-05 Slot status · FR-07 Slot filter | `GET /api/parking/locations`, `GET /api/parking/slots` (`?q=` searches) |
| FR-06 Slot selection · FR-08 Booking details | `POST /api/bookings` |
| FR-09 Booking summary (fees) | `GET /api/bookings/quote` |
| FR-10 Payment | `POST /api/payments/create`, `POST /api/payments/verify` |
| FR-11 Booking history | `GET /api/bookings/history`, `GET /api/bookings/<id>`, `/receipt` |
| FR-12 Profile | `GET` / `PUT /api/profile` |
| FR-13 Admin KPIs · FR-14 Occupancy chart | `GET /api/admin/summary` |
| UC-09 Manage parking | `PUT /api/admin/slots/<id>` |
| NFR-07 Security | hashed passwords, tokens, role checks, parameterised SQL, server-side validation |

The SDD's URLs are the main ones. The few places where the SRS spells a URL differently
(`/api/login`, `/api/register`, `/api/payment/create`, `/api/payment/verify`, `/api/admin/overview`)
also work.

Full details: **`docs/API.md`**.

---

## 6. Try it from the terminal

```bash
# log in (copy the "token" from the answer)
curl -X POST http://localhost:5000/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"aarav@example.com","password":"User@1234"}'

# use the token to see your dashboard
curl http://localhost:5000/api/dashboard -H "Authorization: Bearer PASTE_TOKEN_HERE"
```

More examples (booking, payment, admin) are in `docs/API.md`.

### Demo payment

There is no real payment company in a college project, so `app/payment_gateway.py` pretends to be one:

- **UPI:** any id like `name@upi` succeeds. An id starting with `fail` (e.g. `fail@upi`) is declined.
- **Card:** send `card_token: "tok_ok"` to succeed or `"tok_fail"` to be declined.
  (Real gateways hand the browser a token so card numbers never reach your server — we follow that design.)

To use a real gateway later (Razorpay, Stripe…), only the two functions in that file change.

---

## 7. Tests and maintenance

```bash
python -m unittest discover -s tests -v     # runs 28 checks on a throw-away database
python manage.py reset-db                   # wipe everything, reload demo data
python manage.py create-admin me@x.com "My Name" Strong123
```

Settings you may want to change are in `.env.example` (service fee, hold minutes, secret key, CORS).

---

## 8. Honest limits (and good "future work" for your report)

- **Payments are simulated** (see above). Real gateway + signature checks = future work (SRS §14).
- **No sensors / IoT.** A slot's `OCCUPIED` status is set by an admin (`PUT /api/admin/slots/<id>`);
  a sensor would call the same kind of update. The dashboard's *"on-time exit %"* and *"parking usage %"*
  tiles need real gate data, so the API doesn't invent them.
- **Not yet built (SRS "future"):** email/SMS notifications, forgot-password, live push updates
  (WebSockets), RFID/ANPR gates. The frontend can poll `/api/parking/slots` every few seconds for near-live data.
- **Single-server design.** SQLite and the login-attempt limiter live on one machine. For many
  servers, move to MySQL/PostgreSQL (the SQL is plain and the schema is in one file).
- **Before putting this on the internet:** set a real `SECRET_KEY`, set `CORS_ORIGINS` to your site,
  use HTTPS, and run with a production server (e.g. `gunicorn "app:create_app()"`), not `debug=True`.

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: flask` | Run `pip install -r requirements.txt` |
| "Address already in use" | Another program uses port 5000 — change the port at the bottom of `run.py` |
| Browser says "CORS error" / "Failed to fetch" | Make sure the backend is running and `API_BASE` in the helper matches its address |
| Want a clean start | `python manage.py reset-db` |
| 401 on every call | Your token expired (12 h) or you logged out — log in again |
