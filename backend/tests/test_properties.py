"""Property-based tests for the Drink Menu & Recipe Book API.

# Feature: drink-menu-recipe-book, Property 1: Cabinet filtering correctness
# Feature: drink-menu-recipe-book, Property 6: Recipe type round-trip
"""

import sqlite3
import sys
import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Make the backend package importable when running from the backend/ directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as app_module  # noqa: E402  (import after sys.path manipulation)
from app import app  # noqa: E402


# ---------------------------------------------------------------------------
# SQLite in-memory database helpers
# ---------------------------------------------------------------------------

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
"""


def _make_sqlite_conn(db_path: str = ":memory:") -> sqlite3.Connection:
    """Return a SQLite connection with the test schema applied."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


class _FakeConnection:
    """Thin wrapper that makes a sqlite3.Connection look like a mysql-connector
    connection to the extent that app.py uses it (cursor, close)."""

    def __init__(self, sqlite_conn: sqlite3.Connection) -> None:
        self._conn = sqlite_conn

    def cursor(self, dictionary: bool = False):
        cur = self._conn.cursor()
        if dictionary:
            # Wrap so .fetchall() returns list-of-dicts
            return _DictCursor(cur)
        return cur

    def close(self):
        # Do NOT close the underlying connection — we reuse it across calls.
        pass

    def commit(self):
        self._conn.commit()


class _DictCursor:
    """Wraps a sqlite3.Cursor and makes fetchall() return list[dict]."""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cur = cursor

    def execute(self, query: str, params=None):
        # Translate MySQL-style %s placeholders to SQLite-style ?
        translated = query.replace("%s", "?")
        # SQLite uses 1/0 for booleans; translate TRUE/FALSE literals
        translated = translated.replace("= TRUE", "= 1").replace("= FALSE", "= 0")
        if params is not None:
            self._cur.execute(translated, params)
        else:
            self._cur.execute(translated)

    def fetchall(self):
        columns = [desc[0] for desc in self._cur.description]
        return [dict(zip(columns, row)) for row in self._cur.fetchall()]

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in self._cur.description]
        return dict(zip(columns, row))

    def close(self):
        self._cur.close()

    @property
    def lastrowid(self):
        return self._cur.lastrowid


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# A non-empty, printable text string (no NUL bytes, reasonable length)
_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=32),
    min_size=1,
    max_size=40,
)

# An ingredient: (name, in_cabinet)
_ingredient_st = st.fixed_dictionaries(
    {
        "name": _name_st,
        "in_cabinet": st.booleans(),
    }
)

# A drink: (name, abv, recipe_type, ingredient_indices)
# ingredient_indices is a list of indices into the ingredient list
def _drink_st(num_ingredients: int):
    if num_ingredients == 0:
        return st.nothing()
    return st.fixed_dictionaries(
        {
            "name": _name_st,
            "abv": st.integers(min_value=0, max_value=1000),
            "recipe_type": st.sampled_from(["inline", "link"]),
            # Each drink has 1..min(4, num_ingredients) ingredients
            "ingredient_indices": st.lists(
                st.integers(min_value=0, max_value=num_ingredients - 1),
                min_size=1,
                max_size=min(4, num_ingredients),
                unique=True,
            ),
        }
    )


