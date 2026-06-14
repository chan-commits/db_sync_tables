# db_sync_tables

Language:
- [简体中文](README.zh-CN.md)

MySQL table sync tool using `uv` and `pymysql`.

## Quick Start

1. Edit `db_config.py`.
2. If `pymysql` is already installed in the uv environment, run:

```bash
uv run --no-sync python sync_table.py
```

Or run a different config file directly:

```bash
uv run --no-sync python sync_table.py --config /path/to/your_config.py
```

3. If you want uv to create or refresh the environment from `pyproject.toml`,
   run `uv sync` first, then run the script.
4. Set `DEBUG = True` to print SQL templates only.
5. Set `DEBUG = False` to run the real sync.

## Config Guide

Use `db_config.py` for runtime settings. The key fields are shown below.

```python
DEBUG = True

SOURCE_DB = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "source_user",
    "password": "source_password",
    "database": "source_database",
    "charset": "utf8mb4",
}

TARGET_DB = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "target_user",
    "password": "target_password",
    "database": "target_database",
    "charset": "utf8mb4",
}

SOURCE_TABLE = "source_table"
TARGET_TABLE = "target_table"

COLUMN_MAPPING = [
    ("id", "id"),
]

MATCH_COLUMN_MAPPING = [
    ("id", "id"),
]

SOURCE_COMPARE_TIME_FIELD = "change_time"
TARGET_COMPARE_TIME_FIELD = "change_time"

SOURCE_CREATE_TIME_FIELD = "create_time"
TARGET_CREATE_TIME_FIELD = "create_time"
SOURCE_CHANGE_TIME_FIELD = "change_time"
TARGET_CHANGE_TIME_FIELD = "change_time"

TIME_FILTER_MODE = "change_time"
TIME_START = "2026-01-01 00:00:00"
TIME_END = "2026-02-01 00:00:00"

EXTRA_WHERE_SQL = ""
EXTRA_WHERE_PARAMS = ()

USE_UPSERT = True
UPSERT_UPDATE_COLUMNS = []
BATCH_SIZE = 5
SLEEP_SECONDS = 5
```

Field notes:

- `DEBUG = True` prints SQL and skips execution.
- `SOURCE_DB` should have read-only permission.
- `TARGET_DB` should have read/write permission.
- `COLUMN_MAPPING` defines which columns are copied from source to target.
- `MATCH_COLUMN_MAPPING` defines how a source row matches a target row.
  If the column names are the same on both sides, write them the same way,
  for example `("id", "id")`.
  The source columns in `MATCH_COLUMN_MAPPING` are automatically selected from
  the source table, so they do not need to be repeated in `COLUMN_MAPPING`.
- `AREA_SOURCE_FIELD` / `AREA_TARGET_FIELD` define the source-to-target area
  mapping, and `AREA_CID_MAPPING` defines the derived cid lookup.
- If a cleaned area is not found in `AREA_CID_MAPPING`, `cid` falls back to
  `AREA_CID_DEFAULT` and defaults to `10`.
- Sync decision:
  - if the target row does not exist, insert it
  - if the target row exists and the target timestamp is older than the
    source timestamp, update it
  - if the target timestamp is greater than or equal to the source timestamp,
    skip it
- `SOURCE_COMPARE_TIME_FIELD` and `TARGET_COMPARE_TIME_FIELD` are the fields
  used for the insert/update/skip comparison.
- `ctime` and `mtime` are auto-added to the target write SQL. On insert, both
  are set to the source compare value so they stay equal; on update, only
  `mtime` is refreshed.
- `SOURCE_CREATE_TIME_FIELD` / `TARGET_CREATE_TIME_FIELD` and
  `SOURCE_CHANGE_TIME_FIELD` / `TARGET_CHANGE_TIME_FIELD` are the field names
  used by the source filter and auto-mapping logic. They can be different from
  the actual column names in your tables.
- `Gurl` is a fixed cleanup field in `sync_table.py`:
  - any string that starts with `1^...$` becomes empty string
  - `#2^2$`, `#19^19$`, `#28^28$`, etc. become `\n`
- `area` is appended automatically from `AREA_SOURCE_FIELD` /
  `AREA_TARGET_FIELD` in `db_config.py`.
- `area` is cleaned before writing:
  - `中国,澳大利亚` becomes `中国`
  - empty or missing values become an empty string, not `NULL`
  - the cleaned `area` is then used to resolve `cid`
  - if the cleaned `area` is empty, that row is skipped
- `cid` is derived from `AREA_CID_MAPPING` and does not need to be listed in
  `MATCH_COLUMN_MAPPING`.
- `v_duration` is appended automatically from `DURATION_SOURCE_FIELD` /
  `DURATION_TARGET_FIELD` in `db_config.py`.
- `v_duration` is cleaned before writing:
  - `52分钟` becomes `52`
  - empty values or `0` become `0`
