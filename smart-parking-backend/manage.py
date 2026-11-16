"""
Handy maintenance commands.

    python manage.py reset-db                       wipe the database and reload the demo data
    python manage.py create-admin EMAIL "Full Name" PASSWORD   add another administrator
"""
import os
import sys

from werkzeug.security import generate_password_hash

from app import create_app
from app.db import get_db
from app.utils import Validator, now_local, to_db


def reset_db():
    path = create_app({"AUTO_SEED": False}).config["DATABASE_PATH"]
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    create_app()  # recreates the tables and loads the demo data
    print("Database reset. Demo data loaded.")


def create_admin(email, name, password):
    app = create_app()
    with app.app_context(), app.test_request_context():
        v = Validator({"email": email, "password": password})
        email, password = v.email(), v.password()
        v.done()
        get_db().execute(
            "INSERT INTO users (full_name, email, mobile, password_hash, role, created_at) VALUES (?, ?, '9000000000', ?, 'ADMIN', ?)",
            (name, email, generate_password_hash(password), to_db(now_local())))
    print(f"Administrator {email} created.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["reset-db"]:
        reset_db()
    elif len(args) == 4 and args[0] == "create-admin":
        create_admin(*args[1:])
    else:
        print(__doc__)
