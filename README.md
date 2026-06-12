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

## Config Notes

- `SOURCE_DB` should have read-only permission.
- `TARGET_DB` should have read/write permission.
- `MATCH_COLUMN_MAPPING` defines how one source row matches one target row.
- `SOURCE_COMPARE_TIME_FIELD` and `TARGET_COMPARE_TIME_FIELD` control the
  skip rule. If the target time is greater than or equal to the source time,
  the row is skipped.
- `BATCH_SIZE` defaults to `5`.
- `SLEEP_SECONDS` defaults to `5`.
- `TIME_FILTER_MODE` supports `change_time` and `create_or_change`.

## Files

- `db_config.py`: all editable settings with comments.
- `sync_table.py`: sync logic.
- `README.zh-CN.md`: simplified Chinese guide.
