import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://max_rass:max_rass@app-postgres:5432/max_rass")
SCHEMA_FILE = Path(__file__).parent / "sql" / "001_app_schema.sql"
SAFE_QUERY_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE | re.DOTALL)
UNSAFE_QUERY_RE = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call)\b", re.IGNORECASE)

pool: asyncpg.Pool | None = None


def serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def serialize_record(record: asyncpg.Record) -> dict[str, Any]:
    return {key: serialize_value(value) for key, value in dict(record).items()}


async def connect_database() -> None:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)


async def close_database() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool is not initialized")
    return pool


async def apply_schema() -> None:
    sql_dir = SCHEMA_FILE.parent
    files = sorted(sql_dir.glob("*.sql"))
    async with get_pool().acquire() as conn:
        for path in files:
            await conn.execute(path.read_text(encoding="utf-8"))


async def database_health() -> dict[str, str]:
    async with get_pool().acquire() as conn:
        value = await conn.fetchval("SELECT 'ok'::text")
    return {"status": str(value)}


async def list_tables() -> list[dict[str, Any]]:
    sql = """
        SELECT
            t.table_name,
            COALESCE(s.n_live_tup, 0)::bigint AS estimated_rows
        FROM information_schema.tables t
        LEFT JOIN pg_stat_user_tables s
            ON s.schemaname = t.table_schema
            AND s.relname = t.table_name
        WHERE t.table_schema = 'app'
            AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name;
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql)
    return [serialize_record(row) for row in rows]


async def get_schema_summary() -> dict[str, Any]:
    columns_sql = """
        SELECT
            c.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default
        FROM information_schema.columns c
        WHERE c.table_schema = 'app'
        ORDER BY c.table_name, c.ordinal_position;
    """
    relations_sql = """
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = 'app'
        ORDER BY tc.table_name, kcu.column_name;
    """
    async with get_pool().acquire() as conn:
        columns = await conn.fetch(columns_sql)
        relations = await conn.fetch(relations_sql)
    return {
        "columns": [serialize_record(row) for row in columns],
        "relations": [serialize_record(row) for row in relations],
    }


def normalize_readonly_query(sql: str) -> str:
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("SQL-запрос пустой")
    if ";" in stripped:
        raise ValueError("Разрешён только один SELECT/WITH-запрос без дополнительных команд")
    if not SAFE_QUERY_RE.match(stripped):
        raise ValueError("Разрешены только SELECT или WITH-запросы")
    if UNSAFE_QUERY_RE.search(stripped):
        raise ValueError("Запрос содержит запрещённые команды")
    return stripped


async def run_readonly_query(sql: str, limit: int) -> dict[str, Any]:
    normalized = normalize_readonly_query(sql)
    safe_limit = max(1, min(limit, 200))
    wrapped_sql = f"SELECT * FROM ({normalized}) AS q LIMIT {safe_limit}"

    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction(readonly=True):
                await conn.execute("SET LOCAL statement_timeout = '5s'")
                statement = await conn.prepare(wrapped_sql)
                records = await statement.fetch()
                columns = [attribute.name for attribute in statement.get_attributes()]
    except asyncpg.PostgresError as error:
        raise ValueError(f"Ошибка SQL: {error}") from error

    return {
        "columns": columns,
        "rows": [serialize_record(row) for row in records],
        "row_count": len(records),
        "limit": safe_limit,
    }


async def seed_demo_data() -> dict[str, Any]:
    from demo_seed import seed_demo_data as _seed

    return await _seed(get_pool())


async def seed_formation_test_data() -> dict[str, Any]:
    from formation_test_seed import seed_formation_test_data as _seed

    return await _seed(get_pool())
