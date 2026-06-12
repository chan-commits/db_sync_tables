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
- `SOURCE_COMPARE_TIME_FIELD` and `TARGET_COMPARE_TIME_FIELD` control the
  skip rule.
- If the target timestamp is greater than or equal to the source timestamp,
  the row is skipped.
- `SOURCE_CREATE_TIME_FIELD` / `TARGET_CREATE_TIME_FIELD` and
  `SOURCE_CHANGE_TIME_FIELD` / `TARGET_CHANGE_TIME_FIELD` can be customized
  when the timestamp columns use different names.
- `TIME_FILTER_MODE = "change_time"` filters by the source change time.
- `TIME_FILTER_MODE = "create_or_change"` filters by source create time or
  source change time.
- `BATCH_SIZE` defaults to `5`.
- `SLEEP_SECONDS` defaults to `5`.

## Files

- `db_config.py`: all editable settings with inline comments.
- `sync_table.py`: sync logic.
- `README.zh-CN.md`: simplified Chinese guide.
