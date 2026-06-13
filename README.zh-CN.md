# db_sync_tables

语言切换：
- [English](README.md)

这是一个使用 `uv` 和 `pymysql` 的 MySQL 表同步工具。

## 使用流程

1. 修改 `db_config.py`。
2. 如果 `pymysql` 已经安装在 uv 环境里，直接运行：

```bash
uv run --no-sync python sync_table.py
```

3. 如果你希望由 uv 根据 `pyproject.toml` 创建或刷新环境，先执行
   `uv sync`，再运行脚本。
4. 将 `DEBUG = True`，只打印 SQL 模板，不实际执行。
5. 将 `DEBUG = False`，执行真实同步。

## 配置说明

`db_config.py` 是运行时配置文件。下面是主要字段示例。

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

字段说明：

- `DEBUG = True`：只打印 SQL，不执行。
- `SOURCE_DB`：源数据库连接，建议只读权限。
- `TARGET_DB`：目标数据库连接，建议读写权限。
- `COLUMN_MAPPING`：从源表同步到目标表的字段映射。
- `MATCH_COLUMN_MAPPING`：用于判断同一条记录的匹配字段。
  如果源表和目标表字段名一样，直接写成相同的配对，例如 `("id", "id")`。
- 同步判定流程：
  - 如果目标表没有这条记录，直接插入
  - 如果目标表有这条记录，并且目标时间戳小于源时间戳，执行更新
  - 如果目标时间戳大于等于源时间戳，则跳过
- `SOURCE_COMPARE_TIME_FIELD` / `TARGET_COMPARE_TIME_FIELD`：用于插入/更新/跳过判断的时间字段。
- `SOURCE_CREATE_TIME_FIELD` / `TARGET_CREATE_TIME_FIELD` 和
  `SOURCE_CHANGE_TIME_FIELD` / `TARGET_CHANGE_TIME_FIELD`：用于源表筛选和自动映射，可以按实际字段名自定义。
- 为什么会有多个 TIME_FIELD：
  - `create_time` 通常表示创建时间
  - `change_time` 通常表示最后更新时间
  - `TIME_FILTER_MODE` 决定源表查询时使用哪个时间字段
- `TIME_FILTER_MODE = "change_time"`：按源表变更时间筛选。
- `TIME_FILTER_MODE = "create_or_change"`：按源表创建时间或变更时间筛选。
- `TIME_START` / `TIME_END`：源表查询的时间范围。
- `EXTRA_WHERE_SQL` / `EXTRA_WHERE_PARAMS`：额外的源表筛选条件。
- `USE_UPSERT = True`：当需要写入时，使用 `INSERT ... ON DUPLICATE KEY UPDATE`。
- `UPSERT_UPDATE_COLUMNS`：限制 upsert 时实际刷新的字段。
- `BATCH_SIZE` 默认 `5`。
- `SLEEP_SECONDS` 默认 `5`。

## 真实场景示例

场景：

- 源数据库：`crm_readonly`
- 目标数据库：`crm_rw`
- 源表：`customer_profile`
- 目标表：`customer_profile_sync`
- 使用 `customer_id` 判断是否为同一条数据
- 业务字段包括 `name`、`phone`、`status`
- 源表有 `created_at` 和 `updated_at`
- 目标表也有同样字段
- 只同步 2026 年 1 月更新过的数据

示例配置：

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

这个示例的含义：

- `MATCH_COLUMN_MAPPING = [("order_id", "order_id")]` 表示两边都用
- `MATCH_COLUMN_MAPPING = [("customer_id", "customer_id")]` 表示两边都用
  `customer_id` 识别同一条数据。
- 如果目标表里没有相同 `customer_id` 的记录，就插入。
- 如果记录存在，并且 `目标.updated_at < 源.updated_at`，就更新。
- 如果 `目标.updated_at >= 源.updated_at`，就跳过。
- `TIME_FILTER_MODE = "change_time"` 表示源表筛选时使用 `updated_at`
  来取指定时间范围内的数据。
- `SOURCE_CREATE_TIME_FIELD` 和 `SOURCE_CHANGE_TIME_FIELD` 用来说明源表
  哪个字段是创建时间、哪个字段是更新时间。
- `TARGET_CREATE_TIME_FIELD` 和 `TARGET_CHANGE_TIME_FIELD` 允许目标表
  使用不同字段名时仍然复用同一套逻辑。

## 文件说明

- `db_config.py`：所有可填写配置，带注释。
- `sync_table.py`：同步逻辑。
- `README.md`：英文入口。
