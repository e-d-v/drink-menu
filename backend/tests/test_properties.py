"""Property-based tests for the Drink Menu & Recipe Book API.

# Feature: drink-menu-recipe-book, Property 1: Cabinet filtering correctness
# Feature: drink-menu-recipe-book, Property 6: Recipe type round-trip
"""

import sqlite3
import sys
import os
from datetime import datetime
from unittest.mock import patch

import bcrypt
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Make the backend package importable when running from the backend/ directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as app_module  # noqa: E402
from app import app  # noqa: E402


# ===========================================================================
# Database infrastructure
# ===========================================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingredients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    in_cabinet INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS drinks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    image_url   TEXT,
    abv         INTEGER NOT NULL,
    recipe_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drink_ingredients (
    drink_id      INTEGER NOT NULL,
    ingredient_id INTEGER NOT NULL,
    PRIMARY KEY (drink_id, ingredient_id),
    FOREIGN KEY (drink_id)      REFERENCES drinks(id)      ON DELETE CASCADE,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recipes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    drink_id     INTEGER NOT NULL UNIQUE,
    instructions TEXT,
    url          TEXT,
    FOREIGN KEY (drink_id) REFERENCES drinks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    admin_id   INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE CASCADE
);
"""


def _make_db() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection with the full schema applied."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


class _FakeConnection:
    """Makes a sqlite3.Connection look like a mysql-connector connection."""

    def __init__(self, sqlite_conn: sqlite3.Connection) -> None:
        self._conn = sqlite_conn

    def cursor(self, dictionary: bool = False):
        cur = self._conn.cursor()
        return _DictCursor(cur) if dictionary else cur

    def close(self):
        pass  # keep the underlying connection alive across calls

    def commit(self):
        self._conn.commit()


class _DictCursor:
    """Wraps sqlite3.Cursor so fetchall/fetchone return dicts, like mysql-connector."""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cur = cursor

    def execute(self, query: str, params=None):
        # Translate MySQL placeholders and boolean literals to SQLite equivalents
        q = query.replace("%s", "?").replace("= TRUE", "= 1").replace("= FALSE", "= 0")
        self._cur.execute(q, params) if params is not None else self._cur.execute(q)

    def fetchall(self):
        cols = [d[0] for d in self._cur.description]
        return [dict(zip(cols, self._coerce_row(row))) for row in self._cur.fetchall()]

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return dict(zip(cols, self._coerce_row(row)))

    @staticmethod
    def _coerce_row(row):
        """Convert ISO datetime strings to datetime objects (mimics MySQL driver)."""
        result = []
        for val in row:
            if isinstance(val, str):
                try:
                    val = datetime.fromisoformat(val)
                except ValueError:
                    pass
            result.append(val)
        return result

    def close(self):
        self._cur.close()

    @property
    def lastrowid(self):
        return self._cur.lastrowid


# ===========================================================================
# Test client factory
# ===========================================================================

def make_client(sqlite_conn: sqlite3.Connection) -> TestClient:
    """Return a TestClient whose get_connection is patched to use sqlite_conn."""
    fake = _FakeConnection(sqlite_conn)
    # The patch is entered here and left open for the duration of the test.
    # Tests that need the patch active only during the request can use the
    # context-manager form directly; this helper covers the common case.
    patcher = patch.object(app_module, "get_connection", return_value=fake)
    patcher.start()
    # Attach the patcher so callers can stop it if needed (pytest fixtures handle cleanup)
    client = TestClient(app)
    client._kiro_patcher = patcher  # type: ignore[attr-defined]
    return client


@pytest.fixture
def db():
    """Pytest fixture: fresh in-memory DB, auto-closed after each test."""
    conn = _make_db()
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    """Pytest fixture: TestClient patched against the `db` fixture connection."""
    c = make_client(db)
    yield c
    c._kiro_patcher.stop()


# ===========================================================================
# Seed helpers
# ===========================================================================

def seed_ingredients(conn, *items):
    """Insert ingredients. Each item is (name, in_cabinet: bool).
    Returns list of inserted IDs in the same order."""
    ids = []
    for name, in_cabinet in items:
        cur = conn.execute(
            "INSERT INTO ingredients (name, in_cabinet) VALUES (?, ?)",
            (name, 1 if in_cabinet else 0),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def seed_drink(conn, *, name="Margarita", abv=150, recipe_type="inline",
               image_url=None, instructions="Shake well.", url=None,
               ingredient_names=("Tequila", "Lime Juice")):
    """Insert a drink + recipe + ingredients; return the new drink_id."""
    cur = conn.execute(
        "INSERT INTO drinks (name, image_url, abv, recipe_type) VALUES (?, ?, ?, ?)",
        (name, image_url, abv, recipe_type),
    )
    drink_id = cur.lastrowid
    conn.execute(
        "INSERT INTO recipes (drink_id, instructions, url) VALUES (?, ?, ?)",
        (drink_id, instructions, url),
    )
    for ing_name in ingredient_names:
        conn.execute(
            "INSERT OR IGNORE INTO ingredients (name, in_cabinet) VALUES (?, 1)", (ing_name,)
        )
        row = conn.execute(
            "SELECT id FROM ingredients WHERE name = ?", (ing_name,)
        ).fetchone()
        conn.execute(
            "INSERT INTO drink_ingredients (drink_id, ingredient_id) VALUES (?, ?)",
            (drink_id, row[0]),
        )
    conn.commit()
    return drink_id


def seed_admin(conn, username: str = "admin", password: str = "secret") -> int:
    """Insert an admin with a bcrypt-hashed password; return the admin id."""
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur = conn.execute(
        "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    conn.commit()
    return cur.lastrowid

_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=32),
    min_size=1,
    max_size=40,
)

_ingredient_st = st.fixed_dictionaries({"name": _name_st, "in_cabinet": st.booleans()})


def _drink_st(num_ingredients: int):
    if num_ingredients == 0:
        return st.nothing()
    return st.fixed_dictionaries({
        "name": _name_st,
        "abv": st.integers(min_value=0, max_value=1000),
        "recipe_type": st.sampled_from(["inline", "link"]),
        "ingredient_indices": st.lists(
            st.integers(min_value=0, max_value=num_ingredients - 1),
            min_size=1,
            max_size=min(4, num_ingredients),
            unique=True,
        ),
    })


# ===========================================================================
# Property 1: Cabinet filtering correctness
# ===========================================================================

@settings(max_examples=100)
@given(
    ingredients=st.lists(_ingredient_st, min_size=1, max_size=8).filter(
        lambda lst: len({i["name"] for i in lst}) == len(lst)
    ),
    drinks_seed=st.data(),
)
def test_property_1_cabinet_filtering_correctness(ingredients, drinks_seed):
    """Property 1: Cabinet filtering correctness.

    GET /drinks returns ONLY drinks whose every ingredient is in the cabinet,
    and ALL such drinks.

    # Feature: drink-menu-recipe-book, Property 1: Cabinet filtering correctness
    Validates: Requirements 1.2
    """
    num_ingredients = len(ingredients)
    drinks = drinks_seed.draw(st.lists(_drink_st(num_ingredients), min_size=0, max_size=6))

    conn = _make_db()

    ingredient_ids = []
    for ing in ingredients:
        cur = conn.execute(
            "INSERT INTO ingredients (name, in_cabinet) VALUES (?, ?)",
            (ing["name"], 1 if ing["in_cabinet"] else 0),
        )
        ingredient_ids.append(cur.lastrowid)
    conn.commit()

    drink_ids = []
    for drink in drinks:
        cur = conn.execute(
            "INSERT INTO drinks (name, image_url, abv, recipe_type) VALUES (?, ?, ?, ?)",
            (drink["name"], None, drink["abv"], drink["recipe_type"]),
        )
        drink_id = cur.lastrowid
        drink_ids.append(drink_id)
        for idx in drink["ingredient_indices"]:
            conn.execute(
                "INSERT INTO drink_ingredients (drink_id, ingredient_id) VALUES (?, ?)",
                (drink_id, ingredient_ids[idx]),
            )
    conn.commit()

    # Oracle: drinks where every ingredient is in the cabinet
    cabinet_set = {ingredient_ids[i] for i, ing in enumerate(ingredients) if ing["in_cabinet"]}
    expected_ids = {
        drink_id
        for drink, drink_id in zip(drinks, drink_ids)
        if {ingredient_ids[idx] for idx in drink["ingredient_indices"]}.issubset(cabinet_set)
    }

    with patch.object(app_module, "get_connection", return_value=_FakeConnection(conn)):
        response = TestClient(app).get("/drinks")

    assert response.status_code == 200
    returned_ids = {d["id"] for d in response.json()}

    for drink_item in response.json():
        assert drink_item["id"] in expected_ids, (
            f"Drink id={drink_item['id']} ({drink_item['name']!r}) returned but not all "
            f"ingredients are in cabinet."
        )
    for expected_id in expected_ids:
        assert expected_id in returned_ids, (
            f"Drink id={expected_id} has all ingredients in cabinet but was NOT returned."
        )

    conn.close()


# ===========================================================================
# Property 6: Recipe type round-trip
# ===========================================================================

@settings(max_examples=100)
@given(
    name=_name_st,
    abv=st.integers(min_value=0, max_value=1000),
    recipe_type=st.sampled_from(["inline", "link"]),
)
def test_property_6_recipe_type_round_trip(name, abv, recipe_type):
    """Property 6: Recipe type round-trip.

    GET /drinks/:id returns a recipe_type that matches the value used at creation.

    # Feature: drink-menu-recipe-book, Property 6: Recipe type round-trip
    Validates: Requirements 3.4
    """
    conn = _make_db()
    drink_id = seed_drink(
        conn,
        name=name,
        abv=abv,
        recipe_type=recipe_type,
        instructions="Shake well." if recipe_type == "inline" else None,
        url="https://example.com/recipe" if recipe_type == "link" else None,
    )

    with patch.object(app_module, "get_connection", return_value=_FakeConnection(conn)):
        response = TestClient(app).get(f"/drinks/{drink_id}")

    assert response.status_code == 200
    assert response.json()["recipe_type"] == recipe_type
    conn.close()


# ===========================================================================
# Unit tests: GET /drinks/:id
# ===========================================================================

class TestGetDrinkById:
    """Unit tests for GET /drinks/{drink_id}. Requirements 3.4"""

    def test_returns_drink_with_all_fields(self, db, client):
        drink_id = seed_drink(
            db,
            name="Margarita", abv=150, recipe_type="inline",
            image_url="https://example.com/margarita.jpg",
            instructions="Combine ingredients.\nShake well.",
            ingredient_names=["Tequila", "Triple Sec", "Lime Juice"],
        )
        data = client.get(f"/drinks/{drink_id}").json()
        assert data["id"] == drink_id
        assert data["name"] == "Margarita"
        assert data["image_url"] == "https://example.com/margarita.jpg"
        assert data["abv"] == 150
        assert data["recipe_type"] == "inline"
        assert data["instructions"] == "Combine ingredients.\nShake well."
        assert data["url"] is None
        assert sorted(data["ingredients"]) == ["Lime Juice", "Tequila", "Triple Sec"]

    def test_returns_404_for_nonexistent_drink(self, client):
        response = client.get("/drinks/9999")
        assert response.status_code == 404
        assert response.json() == {"error": "Not found"}

    def test_link_type_drink_returns_url_and_null_instructions(self, db, client):
        drink_id = seed_drink(
            db, name="Mojito", abv=80, recipe_type="link",
            instructions=None, url="https://example.com/mojito-recipe",
            ingredient_names=["Rum", "Mint"],
        )
        data = client.get(f"/drinks/{drink_id}").json()
        assert data["recipe_type"] == "link"
        assert data["url"] == "https://example.com/mojito-recipe"
        assert data["instructions"] is None

    def test_ingredients_list_is_present(self, db, client):
        drink_id = seed_drink(db, ingredient_names=["Vodka", "Orange Juice", "Grenadine"])
        data = client.get(f"/drinks/{drink_id}").json()
        assert isinstance(data["ingredients"], list)
        assert sorted(data["ingredients"]) == sorted(["Vodka", "Orange Juice", "Grenadine"])

    def test_drink_with_no_image_url_returns_null(self, db, client):
        drink_id = seed_drink(db, image_url=None)
        assert client.get(f"/drinks/{drink_id}").json()["image_url"] is None


# ===========================================================================
# Unit tests: GET /ingredients
# ===========================================================================

class TestGetIngredients:
    """Unit tests for GET /ingredients. Requirements 2.2"""

    def test_returns_only_in_cabinet_ingredients(self, db, client):
        seed_ingredients(db, ("Tequila", True), ("Vodka", False), ("Rum", True))
        data = client.get("/ingredients").json()
        names = {item["name"] for item in data}
        assert names == {"Tequila", "Rum"}

    def test_returns_correct_json_shape(self, db, client):
        seed_ingredients(db, ("Gin", True))
        data = client.get("/ingredients").json()
        assert len(data) == 1
        assert {"id", "name", "in_cabinet"} <= data[0].keys()
        assert data[0]["name"] == "Gin"
        assert data[0]["in_cabinet"] is True

    def test_returns_empty_list_when_none_in_cabinet(self, db, client):
        seed_ingredients(db, ("Whiskey", False))
        assert client.get("/ingredients").json() == []

    def test_returns_empty_list_when_table_is_empty(self, client):
        assert client.get("/ingredients").json() == []

    def test_in_cabinet_field_is_boolean(self, db, client):
        seed_ingredients(db, ("Lime Juice", True))
        data = client.get("/ingredients").json()
        assert data[0]["in_cabinet"] is True  # bool, not int 1


# ===========================================================================
# Unit tests: POST /auth/login
# ===========================================================================

class TestLogin:
    """Unit tests for POST /auth/login. Requirements 4.1, 4.2, 4.3"""

    def test_valid_credentials_return_token(self, db, client):
        """Valid username + password returns 200 with a token string."""
        seed_admin(db, username="admin", password="secret")
        response = client.post("/auth/login", json={"username": "admin", "password": "secret"})
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 0

    def test_token_is_stored_in_sessions_table(self, db, client):
        """After a successful login the token must exist in the sessions table."""
        seed_admin(db, username="admin", password="secret")
        response = client.post("/auth/login", json={"username": "admin", "password": "secret"})
        assert response.status_code == 200
        token = response.json()["token"]
        row = db.execute("SELECT token FROM sessions WHERE token = ?", (token,)).fetchone()
        assert row is not None, "Token was not persisted in the sessions table"

    def test_session_has_future_expiry(self, db, client):
        """The stored session must have an expires_at in the future."""
        seed_admin(db, username="admin", password="secret")
        client.post("/auth/login", json={"username": "admin", "password": "secret"})
        row = db.execute("SELECT expires_at FROM sessions").fetchone()
        assert row is not None
        # expires_at is stored as an ISO-format string by SQLite
        from datetime import datetime
        expires_at = datetime.fromisoformat(str(row[0]))
        assert expires_at > datetime.utcnow(), "Session expiry should be in the future"

    def test_wrong_password_returns_401(self, db, client):
        """Wrong password returns 401 Unauthorized."""
        seed_admin(db, username="admin", password="secret")
        response = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_unknown_username_returns_401(self, db, client):
        """Unknown username returns 401 Unauthorized."""
        response = client.post("/auth/login", json={"username": "nobody", "password": "secret"})
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_missing_username_returns_401(self, db, client):
        """Missing username field returns 401."""
        response = client.post("/auth/login", json={"password": "secret"})
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_missing_password_returns_401(self, db, client):
        """Missing password field returns 401."""
        response = client.post("/auth/login", json={"username": "admin"})
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_each_login_creates_a_new_token(self, db, client):
        """Two successful logins produce two distinct tokens."""
        seed_admin(db, username="admin", password="secret")
        r1 = client.post("/auth/login", json={"username": "admin", "password": "secret"})
        r2 = client.post("/auth/login", json={"username": "admin", "password": "secret"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["token"] != r2.json()["token"]


# ===========================================================================
# Unit tests: POST /auth/logout
# ===========================================================================

class TestLogout:
    """Unit tests for POST /auth/logout. Requirements 4.5"""

    def _login(self, client, db):
        """Helper: seed an admin, log in, and return the token."""
        seed_admin(db, username="admin", password="secret")
        response = client.post("/auth/login", json={"username": "admin", "password": "secret"})
        assert response.status_code == 200
        return response.json()["token"]

    def test_logout_returns_200(self, db, client):
        """Valid token in Authorization header returns 200."""
        token = self._login(client, db)
        response = client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_logout_deletes_session_row(self, db, client):
        """After logout the session row is removed from the sessions table."""
        token = self._login(client, db)
        client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        row = db.execute("SELECT token FROM sessions WHERE token = ?", (token,)).fetchone()
        assert row is None, "Session row should have been deleted after logout"

    def test_logout_without_auth_header_returns_401(self, client):
        """Request with no Authorization header returns 401."""
        response = client.post("/auth/logout")
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_logout_with_invalid_token_returns_200(self, db, client):
        """Logout with a token that doesn't exist in the DB still returns 200 (idempotent)."""
        seed_admin(db, username="admin", password="secret")
        response = client.post(
            "/auth/logout",
            headers={"Authorization": "Bearer nonexistenttoken"},
        )
        # Deleting a non-existent row is a no-op; endpoint returns 200
        assert response.status_code == 200

    def test_logout_with_malformed_auth_header_returns_401(self, client):
        """Authorization header without 'Bearer ' prefix returns 401."""
        response = client.post(
            "/auth/logout",
            headers={"Authorization": "Token sometoken"},
        )
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_logout_invalidates_token_for_admin_routes(self, db, client):
        """After logout, using the same token on an admin route returns 401."""
        token = self._login(client, db)
        # Confirm the token works before logout
        response_before = client.get(
            "/admin/ingredients",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response_before.status_code != 401, "Token should be valid before logout"
        # Logout
        client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        # Now the same token must be rejected
        response_after = client.get(
            "/admin/ingredients",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response_after.status_code == 401
        assert response_after.json() == {"error": "Unauthorized"}


# ===========================================================================
# Unit tests: Admin route authentication (Requirements 4.6)
# ===========================================================================

class TestAdminAuth:
    """Every /admin/* endpoint must return 401 when no valid token is provided.

    Requirements 4.6
    """

    ADMIN_ROUTES = [
        ("GET",    "/admin/ingredients"),
        ("POST",   "/admin/ingredients"),
        ("PATCH",  "/admin/ingredients/1"),
        ("GET",    "/admin/drinks"),
        ("POST",   "/admin/drinks"),
        ("PUT",    "/admin/drinks/1"),
        ("DELETE", "/admin/drinks/1"),
    ]

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_missing_auth_header_returns_401(self, client, method, path):
        """Request with no Authorization header returns 401."""
        response = client.request(method, path)
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_malformed_auth_header_returns_401(self, client, method, path):
        """Request with malformed Authorization header returns 401."""
        response = client.request(method, path, headers={"Authorization": "Token badtoken"})
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_invalid_token_returns_401(self, client, method, path):
        """Request with a token not in the sessions table returns 401."""
        response = client.request(
            method, path,
            headers={"Authorization": "Bearer thisisnotavalidtoken"},
        )
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}


# ===========================================================================
# Property 8: API rejects unauthenticated admin requests
# ===========================================================================

_ADMIN_ENDPOINTS = [
    ("GET",    "/admin/ingredients"),
    ("POST",   "/admin/ingredients"),
    ("PATCH",  "/admin/ingredients/1"),
    ("GET",    "/admin/drinks"),
    ("POST",   "/admin/drinks"),
    ("PUT",    "/admin/drinks/1"),
    ("DELETE", "/admin/drinks/1"),
]

_token_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        max_codepoint=127,  # ASCII only — HTTP headers cannot carry non-ASCII bytes
    ),
    min_size=1,
    max_size=64,
)

