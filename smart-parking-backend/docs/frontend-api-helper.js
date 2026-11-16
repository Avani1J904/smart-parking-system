/*
 * frontend-api-helper.js  -  a tiny helper that lets the frontend pages talk to the backend.
 *
 * HOW TO USE
 *   1. Copy this file into the frontend folder, e.g.  assets/js/api.js
 *   2. In an HTML page, add BEFORE app.js:    <script src="assets/js/api.js"></script>
 *   3. Call it from any page script, for example on the Login page:
 *
 *        try {
 *          await SPMS.login("aarav@example.com", "User@1234");
 *          window.location.href = "dashboard.html";
 *        } catch (err) {
 *          alert(err.message);              // already a friendly sentence
 *          console.log(err.details);        // e.g. { email: "Email is not a valid email address." }
 *        }
 *
 * If the backend is on another address, change API_BASE below
 * (or open the frontend through the backend: set FRONTEND_DIR, see README.md).
 */
const SPMS = (() => {
  const API_BASE = "http://localhost:5000";   // where the backend runs
  const TOKEN_KEY = "spms_token";

  // ---- the login token is kept in the browser so it survives page changes ----
  const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return memoryToken; } };
  let memoryToken = null;
  const setToken = (t) => { memoryToken = t; try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch (e) {} };

  // ---- one function that makes every request and turns errors into Error objects ----
  async function request(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    const token = getToken();
    if (token) headers.Authorization = "Bearer " + token;

    const res = await fetch(API_BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const e = data.error || {};
      const err = new Error(e.message || "Something went wrong. Please try again.");
      err.code = e.code; err.status = res.status; err.details = e.details;
      if (res.status === 401 && e.code !== "INVALID_CREDENTIALS") setToken(null);   // session ended
      throw err;
    }
    return data;
  }
  const qs = (params) => {
    const clean = Object.fromEntries(Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== ""));
    const text = new URLSearchParams(clean).toString();
    return text ? "?" + text : "";
  };

  return {
    isLoggedIn: () => !!getToken(),

    // --- Login / Register / Logout  (login.html, register.html) ---
    async login(email, password) { const d = await request("POST", "/api/auth/login", { email, password }); setToken(d.token); return d.user; },
    async register(full_name, email, mobile, password) { const d = await request("POST", "/api/auth/register", { full_name, email, mobile, password }); setToken(d.token); return d.user; },
    async logout() { try { await request("POST", "/api/auth/logout"); } finally { setToken(null); } },
    me: () => request("GET", "/api/auth/me").then((d) => d.user),

    // --- Find Parking  (parking.html) ---
    locations: () => request("GET", "/api/parking/locations").then((d) => d.locations),
    slots: (filters) => request("GET", "/api/parking/slots" + qs(filters)),   // {location_id, date, start_time, duration_hours, q}
    quote: (slot_id, duration_hours) => request("GET", "/api/bookings/quote" + qs({ slot_id, duration_hours })),

    // --- Booking + Payment  (booking.html, payment.html) ---
    createBooking: (form) => request("POST", "/api/bookings", form),   // {slot_id, vehicle_type, vehicle_no, date, start_time, duration_hours, special_request}
    startPayment: (booking_id, method) => request("POST", "/api/payments/create", { booking_id, method }),
    // NOTE: if verifyPayment fails (error code PAYMENT_FAILED) that payment is closed. To let the user
    // try again, call startPayment(...) once more to get a fresh payment_id (until the 10-minute hold ends).
    verifyPayment: (payment_id, extra) => request("POST", "/api/payments/verify", { payment_id, ...extra }),   // extra: {upi_id} or {card_token}

    // --- Dashboard / History / Profile ---
    dashboard: () => request("GET", "/api/dashboard"),
    history: (filters) => request("GET", "/api/bookings/history" + qs(filters)),   // {status, month, q, page}
    booking: (id) => request("GET", "/api/bookings/" + encodeURIComponent(id)),
    cancelBooking: (id) => request("DELETE", "/api/bookings/" + encodeURIComponent(id)),
    receipt: (id) => request("GET", "/api/bookings/" + encodeURIComponent(id) + "/receipt"),
    profile: () => request("GET", "/api/profile"),
    updateProfile: (changes) => request("PUT", "/api/profile", changes),

    // --- Admin  (admin/dashboard.html) ---
    adminSummary: (filters) => request("GET", "/api/admin/summary" + qs(filters)),
    adminBookings: (filters) => request("GET", "/api/admin/bookings" + qs(filters)),
  };
})();

if (typeof module !== "undefined") module.exports = SPMS;   // lets it run in Node for testing
