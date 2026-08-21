"""Create a dashboard/API user without storing a plaintext password."""
import getpass
import sys

from sqlalchemy import select
from app.database.session import SessionLocal
from app.models.domain import User
from app.services.auth import hash_password


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else input("Username: ").strip()
    password = getpass.getpass("Password: ")
    with SessionLocal.begin() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing:
            existing.password_hash = hash_password(password)
            existing.active = True
        else:
            db.add(User(username=username, password_hash=hash_password(password)))
    print(f"User '{username}' is ready")