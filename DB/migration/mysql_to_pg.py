"""MySQL(zhida) -> PostgreSQL(zhida) 业务表结构与数据迁移。

用法（在项目根目录执行）：
    python DB/migration/mysql_to_pg.py            # 目标表非空时拒绝执行
    python DB/migration/mysql_to_pg.py --force    # 清空目标表后全量重导

说明：
- 表结构由 SQLAlchemy ORM 元数据 create_all 生成，与运行时代码保持一致；
- 显式保留 MySQL 侧主键；导入后重置自增序列，避免新插入撞主键；
- 不迁移向量，向量迁移见同目录 chroma_to_pgvector.py。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from sqlalchemy import JSON, create_engine, inspect, text
from sqlalchemy.types import Integer

load_dotenv()

import gateway.models  # noqa: E402,F401  注册网关 4 张表
import model.models  # noqa: E402,F401     注册业务表
from model.initDataBase import Base  # noqa: E402
from model.initDataBase import engine as pg_engine  # noqa: E402


def build_mysql_engine():
    url = (
        f"mysql+pymysql://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}"
        f"@{os.getenv('MYSQL_HOST')}:{os.getenv('MYSQL_PORT')}/{os.getenv('MYSQL_DB')}"
        f"?charset=utf8mb4"
    )
    return create_engine(url)


def normalize_json(row: dict, table) -> dict:
    """MySQL 的 JSON 列可能以字符串返回，PG JSONB 需要 dict/list。"""
    for column in table.columns:
        value = row.get(column.name)
        if isinstance(column.type, JSON) and isinstance(value, str):
            row[column.name] = json.loads(value)
    return row


def reset_sequences(conn, tables) -> None:
    """显式插入主键后，把 PG 自增序列推到当前最大值。"""
    for table in tables:
        pk_columns = list(table.primary_key.columns)
        if len(pk_columns) != 1 or not isinstance(pk_columns[0].type, Integer):
            continue
        pk_name, table_name = pk_columns[0].name, table.name
        sequence = conn.execute(
            text("SELECT pg_get_serial_sequence(:t, :c)"),
            {"t": table_name, "c": pk_name},
        ).scalar()
        if not sequence:
            continue
        conn.execute(
            text(
                f'SELECT setval(CAST(:seq AS regclass), '
                f'COALESCE((SELECT MAX("{pk_name}") FROM "{table_name}"), 1), '
                f'(SELECT COUNT(*) > 0 FROM "{table_name}"))'
            ),
            {"seq": sequence},
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="目标表非空也执行（先清空）")
    args = parser.parse_args()

    source = build_mysql_engine()
    mysql_tables = set(inspect(source).get_table_names())

    Base.metadata.create_all(pg_engine)
    tables = [t for t in Base.metadata.sorted_tables if t.name in mysql_tables]
    print(f"待迁移表 {len(tables)} 张: {', '.join(t.name for t in tables)}")

    with pg_engine.begin() as dst:
        non_empty = [
            (t.name, dst.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar())
            for t in tables
        ]
        occupied = [(name, n) for name, n in non_empty if n]
        if occupied and not args.force:
            print("目标库已有数据，已中止（加 --force 清空后重导）:")
            for name, n in occupied:
                print(f"  {name}: {n}")
            raise SystemExit(1)

        for table in reversed(tables):
            dst.execute(table.delete())

        with source.connect() as src:
            total = 0
            for table in tables:
                rows = [normalize_json(dict(row._mapping), table) for row in src.execute(table.select())]
                if rows:
                    dst.execute(table.insert(), rows)
                total += len(rows)
                print(f"  {table.name}: {len(rows)} 行")

        reset_sequences(dst, tables)

    with pg_engine.connect() as conn:
        print("迁移完成，目标库行数校验:")
        for table in tables:
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
            print(f"  {table.name}: {count}")


if __name__ == "__main__":
    main()
