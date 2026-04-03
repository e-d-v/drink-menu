"""Seed script — inserts the initial admin user if not already present."""

import bcrypt
from db import get_connection

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "changeme"


def seed_admin() -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM admins WHERE username = %s", (ADMIN_USERNAME,))
        if cursor.fetchone():
            print(f"Admin user '{ADMIN_USERNAME}' already exists — skipping.")
            return

        password_hash = bcrypt.hashpw(
            ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        cursor.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
            (ADMIN_USERNAME, password_hash),
        )
        conn.commit()
        print(f"Admin user '{ADMIN_USERNAME}' created successfully.")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    seed_admin()
