"""Sync rows from a source MySQL table into a target MySQL table.

Usage:
    uv run --no-sync python sync_table.py
    uv run --no-sync python sync_table.py --config /path/to/other_config.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import re
import time
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pymysql

_MISSING = object()

# Fields that need fixed cleanup before writing to the target table.
# Change this name directly if your source/target field name changes.
GURL_FIELD = "Gurl"

# Source cleanup patterns for GURL_FIELD.
GURL_CLEAR_PATTERN = re.compile(r"^1\^.*\$$")
GURL_NEWLINE_PATTERN = re.compile(r"^#(\d{1,4})\^(\d{1,4})\$$")


def quote_ident(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def connect_mysql(config: object) -> pymysql.connections.Connection:
    if isinstance(config, dict):
        getter = config.get
    else:
        getter = lambda key, default=None: getattr(config, key, default)

    return pymysql.connect(
        host=getter("host"),
        port=getter("port"),
        user=getter("user"),
        password=getter("password"),
        database=getter("database"),
        charset=getter("charset", "utf8mb4"),
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def load_config(config_path: str) -> ModuleType:
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    spec = importlib.util.spec_from_file_location("db_sync_runtime_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config file: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_value(config: object, name: str, default: object = _MISSING) -> object:
    if hasattr(config, name):
        return getattr(config, name)
    if default is not _MISSING:
        return default
    raise AttributeError(f"Missing required config value: {name}")


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


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


def build_time_where_clause(config: object) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    time_filter_mode = get_value(config, "TIME_FILTER_MODE", None)
    time_start = get_value(config, "TIME_START", None)
    time_end = get_value(config, "TIME_END", None)
    source_create_time_field = get_value(config, "SOURCE_CREATE_TIME_FIELD", None)
    source_change_time_field = get_value(config, "SOURCE_CHANGE_TIME_FIELD", None)
    extra_where_sql = get_value(config, "EXTRA_WHERE_SQL", "")
    extra_where_params = tuple(get_value(config, "EXTRA_WHERE_PARAMS", ()))

    if time_filter_mode in (None, ""):
        pass
    elif time_filter_mode == "change_time":
        if source_change_time_field in (None, ""):
            raise ValueError("SOURCE_CHANGE_TIME_FIELD is required when TIME_FILTER_MODE = 'change_time'.")
        clause, clause_params = build_range_clause(source_change_time_field, time_start, time_end)
        clauses.append(clause)
        params.extend(clause_params)
    elif time_filter_mode == "create_or_change":
        if source_create_time_field in (None, "") or source_change_time_field in (None, ""):
            raise ValueError(
                "SOURCE_CREATE_TIME_FIELD and SOURCE_CHANGE_TIME_FIELD are required when "
                "TIME_FILTER_MODE = 'create_or_change'."
            )
        create_clause, create_params = build_range_clause(source_create_time_field, time_start, time_end)
        change_clause, change_params = build_range_clause(source_change_time_field, time_start, time_end)
        clauses.append(f"({create_clause} OR {change_clause})")
        params.extend(create_params)
        params.extend(change_params)
    else:
        raise ValueError(
            f"Unsupported TIME_FILTER_MODE: {time_filter_mode!r}. "
            "Use 'change_time' or 'create_or_change'."
        )

    if extra_where_sql:
        clauses.append(f"({extra_where_sql})")
        params.extend(extra_where_params)

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


def get_sync_column_mapping(config: object) -> list[tuple[str, str]]:
    column_mapping = list(get_value(config, "COLUMN_MAPPING"))
    area_source_field = get_value(config, "AREA_SOURCE_FIELD", None)
    area_target_field = get_value(config, "AREA_TARGET_FIELD", None)
    duration_source_field = get_value(config, "DURATION_SOURCE_FIELD", None)
    duration_target_field = get_value(config, "DURATION_TARGET_FIELD", None)

    if area_source_field and area_target_field:
        column_mapping = unique_mappings(column_mapping, [(area_source_field, area_target_field)])
    if duration_source_field and duration_target_field:
        column_mapping = unique_mappings(column_mapping, [(duration_source_field, duration_target_field)])

    return column_mapping


def get_match_source_fields(config: object) -> list[str]:
    match_column_mapping = list(get_value(config, "MATCH_COLUMN_MAPPING"))
    return [source_column for source_column, _ in match_column_mapping]


def get_area_cid_mapping(config: object) -> dict[str, object]:
    return dict(get_value(config, "AREA_CID_MAPPING", {}))


def get_area_cid_default(config: object) -> object:
    return get_value(config, "AREA_CID_DEFAULT", 10)


def clean_duration_value(value: object) -> int:
    if value in (None, "", 0, "0"):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text in ("", "0"):
            return 0
        match = re.search(r"(\d+)", text)
        if match:
            return int(match.group(1))
    return 0


def build_source_select_sql(config: object) -> tuple[str, list[object], list[str]]:
    sync_mapping = get_sync_column_mapping(config)
    select_columns: list[str] = []
    alias_order: list[str] = []
    source_compare_time_field = get_value(config, "SOURCE_COMPARE_TIME_FIELD")
    match_source_fields = get_match_source_fields(config)

    for source_column, target_column in sync_mapping:
        alias_order.append(target_column)
        if source_column == target_column:
            select_columns.append(quote_ident(source_column))
        else:
            select_columns.append(f"{quote_ident(source_column)} AS {quote_ident(target_column)}")

    for source_column in match_source_fields:
        append_unique(select_columns, quote_ident(source_column))
    append_unique(alias_order, source_compare_time_field)
    append_unique(select_columns, quote_ident(source_compare_time_field))

    where_sql, params = build_time_where_clause(config)
    source_table = get_value(config, "SOURCE_TABLE")
    source_create_time_field = get_value(config, "SOURCE_CREATE_TIME_FIELD")
    sql = (
        f"SELECT {', '.join(select_columns)} "
        f"FROM {quote_ident(source_table)}"
        f"{where_sql}"
        f" ORDER BY {quote_ident(source_compare_time_field)} ASC, {quote_ident(source_create_time_field)} ASC"
    )
    return sql, params, alias_order


def build_target_lookup_sql(config: object) -> tuple[str, list[str]]:
    match_column_mapping = list(get_value(config, "MATCH_COLUMN_MAPPING"))
    if not match_column_mapping:
        raise ValueError("MATCH_COLUMN_MAPPING cannot be empty.")

    target_table = get_value(config, "TARGET_TABLE")
    target_compare_time_field = get_value(config, "TARGET_COMPARE_TIME_FIELD")
    lookup_columns = [target_column for _, target_column in match_column_mapping]
    where_sql = " AND ".join(f"{quote_ident(column)} = %s" for column in lookup_columns)
    sql = (
        f"SELECT {quote_ident(target_compare_time_field)} "
        f"FROM {quote_ident(target_table)} "
        f"WHERE {where_sql} "
        "LIMIT 1"
    )
    return sql, lookup_columns


def build_insert_sql(config: object) -> tuple[str, list[str]]:
    target_table = get_value(config, "TARGET_TABLE")
    use_upsert = bool(get_value(config, "USE_UPSERT"))
    upsert_update_columns = list(get_value(config, "UPSERT_UPDATE_COLUMNS", []))
    target_create_time_field = get_value(config, "TARGET_CREATE_TIME_FIELD")
    target_compare_time_field = get_value(config, "TARGET_COMPARE_TIME_FIELD")
    area_target_field = get_value(config, "AREA_TARGET_FIELD", None)
    duration_target_field = get_value(config, "DURATION_TARGET_FIELD", None)
    cid_target_field = get_value(config, "CID_TARGET_FIELD", "cid")
    target_columns = [target_column for _, target_column in get_sync_column_mapping(config)]
    append_unique(target_columns, cid_target_field)
    if area_target_field:
        append_unique(target_columns, area_target_field)
    if duration_target_field:
        append_unique(target_columns, duration_target_field)
    append_unique(target_columns, target_create_time_field)
    append_unique(target_columns, target_compare_time_field)
    placeholders = ", ".join(["%s"] * len(target_columns))
    columns_sql = ", ".join(quote_ident(column) for column in target_columns)

    if not use_upsert:
        sql = f"INSERT INTO {quote_ident(target_table)} ({columns_sql}) VALUES ({placeholders})"
        return sql, target_columns

    update_columns = [
        column for column in (upsert_update_columns or target_columns) if column != target_create_time_field
    ]
    append_unique(update_columns, target_compare_time_field)
    update_sql = ", ".join(
        f"{quote_ident(column)} = VALUES({quote_ident(column)})" for column in update_columns
    )
    sql = (
        f"INSERT INTO {quote_ident(target_table)} ({columns_sql}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_sql}"
    )
    return sql, target_columns


def build_update_sql(config: object) -> tuple[str, list[str], list[str]]:
    target_table = get_value(config, "TARGET_TABLE")
    upsert_update_columns = list(get_value(config, "UPSERT_UPDATE_COLUMNS", []))
    target_compare_time_field = get_value(config, "TARGET_COMPARE_TIME_FIELD")
    area_target_field = get_value(config, "AREA_TARGET_FIELD", None)
    duration_target_field = get_value(config, "DURATION_TARGET_FIELD", None)
    cid_target_field = get_value(config, "CID_TARGET_FIELD", "cid")
    target_columns = [target_column for _, target_column in get_sync_column_mapping(config)]
    update_columns = upsert_update_columns or target_columns
    append_unique(update_columns, cid_target_field)
    if area_target_field:
        append_unique(update_columns, area_target_field)
    if duration_target_field:
        append_unique(update_columns, duration_target_field)
    append_unique(update_columns, target_compare_time_field)
    set_sql = ", ".join(f"{quote_ident(column)} = %s" for column in update_columns)
    key_columns = [target_column for _, target_column in get_value(config, "MATCH_COLUMN_MAPPING")]
    where_sql = " AND ".join(f"{quote_ident(column)} = %s" for column in key_columns)
    sql = f"UPDATE {quote_ident(target_table)} SET {set_sql} WHERE {where_sql}"
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
        if text.isdigit():
            return int(text)
        try:
            return dt.datetime.fromisoformat(text)
        except ValueError:
            return value
    return value


def clean_gurl_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    if GURL_CLEAR_PATTERN.fullmatch(value):
        return ""
    if GURL_NEWLINE_PATTERN.fullmatch(value):
        return "\n"
    return value


def clean_source_row(source_row: dict[str, object]) -> dict[str, object]:
    cleaned_row = dict(source_row)
    if GURL_FIELD in cleaned_row:
        cleaned_row[GURL_FIELD] = clean_gurl_value(cleaned_row[GURL_FIELD])
    return cleaned_row


def clean_area_value(value: object) -> object:
    if not isinstance(value, str):
        return value

    text = value.strip().strip('"').strip("'")
    if not text:
        return text

    if "," in text:
        text = text.split(",", 1)[0]

    return text.strip().strip('"').strip("'")


def build_write_row(config: object, source_row: dict[str, object]) -> dict[str, object]:
    cleaned_row = clean_source_row(source_row)
    write_row = dict(cleaned_row)

    area_source_field = get_value(config, "AREA_SOURCE_FIELD", None)
    area_target_field = get_value(config, "AREA_TARGET_FIELD", None)
    duration_source_field = get_value(config, "DURATION_SOURCE_FIELD", None)
    duration_target_field = get_value(config, "DURATION_TARGET_FIELD", None)
    cid_target_field = get_value(config, "CID_TARGET_FIELD", "cid")
    area_cid_mapping = get_area_cid_mapping(config)
    area_cid_default = get_area_cid_default(config)
    source_compare_time_field = get_value(config, "SOURCE_COMPARE_TIME_FIELD")
    target_create_time_field = get_value(config, "TARGET_CREATE_TIME_FIELD")
    target_compare_time_field = get_value(config, "TARGET_COMPARE_TIME_FIELD")

    if area_source_field and area_target_field:
        area_value = clean_area_value(cleaned_row.get(area_source_field))
        write_row[area_target_field] = area_value
        write_row[cid_target_field] = area_cid_mapping.get(area_value, area_cid_default)

    if duration_source_field and duration_target_field:
        write_row[duration_target_field] = clean_duration_value(cleaned_row.get(duration_source_field))

    generated_time = normalize_timestamp(cleaned_row[source_compare_time_field])
    write_row[target_create_time_field] = generated_time
    write_row[target_compare_time_field] = generated_time

    return write_row


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


def run_debug(config: object) -> None:
    source_sql, source_params, alias_order = build_source_select_sql(config)
    lookup_sql, lookup_columns = build_target_lookup_sql(config)
    insert_sql, insert_columns = build_insert_sql(config)
    update_sql, update_columns, update_keys = build_update_sql(config)

    print("DEBUG=True, no SQL will be executed.")
    print(f"[CONFIG] batch_size={get_value(config, 'BATCH_SIZE')}, sleep_seconds={get_value(config, 'SLEEP_SECONDS')}")
    print(f"[CONFIG] sync_columns={alias_order}")
    print(f"[CONFIG] match_columns={lookup_columns}")
    print(
        f"[CONFIG] compare_field={get_value(config, 'SOURCE_COMPARE_TIME_FIELD')} -> "
        f"{get_value(config, 'TARGET_COMPARE_TIME_FIELD')}"
    )
    print_sql("SOURCE SELECT", source_sql, source_params)
    print_sql("TARGET LOOKUP", lookup_sql, [])
    print_sql("INSERT/UPSERT", insert_sql, [])
    print_sql("UPDATE", update_sql, [])
    print(f"[CONFIG] insert_columns={insert_columns}")
    print(f"[CONFIG] update_columns={update_columns}")
    print(f"[CONFIG] update_keys={update_keys}")


def row_values(row: dict[str, object], columns: list[str]) -> tuple[object, ...]:
    return tuple(row[column] for column in columns)


def print_progress(processed: int, inserted: int, updated: int, skipped: int) -> None:
    print(
        f"processed={processed} inserted={inserted} "
        f"updated={updated} skipped={skipped}"
    )


def process_row(
    config: object,
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
    cleaned_row = clean_source_row(source_row)
    match_mapping = list(get_value(config, "MATCH_COLUMN_MAPPING"))
    match_source_by_target = {target_column: source_column for source_column, target_column in match_mapping}
    lookup_params = tuple(cleaned_row[match_source_by_target[column]] for column in lookup_columns)
    target_cursor.execute(lookup_sql, lookup_params)
    target_row = target_cursor.fetchone()

    source_compare_time_field = get_value(config, "SOURCE_COMPARE_TIME_FIELD")
    target_compare_time_field = get_value(config, "TARGET_COMPARE_TIME_FIELD")
    source_time = cleaned_row[source_compare_time_field]
    target_time = target_row[target_compare_time_field] if target_row else None
    if not should_sync(source_time, target_time):
        return "skip"

    use_upsert = bool(get_value(config, "USE_UPSERT"))
    write_row = build_write_row(config, cleaned_row)
    insert_params = tuple(write_row[column] for column in insert_columns)

    if target_row is None:
        target_cursor.execute(insert_sql, insert_params)
        return "insert"

    if use_upsert:
        target_cursor.execute(insert_sql, insert_params)
        return "upsert"

    update_params = tuple(write_row[column] for column in update_columns) + tuple(
        cleaned_row[match_source_by_target[column]] for column in update_keys
    )
    target_cursor.execute(update_sql, update_params)
    return "update"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync MySQL rows from source to target.")
    parser.add_argument(
        "--config",
        default="db_config.py",
        help="Path to the config file. Default: db_config.py",
    )
    args = parser.parse_args()
    config = load_config(args.config)

    if bool(get_value(config, "DEBUG")):
        run_debug(config)
        return

    source_sql, source_params, _ = build_source_select_sql(config)
    lookup_sql, lookup_columns = build_target_lookup_sql(config)
    insert_sql, insert_columns = build_insert_sql(config)
    update_sql, update_columns, update_keys = build_update_sql(config)

    source_conn = connect_mysql(get_value(config, "SOURCE_DB"))
    target_conn = connect_mysql(get_value(config, "TARGET_DB"))

    try:
        with closing(source_conn.cursor()) as source_cursor, closing(target_conn.cursor()) as target_cursor:
            print_sql("SOURCE SELECT", source_sql, source_params)
            source_cursor.execute(source_sql, tuple(source_params))

            batch_size = int(get_value(config, "BATCH_SIZE"))
            sleep_seconds = float(get_value(config, "SLEEP_SECONDS"))
            total_rows = 0
            total_inserted = 0
            total_updated = 0
            total_skipped = 0

            while True:
                batch = source_cursor.fetchmany(batch_size)
                if not batch:
                    break

                for source_row in batch:
                    action = process_row(
                        config=config,
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
                    total_rows += 1
                    print_progress(total_rows, total_inserted, total_updated, total_skipped)

                target_conn.commit()

                if sleep_seconds > 0 and len(batch) == batch_size:
                    time.sleep(sleep_seconds)

    except Exception:
        target_conn.rollback()
        raise
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    main()
