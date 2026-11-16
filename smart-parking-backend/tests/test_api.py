"""
Automated tests. Run them with:

    python -m unittest discover -s tests -v

Each test starts a brand-new temporary database with the demo data, so tests never
affect each other or your real data. Reading the test names is a good way to learn
what the system promises to do.
"""
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app          # noqa: E402
from app.utils import now_local     # noqa: E402

ADMIN = {"email": "admin@parkease.com", "password": "Admin@123"}
AARAV = {"email": "aarav@example.com", "password": "User@1234"}
RIYA = {"email": "riya@example.com", "password": "User@1234"}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE_PATH": os.path.join(self.tmp.name, "test.db"), "TESTING": True})
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---------------------------------------------------------------
    def login(self, creds):
        res = self.client.post("/api/auth/login", json=creds)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return {"Authorization": "Bearer " + res.get_json()["token"]}

    def mall_car_slot(self, index=0):
        """A free car slot in the Mall (the seed data puts no bookings there)."""
        res = self.client.get("/api/parking/slots?location_id=2&vehicle_type=CAR&status=AVAILABLE"
                              f"&date={self.day(3)}&start_time=10:00&duration_hours=2")
        return res.get_json()["slots"][index]

    def day(self, offset):
        with self.app.app_context():
            return (now_local() + timedelta(days=offset)).strftime("%Y-%m-%d")

    def book(self, headers, slot, start="10:00", hours=2, days=3, **overrides):
        body = {"slot_id": slot["slot_id"], "vehicle_type": "CAR", "vehicle_no": "MP09 AB 1234",
                "date": self.day(days), "start_time": start, "duration_hours": hours}
        body.update(overrides)
        return self.client.post("/api/bookings", json=body, headers=headers)

    def pay(self, headers, booking_id, upi="name@upi"):
        created = self.client.post("/api/payments/create", json={"booking_id": booking_id, "method": "UPI"}, headers=headers)
        self.assertIn(created.status_code, (200, 201), created.get_data(as_text=True))
        return self.client.post("/api/payments/verify", headers=headers,
                                json={"payment_id": created.get_json()["payment"]["payment_id"], "upi_id": upi})


