"""
One consistent error format for the whole API (SDD section 9.1).

Every error looks like this, so the frontend only needs one way to show them:

    { "error": { "code": "SLOT_TAKEN",
                 "message": "Sorry, that slot was just booked.",
                 "details": { ... optional, e.g. which form field is wrong ... } } }
"""
import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    """Raise this anywhere to stop the request and send an error to the client."""

    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status = status      # HTTP status number, e.g. 404
        self.code = code          # short machine-readable label, e.g. "NOT_FOUND"
        self.message = message    # sentence a human can read
        self.details = details


def _error_response(status, code, message, details=None):
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return _error_response(err.status, err.code, err.message, err.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        # Flask's own errors (unknown URL, wrong method, ...) in our format.
        code = (err.name or "ERROR").upper().replace(" ", "_")
        return _error_response(err.code or 500, code, err.description)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # A bug. Log the details for the developer, show nothing sensitive to the user.
        log.exception("Unhandled error: %s", err)
        return _error_response(500, "INTERNAL_ERROR", "Something went wrong on our side. Please try again.")
