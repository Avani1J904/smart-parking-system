"""Collects every group of endpoints and attaches it to the app."""
from . import admin, auth, bookings, dashboard, parking, payments, profile


def register_routes(app):
    for module in (auth, parking, bookings, payments, dashboard, profile, admin):
        app.register_blueprint(module.bp)

    # The SRS (section 7.2) spells a few URLs slightly differently from the SDD (section 9).
    # Both spellings work, so either document can be used for testing.
    app.add_url_rule("/api/register", "srs_register", auth.register, methods=["POST"])
    app.add_url_rule("/api/login", "srs_login", auth.login, methods=["POST"])
    app.add_url_rule("/api/payment/create", "srs_payment_create", payments.create_payment, methods=["POST"])
    app.add_url_rule("/api/payment/verify", "srs_payment_verify", payments.verify_payment, methods=["POST"])
