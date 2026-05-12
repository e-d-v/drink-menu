"""Drink Menu & Recipe Book — FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db import get_connection

app = FastAPI(title="Drink Menu & Recipe Book API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


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