class AuthTests(ApiTestCase):
    def test_register_then_login(self):
        res = self.client.post("/api/auth/register", json={
            "full_name": "Test User", "email": "Test@Example.com", "mobile": "+91 98765 43210", "password": "Secret123"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()["user"]["email"], "test@example.com")   # stored lower-case
        self.assertEqual(res.get_json()["user"]["mobile"], "9876543210")        # tidied to 10 digits
        self.assertNotIn("password", str(res.get_json()).lower().replace("password_hash", ""))
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "test@example.com", "password": "Secret123"}).status_code, 200)

    def test_duplicate_email_rejected(self):
        res = self.client.post("/api/auth/register", json={
            "full_name": "Copy", "email": "aarav@example.com", "mobile": "9876543210", "password": "Secret123"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["error"]["code"], "EMAIL_EXISTS")

    def test_validation_lists_every_problem(self):
        res = self.client.post("/api/auth/register", json={"full_name": "", "email": "nope", "mobile": "123", "password": "short"})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(set(res.get_json()["error"]["details"]), {"full_name", "email", "mobile", "password"})

    def test_wrong_password(self):
        res = self.client.post("/api/auth/login", json={"email": AARAV["email"], "password": "Wrong@123"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_protected_route_needs_login(self):
        self.assertEqual(self.client.get("/api/profile").status_code, 401)
        self.assertEqual(self.client.get("/api/profile", headers={"Authorization": "Bearer garbage"}).status_code, 401)

    def test_logout_invalidates_token(self):
        headers = self.login(AARAV)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 200)
        self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)


class ParkingTests(ApiTestCase):
    def test_locations_are_public(self):
        res = self.client.get("/api/parking/locations")
        self.assertEqual(res.status_code, 200)
        names = [l["name"] for l in res.get_json()["locations"]]
        self.assertEqual(names, ["City Center Parking", "Mall Parking", "Railway Parking"])

    def test_slot_grid_matches_prototype(self):
        far = self.day(5)  # a day with no demo bookings, so only the base statuses show
        data = self.client.get(f"/api/parking/slots?location_id=1&zone_id=1&date={far}&start_time=10:00&duration_hours=2").get_json()
        by_no = {s["slot_no"]: s["status"] for s in data["slots"]}
        self.assertEqual(len(by_no), 32)
        self.assertEqual(by_no["A-01"], "AVAILABLE")
        self.assertEqual(by_no["A-07"], "RESERVED")      # priority slot
        self.assertEqual(data["service_fee"], 10)

    def test_search_filter(self):
        data = self.client.get("/api/parking/slots?location_id=1&q=charger").get_json()
        self.assertTrue(data["slots"] and all(s["has_charger"] for s in data["slots"]))


class BookingFlowTests(ApiTestCase):
    def test_full_flow_price_and_qr(self):
        headers = self.login(AARAV)
        slot = self.mall_car_slot()                       # Mall car rate is Rs. 80/hour
        res = self.book(headers, slot, total_amount=1, parking_fee=1)   # fake totals from the "browser" must be ignored
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        booking = res.get_json()["booking"]
        self.assertEqual(booking["status"], "PENDING")
        self.assertEqual(booking["total_amount"], 80 * 2 + 10)          # server-side price
        self.assertEqual(booking["vehicle_no"], "MP09AB1234")
        self.assertIsNone(booking["qr_token"])

        paid = self.pay(headers, booking["booking_id"])
        self.assertEqual(paid.status_code, 200, paid.get_data(as_text=True))
        confirmed = paid.get_json()["booking"]
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertEqual(confirmed["payment_status"], "SUCCESS")
        self.assertTrue(confirmed["qr_token"])

        receipt = self.client.get(f"/api/bookings/{booking['booking_id']}/receipt", headers=headers)
        self.assertEqual(receipt.status_code, 200)

    def test_double_booking_is_rejected(self):
        a, b = self.login(AARAV), self.login(RIYA)
        slot = self.mall_car_slot()
        self.assertEqual(self.book(a, slot).status_code, 201)
        clash = self.book(b, slot, start="11:00")                       # overlaps 10:00-12:00
        self.assertEqual(clash.status_code, 409)
        self.assertEqual(clash.get_json()["error"]["code"], "SLOT_TAKEN")
        self.assertEqual(self.book(b, slot, start="12:00").status_code, 201)   # back-to-back is fine

    def test_slot_shows_reserved_after_booking(self):
        headers = self.login(AARAV)
        slot = self.mall_car_slot()
        self.book(headers, slot)
        url = (f"/api/parking/slots?location_id=2&date={self.day(3)}&start_time=10:00&duration_hours=2")
        status = {s["slot_id"]: s["status"] for s in self.client.get(url).get_json()["slots"]}[slot["slot_id"]]
        self.assertEqual(status, "RESERVED")

    def test_wrong_vehicle_type_and_past_time(self):
        headers = self.login(AARAV)
        slot = self.mall_car_slot()
        self.assertEqual(self.book(headers, slot, vehicle_type="BIKE").get_json()["error"]["code"], "VEHICLE_MISMATCH")
        self.assertEqual(self.book(headers, slot, days=-1).status_code, 422)
        self.assertEqual(self.book(headers, slot, vehicle_no="12345").status_code, 422)

    def test_failed_payment_keeps_booking_pending_and_retry_works(self):
        headers = self.login(AARAV)
        booking = self.book(headers, self.mall_car_slot()).get_json()["booking"]
        failed = self.pay(headers, booking["booking_id"], upi="fail@upi")
        self.assertEqual(failed.status_code, 402)
        self.assertEqual(failed.get_json()["error"]["code"], "PAYMENT_FAILED")
        self.assertEqual(self.client.get(f"/api/bookings/{booking['booking_id']}", headers=headers).get_json()["booking"]["status"], "PENDING")
        self.assertEqual(self.pay(headers, booking["booking_id"]).status_code, 200)   # second attempt succeeds

    def test_expired_hold_frees_the_slot(self):
        self.app.config["HOLD_MINUTES"] = -1                           # hold is over the moment it is created
        a, b = self.login(AARAV), self.login(RIYA)
        slot = self.mall_car_slot()
        booking = self.book(a, slot).get_json()["booking"]
        self.assertEqual(self.book(b, slot).status_code, 201)          # slot is free again
        res = self.client.post("/api/payments/create", json={"booking_id": booking["booking_id"], "method": "UPI"}, headers=a)
        self.assertEqual(res.get_json()["error"]["code"], "HOLD_EXPIRED")

    def test_cancel_refunds_payment(self):
        headers = self.login(AARAV)
        booking = self.book(headers, self.mall_car_slot()).get_json()["booking"]
        self.pay(headers, booking["booking_id"])
        res = self.client.delete(f"/api/bookings/{booking['booking_id']}", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["refunded"])
        self.assertEqual(res.get_json()["booking"]["status"], "CANCELLED")
        detail = self.client.get(f"/api/bookings/{booking['booking_id']}", headers=headers).get_json()
        self.assertEqual(detail["payments"][0]["status"], "REFUNDED")

    def test_users_cannot_see_each_others_bookings(self):
        a, b = self.login(AARAV), self.login(RIYA)
        booking = self.book(a, self.mall_car_slot()).get_json()["booking"]
        self.assertEqual(self.client.get(f"/api/bookings/{booking['booking_id']}", headers=b).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/bookings/{booking['booking_id']}", headers=b).status_code, 404)
        ids = [x["booking_id"] for x in self.client.get("/api/bookings/history", headers=b).get_json()["bookings"]]
        self.assertNotIn(booking["booking_id"], ids)

    def test_history_filters_and_paging(self):
        headers = self.login(AARAV)
        data = self.client.get("/api/bookings/history?status=COMPLETED&per_page=2", headers=headers).get_json()
        self.assertEqual(len(data["bookings"]), 2)
        self.assertTrue(all(b["status"] == "COMPLETED" for b in data["bookings"]))
        self.assertEqual(data["pagination"]["total"], 3)
        self.assertEqual(data["pagination"]["pages"], 2)

    def test_rating_only_after_completion(self):
        headers = self.login(AARAV)
        done = self.client.get("/api/bookings/history?status=COMPLETED", headers=headers).get_json()["bookings"][0]
        self.assertEqual(self.client.post(f"/api/bookings/{done['booking_id']}/rating", json={"rating": 3}, headers=headers).status_code, 200)
        upcoming = self.book(headers, self.mall_car_slot()).get_json()["booking"]
        self.assertEqual(self.client.post(f"/api/bookings/{upcoming['booking_id']}/rating", json={"rating": 5}, headers=headers).status_code, 409)

    def test_quote_matches_prototype_numbers(self):
        slot = self.client.get("/api/parking/slots?location_id=1&q=A-14").get_json()["slots"][0]
        quote = self.client.get(f"/api/bookings/quote?slot_id={slot['slot_id']}&duration_hours=2").get_json()
        self.assertEqual((quote["parking_fee"], quote["service_fee"], quote["total_amount"]), (120, 10, 130))


class DashboardProfileTests(ApiTestCase):
    def test_dashboard(self):
        data = self.client.get("/api/dashboard", headers=self.login(AARAV)).get_json()
        self.assertEqual(data["user"]["first_name"], "Aarav")
        self.assertEqual(data["stats"]["total_bookings"], 4)           # 3 completed + 1 upcoming
        self.assertEqual(data["stats"]["active_bookings"], 1)
        self.assertEqual(data["active_booking"]["slot_no"], "A-14")
        self.assertEqual(len(data["recent_bookings"]), 3)

    def test_profile_update(self):
        headers = self.login(AARAV)
        res = self.client.put("/api/profile", headers=headers, json={"city": "Bhopal", "vehicle_no": "mp04 xy 9999", "notifications_enabled": False})
        user = res.get_json()["user"]
        self.assertEqual((user["city"], user["vehicle_no"], user["notifications_enabled"]), ("Bhopal", "MP04XY9999", False))
        clash = self.client.put("/api/profile", headers=headers, json={"email": "riya@example.com"})
        self.assertEqual(clash.status_code, 409)


class AdminTests(ApiTestCase):
    def test_admin_only(self):
        for path in ("/api/admin/summary", "/api/admin/bookings", "/api/admin/users"):
            self.assertEqual(self.client.get(path, headers=self.login(AARAV)).status_code, 403, path)
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_summary_shape(self):
        data = self.client.get("/api/admin/summary", headers=self.login(ADMIN)).get_json()
        self.assertEqual(data["total_slots"], 32 + 20 + 8 + 24 + 20)
        self.assertEqual(len(data["occupancy_trend"]["labels"]), 7)
        self.assertEqual(data["occupancy_trend"]["labels"][0], "8 AM")
        self.assertGreater(data["daily_bookings"], 0)
        self.assertTrue({"Zone A", "Zone B", "EV Zone"} <= {z["zone_name"] for z in data["zones"]})
        self.assertEqual(self.client.get("/api/admin/overview", headers=self.login(ADMIN)).status_code, 200)   # SRS name

    def test_admin_bookings_and_slot_update(self):
        admin = self.login(ADMIN)
        data = self.client.get("/api/admin/bookings?per_page=5", headers=admin).get_json()
        self.assertEqual(len(data["bookings"]), 5)
        self.assertIn("user_name", data["bookings"][0])

        slot = self.mall_car_slot()
        user = self.login(AARAV)
        self.book(user, slot)
        res = self.client.put(f"/api/admin/slots/{slot['slot_id']}", json={"status": "OUT_OF_SERVICE"}, headers=admin)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["upcoming_bookings_affected"], 1)
        # and now nobody can book it
        self.assertEqual(self.book(self.login(RIYA), slot, start="15:00").status_code, 409)

    def test_srs_url_aliases(self):
        self.assertEqual(self.client.post("/api/login", json=AARAV).status_code, 200)


class MiscTests(ApiTestCase):
    def test_errors_are_json(self):
        res = self.client.get("/api/nothing-here")
        self.assertEqual(res.status_code, 404)
        self.assertIn("error", res.get_json())
        self.assertEqual(self.client.post("/api/auth/login", data="not json").status_code, 400)

    def test_cors_and_health(self):
        res = self.client.get("/api/health", headers={"Origin": "http://localhost:5500"})
        self.assertEqual(res.get_json()["status"], "ok")
        self.assertEqual(res.headers["Access-Control-Allow-Origin"], "*")


if __name__ == "__main__":
    unittest.main()
