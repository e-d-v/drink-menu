"""Drink Menu & Recipe Book — FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