- `long` does not need to be listed in `MATCH_COLUMN_MAPPING`.
- Why there are multiple time fields:
  - `create_time` is usually the original creation timestamp
  - `change_time` is usually the last modified timestamp
  - `TIME_FILTER_MODE` decides which source timestamp is used to fetch rows
- `TIME_FILTER_MODE`, `TIME_START`, and `TIME_END` are optional.
- If you do not need a built-in time window, leave all three as `None` and use
  `EXTRA_WHERE_SQL` / `EXTRA_WHERE_PARAMS` instead.
- If `TIME_FILTER_MODE = "change_time"`, the source query filters by the
  source change time field.
- If `TIME_FILTER_MODE = "create_or_change"`, the source query filters by the
  source create time field or source change time field.
- `EXTRA_WHERE_SQL` and `EXTRA_WHERE_PARAMS` add extra source-side filters.
- `USE_UPSERT = True` uses `INSERT ... ON DUPLICATE KEY UPDATE` when a row
  needs to be written.
- `UPSERT_UPDATE_COLUMNS` limits which columns are refreshed during upsert.
- `BATCH_SIZE` defaults to `5`.
- `SLEEP_SECONDS` defaults to `5`.
- Each processed row prints a decision log such as:
  - `processed=1 inserted=0 updated=0 skipped=1`
  - `[ROW] action=skip reason=target_time_newer_or_equal ...`
- SQL logs print both the parameterized template and the rendered SQL with
  parameters already substituted, so you can run the rendered statement
  directly against the source or target database.
- If you want to rely only on your own `EXTRA_WHERE_SQL`, set `TIME_FILTER_MODE`,
  `TIME_START`, and `TIME_END` to `None`.

## Real-World Example

Scenario:

- Source DB: `crm_readonly`
- Target DB: `crm_rw`
- Source table: `customer_profile`
- Target table: `customer_profile_sync`
- Same row is identified by `customer_id`
- Business fields include `name`, `phone`, and `status`
- Source has `created_at` and `updated_at`
- Target has the same fields
- Only rows updated in January 2026 should be synced

Example config:

```python
DEBUG = True

SOURCE_DB = {
    "host": "10.0.0.21",
    "port": 3306,
    "user": "crm_ro",
    "password": "ro_password",
    "database": "crm_readonly",
    "charset": "utf8mb4",
}

TARGET_DB = {
    "host": "10.0.0.22",
    "port": 3306,
    "user": "crm_rw",
    "password": "rw_password",
    "database": "crm_rw",
    "charset": "utf8mb4",
}

SOURCE_TABLE = "customer_profile"
TARGET_TABLE = "customer_profile_sync"

COLUMN_MAPPING = [
    ("customer_id", "customer_id"),
    ("name", "name"),
    ("phone", "phone"),
    ("status", "status"),
    ("created_at", "created_at"),
    ("updated_at", "updated_at"),
]

MATCH_COLUMN_MAPPING = [
    ("customer_id", "customer_id"),
]

SOURCE_COMPARE_TIME_FIELD = "updated_at"
TARGET_COMPARE_TIME_FIELD = "updated_at"

SOURCE_CREATE_TIME_FIELD = "created_at"
TARGET_CREATE_TIME_FIELD = "created_at"
SOURCE_CHANGE_TIME_FIELD = "updated_at"
TARGET_CHANGE_TIME_FIELD = "updated_at"

TIME_FILTER_MODE = "change_time"
TIME_START = "2026-01-01 00:00:00"
TIME_END = "2026-02-01 00:00:00"

EXTRA_WHERE_SQL = "`status` IN (%s, %s)"
EXTRA_WHERE_PARAMS = ("paid", "shipped")

USE_UPSERT = False
UPSERT_UPDATE_COLUMNS = []
BATCH_SIZE = 5
SLEEP_SECONDS = 5
```

How this example works:

- `MATCH_COLUMN_MAPPING = [("customer_id", "customer_id")]` means both tables
  use `customer_id` to identify the same record.
- If a target row with the same `customer_id` does not exist, the row is inserted.
- If the row exists and `target.updated_at < source.updated_at`, the row is updated.
- If `target.updated_at >= source.updated_at`, the row is skipped.
- `TIME_FILTER_MODE = "change_time"` means the source query uses `updated_at`
  to find rows in the selected time window.
- `SOURCE_CREATE_TIME_FIELD` and `SOURCE_CHANGE_TIME_FIELD` help the script
  understand which source fields are creation and modification timestamps.
- `TARGET_CREATE_TIME_FIELD` and `TARGET_CHANGE_TIME_FIELD` let the same
  timestamp logic work even if the target table uses different column names.

## Files

- `db_config.py`: all editable settings with inline comments.
- `sync_table.py`: sync logic.
- `README.zh-CN.md`: simplified Chinese guide.
