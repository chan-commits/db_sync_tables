"""Editable configuration for source -> target table syncing.

Fill in every value below before running the sync script.
Other servers only need to copy this file and adjust the values.
"""

# Set to True to print SQL templates only and skip all database execution.
# Set to False to run the real sync job.
DEBUG = True

# Source database connection.
# This account should have read-only permission on the source DB.
SOURCE_DB = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "source_user",
    "password": "source_password",
    "database": "source_database",
    "charset": "utf8mb4",
}

# Target database connection.
# This account should have read/write permission on the target DB.
TARGET_DB = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "target_user",
    "password": "target_password",
    "database": "target_database",
    "charset": "utf8mb4",
}

# Source table name and target table name.
SOURCE_TABLE = "source_table"
TARGET_TABLE = "target_table"

# Columns to sync from source -> target.
# Keep the same name when both sides use the same column name.
# Example:
# COLUMN_MAPPING = [
#     ("id", "id"),
#     ("user_name", "user_name"),
#     ("created_at", "create_time"),
#     ("updated_at", "change_time"),
# ]
COLUMN_MAPPING = [
    ("id", "id"),
]

# Columns used to locate the same row in both tables.
# Example:
# MATCH_COLUMN_MAPPING = [
#     ("id", "id"),
# ]
MATCH_COLUMN_MAPPING = [
    ("id", "id"),
]

# Source/target timestamp field names used for comparison.
# If the target row time is greater than or equal to the source row time,
# the script skips that row.
SOURCE_COMPARE_TIME_FIELD = "change_time"
TARGET_COMPARE_TIME_FIELD = "change_time"

# Optional create-time field names. These are added into the sync mapping
# automatically when they are not already listed in COLUMN_MAPPING.
SOURCE_CREATE_TIME_FIELD = "create_time"
TARGET_CREATE_TIME_FIELD = "create_time"

# Optional change-time field names. These are added into the sync mapping
# automatically when they are not already listed in COLUMN_MAPPING.
SOURCE_CHANGE_TIME_FIELD = "change_time"
TARGET_CHANGE_TIME_FIELD = "change_time"

# Query mode:
# - "change_time": filter by the source change-time field only.
# - "create_or_change": filter by either source create-time or change-time.
TIME_FILTER_MODE = "change_time"

# Time window used by the WHERE clause.
# Leave one side as None if you only want a lower or upper bound.
TIME_START = "2026-01-01 00:00:00"
TIME_END = "2026-02-01 00:00:00"

# Extra WHERE clause that will be appended to the time filter.
# Example:
# EXTRA_WHERE_SQL = "`status` = %s AND `is_deleted` = %s"
# EXTRA_WHERE_PARAMS = (1, 0)
EXTRA_WHERE_SQL = ""
EXTRA_WHERE_PARAMS = ()

# Insert/update behavior for rows that should be synced.
# True: use INSERT ... ON DUPLICATE KEY UPDATE.
# False: use UPDATE for existing rows and INSERT for new rows.
USE_UPSERT = True

# Columns to update when USE_UPSERT is enabled.
# If empty, the script updates every mapped target column.
UPSERT_UPDATE_COLUMNS = []

# Number of rows fetched from the source DB per batch.
BATCH_SIZE = 5

# Sleep interval between batches, in seconds.
SLEEP_SECONDS = 5
