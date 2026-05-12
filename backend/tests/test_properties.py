"""Property-based tests for the Drink Menu & Recipe Book API.

# Feature: drink-menu-recipe-book, Property 1: Cabinet filtering correctness
# Feature: drink-menu-recipe-book, Property 6: Recipe type round-trip
"""

import sqlite3
import sys
import os
from unittest.mock import patch

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
        return [dict(zip(cols, row)) for row in self._cur.fetchall()]

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return dict(zip(cols, row))

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


# ===========================================================================
# Hypothesis strategies
# ===========================================================================

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
