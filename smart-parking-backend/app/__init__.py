"""
Smart Parking Management System - backend (Flask).

`create_app()` builds the whole application: it loads settings, opens the
database, attaches all the endpoints and adds the cross-cutting extras
(error format, browser-access headers, status refresh).
"""
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import db, services
from .config import Config
from .errors import ApiError, register_error_handlers
from .routes import register_routes
from .seed import database_is_empty, seed_database
from .utils import now_local


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    db.init_app(app)                       # create tables if needed
    register_error_handlers(app)
    register_routes(app)

    # First start: fill an empty database with demo data.
    if app.config["AUTO_SEED"]:
        with app.app_context():
            if database_is_empty(db.get_db()):
                seed_database(db.get_db())

    @app.before_request
    def refresh_booking_statuses():
        """Before each API call: expire old holds, mark bookings active/completed (see services.py)."""
        if request.path.startswith("/api/") and request.method != "OPTIONS":
            services.sync_booking_statuses(db.get_db(), now_local())

    @app.after_request
    def add_headers(response):
        # CORS: lets the frontend (served from another address) call this API from the browser.
        allowed = app.config["CORS_ORIGINS"]
        origin = request.headers.get("Origin")
        if allowed == "*":
            response.headers["Access-Control-Allow-Origin"] = "*"
        elif origin and origin in [o.strip() for o in allowed.split(",")]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        # Basic browser protections (SDD 11.3).
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/health")
    def health():
        db.get_db().execute("SELECT 1")
        return jsonify({"status": "ok", "time": now_local().isoformat()})

    # --- Home page -------------------------------------------------------------
    frontend = app.config["FRONTEND_DIR"]
    if frontend and os.path.isdir(frontend):
        # Serve the website too, so one address gives you both the pages and the API.
        @app.get("/", defaults={"path": "index.html"})
        @app.get("/<path:path>")
        def serve_frontend(path):
            if path.startswith("api/"):
                raise ApiError(404, "NOT_FOUND", "No such API endpoint.")
            return send_from_directory(frontend, path)
    else:
        @app.get("/")
        def index():
            return jsonify({
                "name": "Smart Parking Management System API",
                "status": "running",
                "try_this": "/api/parking/locations",
                "health": "/api/health",
                "docs": "See README.md and docs/API.md in the project folder.",
            })

    return app
