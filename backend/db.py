"""Database connection module with connection pooling."""

import os
import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool

_pool: MySQLConnectionPool | None = None


def _get_pool() -> MySQLConnectionPool:
    global _pool
    if _pool is None:
        _pool = MySQLConnectionPool(
            pool_name="drink_menu_pool",
            pool_size=5,
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_USER", "root"),
            password=os.environ.get("DB_PASSWORD", "mypass"),
            database=os.environ.get("DB_NAME", "drink_menu"),
            autocommit=False,
        )
    return _pool


def get_connection():
    """Return a connection from the pool. Caller is responsible for closing it."""
    return _get_pool().get_connection()
