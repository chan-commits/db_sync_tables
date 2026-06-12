"""Sync rows from a source MySQL table into a target MySQL table.

Usage:
    uv run python sync_table.py
"""

from __future__ import annotations

import datetime as dt
import time
from contextlib import closing

import pymysql

from db_config import (
    BATCH_SIZE,
    COLUMN_MAPPING,
    DEBUG,
    EXTRA_WHERE_PARAMS,
    EXTRA_WHERE_SQL,
    MATCH_COLUMN_MAPPING,
    SOURCE_CHANGE_TIME_FIELD,
    SOURCE_COMPARE_TIME_FIELD,
    SOURCE_CREATE_TIME_FIELD,
    SOURCE_DB,
    SOURCE_TABLE,
    SLEEP_SECONDS,
    TARGET_CHANGE_TIME_FIELD,
    TARGET_COMPARE_TIME_FIELD,
    TARGET_CREATE_TIME_FIELD,
    TARGET_DB,
    TARGET_TABLE,
    TIME_END,
    TIME_FILTER_MODE,
    TIME_START,
    UPSERT_UPDATE_COLUMNS,
    USE_UPSERT,
)


def quote_ident(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def connect_mysql(config: dict[str, object]) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        charset=config.get("charset", "utf8mb4"),
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def build_range_clause(field: str, start: object, end: object) -> tuple[str, list[object]]:
    parts: list[str] = []
    params: list[object] = []

    if start is not None:
        parts.append(f"{quote_ident(field)} >= %s")
        params.append(start)
    if end is not None:
        parts.append(f"{quote_ident(field)} < %s")
        params.append(end)

    if not parts:
        return "1=1", []

    return " AND ".join(parts), params


def build_time_where_clause() -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    if TIME_FILTER_MODE == "change_time":
        clause, clause_params = build_range_clause(SOURCE_CHANGE_TIME_FIELD, TIME_START, TIME_END)
        clauses.append(clause)
        params.extend(clause_params)
    elif TIME_FILTER_MODE == "create_or_change":
        create_clause, create_params = build_range_clause(SOURCE_CREATE_TIME_FIELD, TIME_START, TIME_END)
        change_clause, change_params = build_range_clause(SOURCE_CHANGE_TIME_FIELD, TIME_START, TIME_END)
        clauses.append(f"({create_clause} OR {change_clause})")
        params.extend(create_params)
        params.extend(change_params)
    else:
        raise ValueError(
            f"Unsupported TIME_FILTER_MODE: {TIME_FILTER_MODE!r}. "
            "Use 'change_time' or 'create_or_change'."
        )

    if EXTRA_WHERE_SQL:
        clauses.append(f"({EXTRA_WHERE_SQL})")
        params.extend(EXTRA_WHERE_PARAMS)

    if not clauses:
        return "", []

    return " WHERE " + " AND ".join(clauses), params


def unique_mappings(*mapping_groups: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    seen_sources: dict[str, str] = {}

    for group in mapping_groups:
        for source_column, target_column in group:
            existing_target = seen_sources.get(source_column)
            if existing_target is None:
                seen_sources[source_column] = target_column
                merged.append((source_column, target_column))
                continue

            if existing_target != target_column:
                raise ValueError(
                    "Conflicting mapping for source column "
                    f"{source_column!r}: {existing_target!r} vs {target_column!r}"
                )

    return merged


def get_sync_column_mapping() -> list[tuple[str, str]]:
    auto_mappings = [
        list(MATCH_COLUMN_MAPPING),
        [
            (SOURCE_CREATE_TIME_FIELD, TARGET_CREATE_TIME_FIELD),
            (SOURCE_CHANGE_TIME_FIELD, TARGET_CHANGE_TIME_FIELD),
            (SOURCE_COMPARE_TIME_FIELD, TARGET_COMPARE_TIME_FIELD),
        ],
    ]
    return unique_mappings(list(COLUMN_MAPPING), *auto_mappings)


def build_source_select_sql() -> tuple[str, list[object], list[str]]:
    sync_mapping = get_sync_column_mapping()
    select_columns: list[str] = []
    alias_order: list[str] = []

    for source_column, target_column in sync_mapping:
        alias_order.append(target_column)
        if source_column == target_column:
            select_columns.append(quote_ident(source_column))
        else:
            select_columns.append(f"{quote_ident(source_column)} AS {quote_ident(target_column)}")

    where_sql, params = build_time_where_clause()
    sql = (
        f"SELECT {', '.join(select_columns)} "
        f"FROM {quote_ident(SOURCE_TABLE)}"
        f"{where_sql}"
        f" ORDER BY {quote_ident(SOURCE_COMPARE_TIME_FIELD)} ASC, {quote_ident(SOURCE_CREATE_TIME_FIELD)} ASC"
    )
    return sql, params, alias_order


def build_target_lookup_sql() -> tuple[str, list[str]]:
    if not MATCH_COLUMN_MAPPING:
        raise ValueError("MATCH_COLUMN_MAPPING cannot be empty.")

    lookup_columns = [target_column for _, target_column in MATCH_COLUMN_MAPPING]
    where_sql = " AND ".join(f"{quote_ident(column)} = %s" for column in lookup_columns)
    sql = (
        f"SELECT {quote_ident(TARGET_COMPARE_TIME_FIELD)} "
        f"FROM {quote_ident(TARGET_TABLE)} "
        f"WHERE {where_sql} "
        "LIMIT 1"
    )
    return sql, lookup_columns


def build_insert_sql() -> tuple[str, list[str]]:
    target_columns = [target_column for _, target_column in get_sync_column_mapping()]
    placeholders = ", ".join(["%s"] * len(target_columns))
    columns_sql = ", ".join(quote_ident(column) for column in target_columns)

    if not USE_UPSERT:
        sql = f"INSERT INTO {quote_ident(TARGET_TABLE)} ({columns_sql}) VALUES ({placeholders})"
        return sql, target_columns

    update_columns = UPSERT_UPDATE_COLUMNS or target_columns
    update_sql = ", ".join(
        f"{quote_ident(column)} = VALUES({quote_ident(column)})" for column in update_columns
    )
    sql = (
        f"INSERT INTO {quote_ident(TARGET_TABLE)} ({columns_sql}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_sql}"
    )
    return sql, target_columns


def build_update_sql() -> tuple[str, list[str], list[str]]:
    target_columns = [target_column for _, target_column in get_sync_column_mapping()]
    update_columns = UPSERT_UPDATE_COLUMNS or target_columns
    set_sql = ", ".join(f"{quote_ident(column)} = %s" for column in update_columns)
    key_columns = [target_column for _, target_column in MATCH_COLUMN_MAPPING]
    where_sql = " AND ".join(f"{quote_ident(column)} = %s" for column in key_columns)
    sql = f"UPDATE {quote_ident(TARGET_TABLE)} SET {set_sql} WHERE {where_sql}"
    return sql, update_columns, key_columns


def normalize_timestamp(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (dt.datetime, dt.date, int, float)):
        if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
            return dt.datetime(value.year, value.month, value.day)
        return value
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        for parser in (dt.datetime.fromisoformat,):
            try:
                return parser(text)
            except ValueError:
                continue
    return value


def should_sync(source_time: object, target_time: object) -> bool:
    if source_time is None:
        return True
    if target_time is None:
        return True

    source_value = normalize_timestamp(source_time)
    target_value = normalize_timestamp(target_time)

    try:
        return target_value < source_value
    except TypeError as exc:
        raise TypeError(
            "Cannot compare source and target timestamp values. "
            f"source={source_time!r}, target={target_time!r}"
        ) from exc


def print_sql(label: str, sql: str, params: list[object] | tuple[object, ...] | None = None) -> None:
    if params is None:
        print(f"[SQL] {label}: {sql}")
    else:
        print(f"[SQL] {label}: {sql}")
        print(f"[SQL] {label} params: {tuple(params)!r}")


def run_debug() -> None:
    source_sql, source_params, alias_order = build_source_select_sql()
    lookup_sql, lookup_columns = build_target_lookup_sql()
    insert_sql, insert_columns = build_insert_sql()
    update_sql, update_columns, update_keys = build_update_sql()

    print("DEBUG=True, no SQL will be executed.")
    print(f"[CONFIG] batch_size={BATCH_SIZE}, sleep_seconds={SLEEP_SECONDS}")
    print(f"[CONFIG] sync_columns={alias_order}")
    print(f"[CONFIG] match_columns={lookup_columns}")
    print(f"[CONFIG] compare_field={SOURCE_COMPARE_TIME_FIELD} -> {TARGET_COMPARE_TIME_FIELD}")
    print_sql("SOURCE SELECT", source_sql, source_params)
    print_sql("TARGET LOOKUP", lookup_sql, [])
    print_sql("INSERT/UPSERT", insert_sql, [])
    print_sql("UPDATE", update_sql, [])
    print(f"[CONFIG] insert_columns={insert_columns}")
    print(f"[CONFIG] update_columns={update_columns}")
    print(f"[CONFIG] update_keys={update_keys}")


def row_values(row: dict[str, object], columns: list[str]) -> tuple[object, ...]:
    return tuple(row[column] for column in columns)


def process_row(
    source_row: dict[str, object],
    target_cursor: pymysql.cursors.DictCursor,
    insert_sql: str,
    insert_columns: list[str],
    update_sql: str,
    update_columns: list[str],
    update_keys: list[str],
    lookup_sql: str,
    lookup_columns: list[str],
) -> str:
    lookup_params = row_values(source_row, lookup_columns)
    target_cursor.execute(lookup_sql, lookup_params)
    target_row = target_cursor.fetchone()

    source_time = source_row[TARGET_COMPARE_TIME_FIELD]
    target_time = target_row[TARGET_COMPARE_TIME_FIELD] if target_row else None
    if not should_sync(source_time, target_time):
        return "skip"

    insert_params = row_values(source_row, insert_columns)

    if target_row is None:
        target_cursor.execute(insert_sql, insert_params)
        return "insert"

    if USE_UPSERT:
        target_cursor.execute(insert_sql, insert_params)
        return "upsert"

    update_params = row_values(source_row, update_columns) + row_values(source_row, update_keys)
    target_cursor.execute(update_sql, update_params)
    return "update"


def main() -> None:
    if DEBUG:
        run_debug()
        return

    source_sql, source_params, _ = build_source_select_sql()
    lookup_sql, lookup_columns = build_target_lookup_sql()
    insert_sql, insert_columns = build_insert_sql()
    update_sql, update_columns, update_keys = build_update_sql()

    source_conn = connect_mysql(SOURCE_DB)
    target_conn = connect_mysql(TARGET_DB)

    try:
        with closing(source_conn.cursor()) as source_cursor, closing(target_conn.cursor()) as target_cursor:
            print_sql("SOURCE SELECT", source_sql, source_params)
            source_cursor.execute(source_sql, tuple(source_params))

            total_rows = 0
            total_inserted = 0
            total_updated = 0
            total_skipped = 0

            while True:
                batch = source_cursor.fetchmany(BATCH_SIZE)
                if not batch:
                    break

                for source_row in batch:
                    action = process_row(
                        source_row=source_row,
                        target_cursor=target_cursor,
                        insert_sql=insert_sql,
                        insert_columns=insert_columns,
                        update_sql=update_sql,
                        update_columns=update_columns,
                        update_keys=update_keys,
                        lookup_sql=lookup_sql,
                        lookup_columns=lookup_columns,
                    )
                    if action == "insert":
                        total_inserted += 1
                    elif action == "upsert":
                        total_updated += 1
                    elif action == "update":
                        total_updated += 1
                    else:
                        total_skipped += 1

                target_conn.commit()
                total_rows += len(batch)
                print(
                    "processed="
                    f"{total_rows} inserted={total_inserted} updated={total_updated} skipped={total_skipped}"
                )

                if SLEEP_SECONDS > 0 and len(batch) == BATCH_SIZE:
                    time.sleep(SLEEP_SECONDS)

    except Exception:
        target_conn.rollback()
        raise
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    main()