_auth_header_st = st.one_of(
    # No Authorization header at all
    st.just({}),
    # Wrong scheme
    st.builds(lambda t: {"Authorization": f"Token {t}"}, _token_st),
    # Bearer with a random token that is never inserted into the sessions table
    st.builds(lambda t: {"Authorization": f"Bearer {t}"}, _token_st),
    # Empty Bearer value
    st.just({"Authorization": "Bearer "}),
    # Completely random header value
    st.builds(lambda t: {"Authorization": t}, _token_st),
)


@settings(max_examples=100)
@given(
    endpoint=st.sampled_from(_ADMIN_ENDPOINTS),
    headers=_auth_header_st,
)
def test_property_8_api_rejects_unauthenticated_admin_requests(endpoint, headers):
    """Property 8: API rejects unauthenticated admin requests.

    For any admin endpoint and any request that does not carry a valid session
    token, the API must return 401 with {"error": "Unauthorized"}.

    # Feature: drink-menu-recipe-book, Property 8: API rejects unauthenticated admin requests
    Validates: Requirements 4.6
    """
    method, path = endpoint
    conn = _make_db()

    with patch.object(app_module, "get_connection", return_value=_FakeConnection(conn)):
        response = TestClient(app).request(method, path, headers=headers)

    assert response.status_code == 401, (
        f"{method} {path} with headers={headers!r} returned {response.status_code}, expected 401"
    )
    assert response.json() == {"error": "Unauthorized"}, (
        f"{method} {path} returned unexpected body: {response.json()!r}"
    )

    conn.close()
