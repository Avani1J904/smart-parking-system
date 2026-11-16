"""
Small reusable helpers: time handling, input checking ("validation") and paging.
"""
import re
from datetime import datetime, timedelta, timezone

from flask import current_app, request

from .errors import ApiError

# ----------------------------------------------------------------------------
# TIME
# All times are kept in ONE local time zone (India by default).
# In the database they are plain text like "2026-09-22T19:00:00", which sorts
# correctly as text. When we send them out we add the offset: "...+05:30".
# ----------------------------------------------------------------------------
DB_FORMAT = "%Y-%m-%dT%H:%M:%S"


def now_local():
    """Current local time (no timezone attached)."""
    minutes = current_app.config["TZ_OFFSET_MINUTES"]
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(tzinfo=None, microsecond=0)


def to_db(dt):
    """datetime -> text for the database."""
    return dt.strftime(DB_FORMAT)


def from_db(text):
    """text from the database -> datetime."""
    return datetime.strptime(text, DB_FORMAT)


def tz_suffix():
    minutes = current_app.config["TZ_OFFSET_MINUTES"]
    sign = "+" if minutes >= 0 else "-"
    hh, mm = divmod(abs(minutes), 60)
    return f"{sign}{hh:02d}:{mm:02d}"


def to_api(text):
    """Database time text -> API time text with offset, e.g. 2026-09-22T19:00:00+05:30."""
    return f"{text}{tz_suffix()}" if text else None


# ----------------------------------------------------------------------------
# VALIDATION
# Never trust data from the browser (SDD 12.2). The Validator collects every
# problem so the user can fix all of them at once, instead of one per click.
# ----------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
VEHICLE_NO_RE = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}$")  # e.g. MP09AB1234


def get_json_body():
    """The JSON the client sent, or a clear error if it is missing/broken."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "INVALID_JSON", "Please send a JSON object in the request body.")
    return data


class Validator:
    """
    Usage:
        v = Validator(get_json_body())
        email = v.email("email")
        hours = v.integer("duration_hours", "Duration", minimum=1, maximum=12)
        v.done()            # <- raises one error listing every problem found
    """

    def __init__(self, data):
        self.data = data
        self.errors = {}

    def _fail(self, key, message):
        self.errors.setdefault(key, message)

    def done(self):
        if self.errors:
            raise ApiError(422, "VALIDATION_ERROR", "Please correct the highlighted fields.", self.errors)

    # -- building blocks -----------------------------------------------------
    def text(self, key, label, required=True, max_len=100):
        raw = self.data.get(key)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            if required:
                self._fail(key, f"{label} is required.")
            return None
        if not isinstance(raw, str):
            self._fail(key, f"{label} must be text.")
            return None
        value = raw.strip()
        if len(value) > max_len:
            self._fail(key, f"{label} must be at most {max_len} characters.")
            return None
        return value

    def email(self, key="email", label="Email", required=True):
        value = self.text(key, label, required, max_len=120)
        if value is None:
            return None
        if not EMAIL_RE.match(value):
            self._fail(key, f"{label} is not a valid email address.")
            return None
        return value.lower()

    def mobile(self, key="mobile", label="Mobile number", required=True):
        value = self.text(key, label, required, max_len=20)
        if value is None:
            return None
        digits = re.sub(r"\D", "", value)
        if len(digits) == 12 and digits.startswith("91"):   # +91 91234 56789
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):  # 091234 56789
            digits = digits[1:]
        if not re.fullmatch(r"[6-9]\d{9}", digits):
            self._fail(key, f"{label} must be a valid 10-digit Indian mobile number.")
            return None
        return digits

    def password(self, key="password", label="Password"):
        raw = self.data.get(key)
        if not isinstance(raw, str) or raw == "":
            self._fail(key, f"{label} is required.")
            return None
        if len(raw) < 8 or len(raw) > 128:
            self._fail(key, f"{label} must be 8 to 128 characters long.")
        elif not (re.search(r"[A-Za-z]", raw) and re.search(r"\d", raw)):
            self._fail(key, f"{label} must contain at least one letter and one number.")
        return raw

    def integer(self, key, label, minimum=None, maximum=None, required=True):
        raw = self.data.get(key)
        if raw is None or raw == "":
            if required:
                self._fail(key, f"{label} is required.")
            return None
        if isinstance(raw, bool) or not (isinstance(raw, int) or (isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()))):
            self._fail(key, f"{label} must be a whole number.")
            return None
        value = int(raw)
        if minimum is not None and value < minimum:
            self._fail(key, f"{label} must be at least {minimum}.")
            return None
        if maximum is not None and value > maximum:
            self._fail(key, f"{label} must be at most {maximum}.")
            return None
        return value

    def choice(self, key, label, options, aliases=None, required=True):
        """Value must be one of `options` (case-insensitive). `aliases` maps alternative spellings."""
        value = self.text(key, label, required, max_len=40)
        if value is None:
            return None
        normalized = value.upper().replace("-", "_")
        if aliases:
            normalized = aliases.get(normalized, normalized)
        if normalized not in options:
            self._fail(key, f"{label} must be one of: {', '.join(sorted(options))}.")
            return None
        return normalized

    def date(self, key, label, required=True):
        value = self.text(key, label, required, max_len=10)
        if value is None:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            self._fail(key, f"{label} must look like 2026-09-22 (YYYY-MM-DD).")
            return None

    def time(self, key, label, required=True):
        value = self.text(key, label, required, max_len=8)
        if value is None:
            return None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
        self._fail(key, f"{label} must look like 19:00 (HH:MM, 24-hour).")
        return None

    def vehicle_no(self, key="vehicle_no", label="Vehicle number", required=True):
        value = self.text(key, label, required, max_len=20)
        if value is None:
            return None
        compact = re.sub(r"[\s\-]", "", value).upper()   # "mp09 ab 1234" -> "MP09AB1234"
        if not VEHICLE_NO_RE.match(compact):
            self._fail(key, f"{label} looks invalid. Example: MP09 AB 1234.")
            return None
        return compact

    def boolean(self, key, label, required=False):
        raw = self.data.get(key)
        if raw is None:
            if required:
                self._fail(key, f"{label} is required.")
            return None
        if not isinstance(raw, bool):
            self._fail(key, f"{label} must be true or false.")
            return None
        return raw


# ----------------------------------------------------------------------------
# PAGING  (SDD 13.2: "paginate large datasets on the server")
# ----------------------------------------------------------------------------
def get_page_args(default_per_page=10, max_per_page=100):
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = int(request.args.get("per_page", default_per_page))
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "page and per_page must be whole numbers.")
    per_page = max(1, min(per_page, max_per_page))
    return page, per_page, (page - 1) * per_page


def page_info(page, per_page, total):
    return {"page": page, "per_page": per_page, "total": total, "pages": max(1, -(-total // per_page))}