# ---------------------------------------------------------------------------
# Property 1: Cabinet filtering correctness
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    ingredients=st.lists(_ingredient_st, min_size=1, max_size=8).filter(
        lambda lst: len({i["name"] for i in lst}) == len(lst)  # unique names
    ),
    drinks_seed=st.data(),
)
def test_property_1_cabinet_filtering_correctness(ingredients, drinks_seed):
    """Property 1: Cabinet filtering correctness.

    For any set of drinks in the database and any cabinet configuration,
    GET /drinks returns ONLY drinks for which every associated ingredient
    has in_cabinet = true, AND includes ALL such drinks.

    Validates: Requirements 1.2
    """
    # Feature: drink-menu-recipe-book, Property 1: Cabinet filtering correctness

    num_ingredients = len(ingredients)

    # Draw a list of drinks (may be empty)
    drinks = drinks_seed.draw(
        st.lists(_drink_st(num_ingredients), min_size=0, max_size=6)
    )

    # -----------------------------------------------------------------------
    # Build an in-memory SQLite database and populate it
    # -----------------------------------------------------------------------
    sqlite_conn = _make_sqlite_conn()

    # Insert ingredients
    ingredient_ids = []
    for ing in ingredients:
        cur = sqlite_conn.execute(
            "INSERT INTO ingredients (name, in_cabinet) VALUES (?, ?)",
            (ing["name"], 1 if ing["in_cabinet"] else 0),
        )
        ingredient_ids.append(cur.lastrowid)
    sqlite_conn.commit()

    # Insert drinks and their ingredient links
    drink_ids = []
    for drink in drinks:
        cur = sqlite_conn.execute(
            "INSERT INTO drinks (name, image_url, abv, recipe_type) VALUES (?, ?, ?, ?)",
            (drink["name"], None, drink["abv"], drink["recipe_type"]),
        )
        drink_id = cur.lastrowid
        drink_ids.append(drink_id)
        for idx in drink["ingredient_indices"]:
            sqlite_conn.execute(
                "INSERT INTO drink_ingredients (drink_id, ingredient_id) VALUES (?, ?)",
                (drink_id, ingredient_ids[idx]),
            )
    sqlite_conn.commit()

    # -----------------------------------------------------------------------
    # Compute the expected set of available drink IDs (pure Python oracle)
    # -----------------------------------------------------------------------
    cabinet_set = {
        ingredient_ids[i]
        for i, ing in enumerate(ingredients)
        if ing["in_cabinet"]
    }

    expected_available_ids = set()
    for drink, drink_id in zip(drinks, drink_ids):
        drink_ingredient_ids = {ingredient_ids[idx] for idx in drink["ingredient_indices"]}
        # A drink is available iff it has ≥1 ingredient and ALL are in cabinet
        if drink_ingredient_ids and drink_ingredient_ids.issubset(cabinet_set):
            expected_available_ids.add(drink_id)

    # -----------------------------------------------------------------------
    # Patch db.get_connection to return our fake SQLite connection
    # -----------------------------------------------------------------------
    fake_conn = _FakeConnection(sqlite_conn)

    with patch.object(app_module, "get_connection", return_value=fake_conn):
        client = TestClient(app)
        response = client.get("/drinks")

    assert response.status_code == 200
    result = response.json()
    returned_ids = {drink["id"] for drink in result}

    # -----------------------------------------------------------------------
    # Assert both directions of the property
    # -----------------------------------------------------------------------

    # Direction 1: Every drink in the response must have ALL ingredients in cabinet
    for drink_item in result:
        assert drink_item["id"] in expected_available_ids, (
            f"Drink id={drink_item['id']} (name={drink_item['name']!r}) was returned "
            f"but not all its ingredients are in the cabinet."
        )

    # Direction 2: Every drink with ALL ingredients in cabinet must be in the response
    for expected_id in expected_available_ids:
        assert expected_id in returned_ids, (
            f"Drink id={expected_id} has all ingredients in cabinet but was NOT returned."
        )

    sqlite_conn.close()


# ---------------------------------------------------------------------------
# Unit tests for GET /drinks/:id  (task 2.3, Requirements 3.4)
# ---------------------------------------------------------------------------

_SCHEMA_WITH_RECIPES = _SCHEMA + """
CREATE TABLE IF NOT EXISTS recipes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    drink_id     INTEGER NOT NULL UNIQUE,
    instructions TEXT,
    url          TEXT,
    FOREIGN KEY (drink_id) REFERENCES drinks(id) ON DELETE CASCADE
);
"""


