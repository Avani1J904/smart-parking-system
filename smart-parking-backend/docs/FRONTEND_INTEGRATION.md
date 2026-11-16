# Connecting the frontend to the backend

The frontend pages are currently demo-only. Follow these steps to make them real.

## Step 1 — add the helper

1. Copy `docs/frontend-api-helper.js` into the frontend as `assets/js/api.js`.
2. In every page that talks to the server, add this line **before** `app.js`:

```html
<script src="assets/js/api.js"></script>
```
(Pages inside `admin/` use `../assets/js/api.js`.)

3. If the backend is not at `http://localhost:5000`, edit `API_BASE` at the top of the helper.

## Step 2 — replace each demo action

| Page | Today (demo) | Replace with |
|---|---|---|
| `register.html` | form redirects to dashboard | `await SPMS.register(name, email, mobile, password)` then go to dashboard |
| `login.html` | form redirects to dashboard | `await SPMS.login(email, password)` then go to dashboard (admins → `admin/dashboard.html`: check `user.role`) |
| Any dashboard page → *Logout* link | link to `index.html` | `await SPMS.logout()` then go to `index.html` |
| `dashboard.html` | fixed numbers | `const d = await SPMS.dashboard()` → fill tiles from `d.stats`, the card from `d.active_booking`, the table from `d.recent_bookings` |
| `parking.html` | hard-coded slot cards | `const g = await SPMS.slots({location_id, date, start_time, duration_hours})` → draw `g.slots`; show `g.summary.available` of `g.summary.total`; disable cards whose `status` isn't `AVAILABLE` |
| `parking.html` summary box | fixed ₹130 | `await SPMS.quote(slotId, hours)` → `parking_fee`, `service_fee`, `total_amount` |
| `booking.html` submit | goes to `payment.html` | `const {booking} = await SPMS.createBooking({...})`, keep `booking.booking_id`, then go to `payment.html` |
| `payment.html` Pay button | toast message | `const {payment} = await SPMS.startPayment(bookingId, "UPI")` then `await SPMS.verifyPayment(payment.payment_id, {upi_id})`; show `booking.qr_token` on success |
| `history.html` | fixed rows | `await SPMS.history({q, status, month, page})` → rows from `bookings`; "Receipt" button → `SPMS.receipt(id)` |
| `profile.html` | fixed values | `SPMS.profile()` to fill, `SPMS.updateProfile({...})` on save |
| `admin/dashboard.html` | fixed numbers + fixed chart | `const s = await SPMS.adminSummary()` → tiles (`total_slots`, `occupied_slots`, `daily_bookings`, `daily_revenue`), zone list from `s.zones`, chart from `s.occupancy_trend.labels/values`; table from `SPMS.adminBookings({per_page: 5})` |

## Step 3 — a complete example (Booking page)

```js
// booking.html – when the form is submitted
bookingForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const { booking } = await SPMS.createBooking({
      slot_id: Number(selectedSlotId),             // remembered from the Find Parking page
      vehicle_type: vehicleTypeSelect.value,       // "Car", "Bike" or "EV Car" all work
      vehicle_no: vehicleNoInput.value,
      date: dateInput.value,                       // 2026-09-22
      start_time: startInput.value,                // 19:00
      duration_hours: parseInt(durationSelect.value),   // "2 hours" -> 2
      special_request: noteInput.value,
    });
    sessionStorage.setItem("bookingId", booking.booking_id);
    window.location.href = "payment.html";
  } catch (err) {
    if (err.code === "SLOT_TAKEN") alert(err.message);        // someone else got there first
    else if (err.details) showFieldErrors(err.details);       // { vehicle_no: "Vehicle number looks invalid..." }
    else alert(err.message);
  }
});
```

## Things to remember

- **Duration dropdowns** say "2 hrs" in the prototype — send the number (`2`) to the API.
- **Not logged in?** Calls to 🔒 endpoints fail with `401`; send the user to `login.html`.
- **Slot ids vs slot numbers:** the API uses `slot_id` (a number) when booking and `slot_no` ("A-14") for display. Keep both from the slots response.
- **Opening pages directly from disk** (`file://`) works for the API because the backend allows any origin in development
  (`CORS_ORIGINS=*`). For tidiness you can instead let the backend serve the frontend (see README → *one address*).
- **Keep it fresh:** to make the slot grid "live", re-call `SPMS.slots(...)` every 5–10 seconds.
