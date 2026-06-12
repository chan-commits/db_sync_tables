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

- `SOURCE_DB`：源数据库连接，建议只读权限。
- `TARGET_DB`：目标数据库连接，建议读写权限。
- `SOURCE_TABLE` / `TARGET_TABLE`：源表和目标表名称。
- `COLUMN_MAPPING`：需要从源表同步到目标表的字段映射。
- `MATCH_COLUMN_MAPPING`：用于判断同一条记录的匹配字段。
- `SOURCE_COMPARE_TIME_FIELD` / `TARGET_COMPARE_TIME_FIELD`：时间比较字段。
- 如果目标时间 `>=` 源时间，则跳过该条数据，不做任何操作。
- `BATCH_SIZE`：每批处理条数，默认 `5`。
- `SLEEP_SECONDS`：每批之间的休眠秒数，默认 `5`。
- `TIME_FILTER_MODE`：
  - `change_time`：按源表变更时间筛选。
  - `create_or_change`：按源表创建时间或变更时间筛选。

## 文件说明

- `db_config.py`：所有可填写配置，带注释。
- `sync_table.py`：同步逻辑。
- `README.md`：英文入口。