def _make_sqlite_conn_with_recipes() -> sqlite3.Connection:
    """Return a SQLite connection with the full schema (including recipes)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_WITH_RECIPES)
    conn.commit()
    return conn


def _seed_drink(conn, *, name="Margarita", abv=150, recipe_type="inline",
                image_url=None, instructions="Shake well.", url=None,
                ingredient_names=("Tequila", "Lime Juice")):
    """Insert a drink + recipe + ingredients into the SQLite DB; return drink_id."""
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
        # Insert ingredient if not already present
        conn.execute(
            "INSERT OR IGNORE INTO ingredients (name, in_cabinet) VALUES (?, 1)",
            (ing_name,),
        )
        ing_row = conn.execute(
            "SELECT id FROM ingredients WHERE name = ?", (ing_name,)
        ).fetchone()
        conn.execute(
            "INSERT INTO drink_ingredients (drink_id, ingredient_id) VALUES (?, ?)",
            (drink_id, ing_row[0]),
        )

    conn.commit()
    return drink_id


# ---------------------------------------------------------------------------
# Property 6: Recipe type round-trip
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    name=_name_st,
    abv=st.integers(min_value=0, max_value=1000),
    recipe_type=st.sampled_from(["inline", "link"]),
)
def test_property_6_recipe_type_round_trip(name, abv, recipe_type):
    """Property 6: Recipe type round-trip.

    For any drink created with a given recipe_type ('inline' or 'link'),
    GET /drinks/:id should return a recipe_type field whose value matches
    the type used at creation.

    Validates: Requirements 3.4
    # Feature: drink-menu-recipe-book, Property 6: Recipe type round-trip
    """
    sqlite_conn = _make_sqlite_conn_with_recipes()

    instructions = "Shake well." if recipe_type == "inline" else None
    url = "https://example.com/recipe" if recipe_type == "link" else None

    drink_id = _seed_drink(
        sqlite_conn,
        name=name,
        abv=abv,
        recipe_type=recipe_type,
        instructions=instructions,
        url=url,
    )

    fake_conn = _FakeConnection(sqlite_conn)
    with patch.object(app_module, "get_connection", return_value=fake_conn):
        client = TestClient(app)
        response = client.get(f"/drinks/{drink_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["recipe_type"] == recipe_type, (
        f"Expected recipe_type={recipe_type!r} but got {data['recipe_type']!r} "
        f"for drink name={name!r}, abv={abv}"
    )

    sqlite_conn.close()


class TestGetDrinkById:
    """Unit tests for GET /drinks/{drink_id}."""

    def test_returns_drink_with_all_fields(self):
        """A found drink includes id, name, image_url, abv, recipe_type,
        ingredients, instructions, and url."""
        sqlite_conn = _make_sqlite_conn_with_recipes()
        drink_id = _seed_drink(
            sqlite_conn,
            name="Margarita",
            abv=150,
            recipe_type="inline",
            image_url="https://example.com/margarita.jpg",
            instructions="Combine ingredients.\nShake well.",
            url=None,
            ingredient_names=["Tequila", "Triple Sec", "Lime Juice"],
        )

        fake_conn = _FakeConnection(sqlite_conn)
        with patch.object(app_module, "get_connection", return_value=fake_conn):
            client = TestClient(app)
            response = client.get(f"/drinks/{drink_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == drink_id
        assert data["name"] == "Margarita"
        assert data["image_url"] == "https://example.com/margarita.jpg"
        assert data["abv"] == 150
        assert data["recipe_type"] == "inline"
        assert data["instructions"] == "Combine ingredients.\nShake well."
        assert data["url"] is None
        assert sorted(data["ingredients"]) == ["Lime Juice", "Tequila", "Triple Sec"]

        sqlite_conn.close()

    def test_returns_404_for_nonexistent_drink(self):
        """A request for a drink ID that does not exist returns 404 with error body."""
        sqlite_conn = _make_sqlite_conn_with_recipes()

        fake_conn = _FakeConnection(sqlite_conn)
        with patch.object(app_module, "get_connection", return_value=fake_conn):
            client = TestClient(app)
            response = client.get("/drinks/9999")

        assert response.status_code == 404
        assert response.json() == {"error": "Not found"}

        sqlite_conn.close()

    def test_link_type_drink_returns_url_and_null_instructions(self):
        """A link-type drink returns the url field and null instructions."""
        sqlite_conn = _make_sqlite_conn_with_recipes()
        drink_id = _seed_drink(
            sqlite_conn,
            name="Mojito",
            abv=80,
            recipe_type="link",
            instructions=None,
            url="https://example.com/mojito-recipe",
            ingredient_names=["Rum", "Mint"],
        )

        fake_conn = _FakeConnection(sqlite_conn)
        with patch.object(app_module, "get_connection", return_value=fake_conn):
            client = TestClient(app)
            response = client.get(f"/drinks/{drink_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["recipe_type"] == "link"
        assert data["url"] == "https://example.com/mojito-recipe"
        assert data["instructions"] is None

        sqlite_conn.close()

    def test_ingredients_list_is_present_and_ordered(self):
        """The ingredients field is a list of ingredient name strings."""
        sqlite_conn = _make_sqlite_conn_with_recipes()
        drink_id = _seed_drink(
            sqlite_conn,
            ingredient_names=["Vodka", "Orange Juice", "Grenadine"],
        )

        fake_conn = _FakeConnection(sqlite_conn)
        with patch.object(app_module, "get_connection", return_value=fake_conn):
            client = TestClient(app)
            response = client.get(f"/drinks/{drink_id}")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["ingredients"], list)
        assert sorted(data["ingredients"]) == sorted(["Vodka", "Orange Juice", "Grenadine"])

        sqlite_conn.close()

    def test_drink_with_no_image_url_returns_null(self):
        """A drink without an image URL returns null for image_url."""
        sqlite_conn = _make_sqlite_conn_with_recipes()
        drink_id = _seed_drink(sqlite_conn, image_url=None)

        fake_conn = _FakeConnection(sqlite_conn)
        with patch.object(app_module, "get_connection", return_value=fake_conn):
            client = TestClient(app)
            response = client.get(f"/drinks/{drink_id}")

        assert response.status_code == 200
        assert response.json()["image_url"] is None

        sqlite_conn.close()
