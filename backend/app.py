"""Drink Menu & Recipe Book — FastAPI application."""

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db import get_connection

# Session lifetime in hours
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "24"))

app = FastAPI(title="Drink Menu & Recipe Book API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_admin_by_username(cursor, username: str):
    """Return the admin row for *username*, or None if not found."""
    cursor.execute(
        "SELECT id, username, password_hash FROM admins WHERE username = %s",
        (username,),
    )
    return cursor.fetchone()


def _create_session(cursor, admin_id: int) -> tuple[str, datetime]:
    """Insert a new session row and return (token, expires_at)."""
    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # store as naive UTC
    expires_at = now + timedelta(hours=SESSION_HOURS)
    cursor.execute(
        """
        INSERT INTO sessions (token, admin_id, created_at, expires_at)
        VALUES (%s, %s, %s, %s)
        """,
        (token, admin_id, now, expires_at),
    )
    return token, expires_at


def _require_auth(request: Request):
    """Validate the Authorization: Bearer <token> header against the sessions table.

    Returns None on success (valid, non-expired token).
    Returns a 401 JSONResponse if the header is missing, malformed, token not
    found, or the session has expired.

    Requirements: 4.6
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    token = auth_header[len("Bearer "):]
    if not token:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT token, expires_at FROM sessions WHERE token = %s",
            (token,),
        )
        session = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()

    if session is None:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if session["expires_at"] < now:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    return None


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/auth/login")
async def login(request: Request):
    """Authenticate an admin and return a session token.

    Accepts JSON body: {"username": "...", "password": "..."}
    Returns {"token": "..."} on success, 401 on invalid credentials.

    Requirements 4.1, 4.2, 4.3
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid request"})

    username = body.get("username", "")
    password = body.get("password", "")

    if not username or not password:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        admin = _get_admin_by_username(cursor, username)

        if admin is None:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Verify password against stored bcrypt hash
        password_matches = bcrypt.checkpw(
            password.encode("utf-8"),
            admin["password_hash"].encode("utf-8"),
        )
        if not password_matches:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Credentials valid — create a session
        token, _ = _create_session(cursor, admin["id"])
        conn.commit()
        cursor.close()
    finally:
        conn.close()

    return {"token": token}


@app.post("/auth/logout")
async def logout(request: Request):
    """Invalidate the current session token.

    Expects an ``Authorization: Bearer <token>`` header.
    Deletes the matching row from the ``sessions`` table and returns 200.
    Returns 401 if the header is missing or the token is not found.

    Requirements 4.5
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    token = auth_header[len("Bearer "):]
    if not token:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()
        cursor.close()
    finally:
        conn.close()

    return JSONResponse(status_code=200, content={"message": "Logged out"})


@app.get("/ingredients")
def list_ingredients():
    """Return all ingredients where in_cabinet = true.

    Requirements 2.2
    """
    query = """
        SELECT id, name, in_cabinet
        FROM ingredients
        WHERE in_cabinet = TRUE
        ORDER BY name
    """
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    # Ensure in_cabinet is a proper boolean in the response
    for row in rows:
        row["in_cabinet"] = bool(row["in_cabinet"])

    return rows


@app.get("/drinks")
def list_drinks():
    """Return drinks whose every ingredient is in the cabinet.

    A drink with no ingredients is excluded (Requirements 1.1, 1.2).
    """
    query = """
        SELECT
            d.id,
            d.name,
            d.image_url,
            d.abv,
            d.recipe_type
        FROM drinks d
        JOIN drink_ingredients di ON di.drink_id = d.id
        JOIN ingredients i ON i.id = di.ingredient_id
        GROUP BY d.id, d.name, d.image_url, d.abv, d.recipe_type
        HAVING
            COUNT(i.id) > 0
            AND COUNT(i.id) = SUM(CASE WHEN i.in_cabinet = TRUE THEN 1 ELSE 0 END)
        ORDER BY d.name
    """
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    return rows


@app.get("/drinks/{drink_id}")
def get_drink(drink_id: int):
    """Return a single drink with full recipe detail.

    Includes ingredients list, instructions, and url fields.
    Returns 404 if the drink is not found (Requirements 3.4).
    """
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        # Fetch the drink row
        cursor.execute(
            """
            SELECT
                d.id,
                d.name,
                d.image_url,
                d.abv,
                d.recipe_type,
                r.instructions,
                r.url
            FROM drinks d
            LEFT JOIN recipes r ON r.drink_id = d.id
            WHERE d.id = %s
            """,
            (drink_id,),
        )
        drink = cursor.fetchone()

        if drink is None:
            return JSONResponse(status_code=404, content={"error": "Not found"})

        # Fetch the ingredient names for this drink
        cursor.execute(
            """
            SELECT i.name
            FROM drink_ingredients di
            JOIN ingredients i ON i.id = di.ingredient_id
            WHERE di.drink_id = %s
            ORDER BY i.name
            """,
            (drink_id,),
        )
        ingredient_rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    drink["ingredients"] = [row["name"] for row in ingredient_rows]
    return drink


# ---------------------------------------------------------------------------
# Admin — ingredients
# ---------------------------------------------------------------------------

@app.get("/admin/ingredients")
async def admin_list_ingredients(request: Request):
    """List all ingredients with cabinet status. Requirements: 5.1"""
    err = _require_auth(request)
    if err:
        return err
    # TODO: implement in task 4.1
    return []

@app.post("/admin/ingredients")
async def admin_add_ingredient(request: Request):
    """Add a new ingredient. Requirements: 5.3, 5.4"""
    err = _require_auth(request)
    if err:
        return err
    # TODO: implement in task 4.2
    return JSONResponse(status_code=501, content={"error": "Not implemented"})

@app.patch("/admin/ingredients/{ingredient_id}")
async def admin_toggle_ingredient(ingredient_id: int, request: Request):
    """Toggle cabinet status. Requirements: 5.2"""
    err = _require_auth(request)
    if err:
        return err
    # TODO: implement in task 4.3
    return JSONResponse(status_code=501, content={"error": "Not implemented"})

# ---------------------------------------------------------------------------
# Admin — drinks
# ---------------------------------------------------------------------------

@app.get("/admin/drinks")
async def admin_list_drinks(request: Request):
    """List all drinks regardless of cabinet state. Requirements: 8.1"""
    err = _require_auth(request)
    if err:
        return err
    # TODO: implement in task 5.1
    return []

@app.post("/admin/drinks")
async def admin_create_drink(request: Request):
    """Create drink + recipe. Requirements: 6.2, 7.2, 10.1, 10.2, 10.4"""
    err = _require_auth(request)
    if err:
        return err
    # TODO: implement in task 5.3
    return JSONResponse(status_code=501, content={"error": "Not implemented"})

@app.put("/admin/drinks/{drink_id}")
async def admin_update_drink(drink_id: int, request: Request):
    """Update drink + recipe. Requirements: 8.3"""
    err = _require_auth(request)
    if err:
        return err
    # TODO: implement in task 5.8
    return JSONResponse(status_code=501, content={"error": "Not implemented"})

@app.delete("/admin/drinks/{drink_id}")
async def admin_delete_drink(drink_id: int, request: Request):
    """Delete drink + recipe. Requirements: 8.4"""
    err = _require_auth(request)
    if err:
        return err
    # TODO: implement in task 5.10
    return JSONResponse(status_code=501, content={"error": "Not implemented"})
