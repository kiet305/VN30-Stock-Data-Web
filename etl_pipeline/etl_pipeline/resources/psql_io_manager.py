from contextlib import contextmanager
import os
import re
import tempfile
import time
import pandas as pd
from dagster import IOManager, OutputContext, InputContext
from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO)
logs = logging.getLogger("psql_io_manager")


@contextmanager
def connect_psql(config, schema: str):
    conn_info = (
        f"postgresql+psycopg2://{config['user']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )
    engine = create_engine(conn_info)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

    yield engine


class PostgreSQLIOManager(IOManager):
    def __init__(self, config):
        self._config = config

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    def _qualified_name(self, schema: str, table: str) -> str:
        return (
            f"{self._quote_identifier(schema)}."
            f"{self._quote_identifier(table)}"
        )

    def _index_name(self, table: str, columns: list[str], suffix: str = "idx") -> str:
        raw_name = "_".join([suffix, table, *columns])
        safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", raw_name).strip("_")
        return safe_name[:63]

    def _table_columns_with_types(self, conn, schema: str, table: str):
        return conn.execute(
            text(
                """
                SELECT
                    a.attname AS column_name,
                    pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
                JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = :schema
                  AND c.relname = :table
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY a.attnum
                """
            ),
            {"schema": schema, "table": table},
        ).all()

    def _replace_table_with_copy(
        self,
        *,
        conn,
        context: OutputContext,
        obj: pd.DataFrame,
        schema: str,
        table: str,
    ):
        total_start = time.perf_counter()
        target_table_name = self._qualified_name(schema, table)
        context.log.info(
            "PostgreSQL COPY replace start | "
            f"table={schema}.{table} | rows={len(obj)} | columns={len(obj.columns)}"
        )

        schema_start = time.perf_counter()
        obj.head(0).to_sql(
            table,
            con=conn,
            schema=schema,
            if_exists="replace",
            index=False,
        )
        context.log.info(
            "PostgreSQL COPY schema ready | "
            f"table={schema}.{table} | elapsed={time.perf_counter() - schema_start:.2f}s"
        )

        if obj.empty:
            context.log.info(
                "PostgreSQL COPY replace done | "
                f"table={schema}.{table} | rows=0 | elapsed={time.perf_counter() - total_start:.2f}s"
            )
            return

        csv_path = None
        try:
            csv_start = time.perf_counter()
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=f"_{table}.csv",
                delete=False,
                encoding="utf-8",
                newline="",
            ) as tmp_file:
                csv_path = tmp_file.name
                obj.to_csv(
                    tmp_file,
                    index=False,
                    na_rep="\\N",
                    date_format="%Y-%m-%d %H:%M:%S",
                )

            csv_size_mb = os.path.getsize(csv_path) / (1024 * 1024)
            context.log.info(
                "PostgreSQL COPY csv ready | "
                f"table={schema}.{table} | path={csv_path} | "
                f"size_mb={csv_size_mb:.2f} | elapsed={time.perf_counter() - csv_start:.2f}s"
            )

            copy_start = time.perf_counter()
            quoted_columns = ", ".join(
                self._quote_identifier(column_name)
                for column_name in obj.columns
            )
            copy_sql = (
                f"COPY {target_table_name} ({quoted_columns}) "
                "FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '\\N')"
            )
            driver_connection = conn.connection.driver_connection
            with driver_connection.cursor() as cursor:
                with open(csv_path, "r", encoding="utf-8", newline="") as csv_file:
                    cursor.copy_expert(copy_sql, csv_file)

            context.log.info(
                "PostgreSQL COPY data loaded | "
                f"table={schema}.{table} | rows={len(obj)} | "
                f"elapsed={time.perf_counter() - copy_start:.2f}s"
            )
        finally:
            if csv_path and os.path.exists(csv_path):
                os.remove(csv_path)

        context.log.info(
            "PostgreSQL COPY replace done | "
            f"table={schema}.{table} | rows={len(obj)} | "
            f"elapsed={time.perf_counter() - total_start:.2f}s"
        )

    def get_max_date(
        self,
        *,
        schema: str,
        table: str,
        date_column: str = "date",
    ):
        with connect_psql(self._config, schema) as engine:
            with engine.begin() as conn:
                exists = conn.execute(
                    text("SELECT to_regclass(:qualified_table)"),
                    {"qualified_table": f"{schema}.{table}"},
                ).scalar()

                if not exists:
                    return None

                return conn.execute(
                    text(f"SELECT MAX({date_column}) FROM {schema}.{table}")
                ).scalar()

    def load_input(self, context: InputContext) -> pd.DataFrame:
        raise NotImplementedError()

    def handle_output(self, context: OutputContext, obj: pd.DataFrame):
        table = context.asset_key.path[-1]
        schema = context.asset_key.path[0]

        # lấy unique_key từ metadata của asset output
        unique_key = (context.output_metadata or {}).get("unique_key")
        replace_table = (context.output_metadata or {}).get("replace_table")
        replace_by_columns = (context.output_metadata or {}).get("replace_by_columns")

        # convert Dagster metadata value -> python object
        if unique_key is not None and hasattr(unique_key, "value"):
            unique_key = unique_key.value
        if replace_table is not None and hasattr(replace_table, "value"):
            replace_table = replace_table.value
        if replace_by_columns is not None and hasattr(replace_by_columns, "value"):
            replace_by_columns = replace_by_columns.value

        context.log.info(f"Writing to table {schema}.{table}")
        if replace_table:
            context.log.info("Replace table mode enabled")
        if unique_key:
            context.log.info(f"Dedup enabled with unique_key={unique_key}")
        if replace_by_columns:
            context.log.info(
                f"Replace slice enabled with columns={replace_by_columns}"
            )

        with connect_psql(self._config, schema) as engine:
            with engine.begin() as conn:
                if replace_table:
                    self._replace_table_with_copy(
                        conn=conn,
                        context=context,
                        obj=obj,
                        schema=schema,
                        table=table,
                    )
                    return

                # 1) dedup trong dataframe
                if unique_key:
                    obj = obj.drop_duplicates(subset=unique_key, keep="last")

                if not unique_key:
                    # fallback: append bình thường
                    obj.to_sql(
                        table,
                        con=conn,
                        schema=schema,
                        if_exists="append",
                        index=False,
                    )
                    return

                # 2) tạo temp table
                temp_table = f"__tmp_{table}"
                conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{temp_table}"))

                obj.to_sql(
                    temp_table,
                    con=conn,
                    schema=schema,
                    if_exists="replace",
                    index=False,
                )

                # 3) delete record trùng key trong bảng thật
                if not conn.execute(
                    text("SELECT to_regclass(:qualified_table)"),
                    {"qualified_table": f"{schema}.{table}"},
                ).scalar():
                    obj.head(0).to_sql(
                        table,
                        con=conn,
                        schema=schema,
                        if_exists="replace",
                        index=False,
                    )

                temp_columns_with_types = self._table_columns_with_types(
                    conn, schema, temp_table
                )
                target_columns_with_types = self._table_columns_with_types(
                    conn, schema, table
                )
                target_columns = [
                    column_name
                    for column_name, _ in target_columns_with_types
                ]

                target_table_name = self._qualified_name(schema, table)
                temp_table_name = self._qualified_name(schema, temp_table)
                for column_name, data_type in temp_columns_with_types:
                    if column_name in target_columns:
                        continue
                    conn.execute(
                        text(
                            f"ALTER TABLE {target_table_name} "
                            f"ADD COLUMN {self._quote_identifier(column_name)} "
                            f"{data_type}"
                        )
                    )
                    target_columns.append(column_name)
                    target_columns_with_types.append((column_name, data_type))

                temp_columns = [
                    column_name
                    for column_name, _ in temp_columns_with_types
                ]
                target_type_by_column = {
                    column_name: data_type
                    for column_name, data_type in target_columns_with_types
                }
                insert_columns = [
                    column_name
                    for column_name in target_columns
                    if column_name in temp_columns
                ]
                quoted_insert_columns = ", ".join(
                    self._quote_identifier(column_name)
                    for column_name in insert_columns
                )
                select_columns = ", ".join(
                    (
                        f"{self._quote_identifier(column_name)}"
                        f"::{target_type_by_column[column_name]} "
                        f"AS {self._quote_identifier(column_name)}"
                    )
                    for column_name in insert_columns
                )

                delete_columns = replace_by_columns or unique_key
                join_cond = " AND ".join(
                    [
                        f"t.{self._quote_identifier(c)} "
                        f"IS NOT DISTINCT FROM s.{self._quote_identifier(c)}"
                        for c in delete_columns
                    ]
                )

                quoted_key_columns = ", ".join(
                    self._quote_identifier(column_name)
                    for column_name in delete_columns
                )
                target_index = self._quote_identifier(
                    self._index_name(table, delete_columns)
                )
                temp_index = self._quote_identifier(
                    self._index_name(temp_table, delete_columns)
                )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {target_index} "
                        f"ON {target_table_name} ({quoted_key_columns})"
                    )
                )
                conn.execute(
                    text(
                        f"CREATE INDEX {temp_index} "
                        f"ON {temp_table_name} ({quoted_key_columns})"
                    )
                )

                delete_source = temp_table_name
                if replace_by_columns:
                    distinct_columns = ", ".join(
                        self._quote_identifier(column_name)
                        for column_name in replace_by_columns
                    )
                    delete_source = (
                        f"(SELECT DISTINCT {distinct_columns} "
                        f"FROM {temp_table_name})"
                    )

                delete_sql = f"""
                    DELETE FROM {target_table_name} t
                    USING {delete_source} s
                    WHERE {join_cond}
                """
                conn.execute(text(delete_sql))

                # 4) insert dữ liệu mới
                insert_sql = f"""
                    INSERT INTO {target_table_name} ({quoted_insert_columns})
                    SELECT {select_columns}
                    FROM {temp_table_name}
                """
                conn.execute(text(insert_sql))

                # 5) drop temp
                conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{temp_table}"))

        context.log.info(f"Done write {schema}.{table}, rows={len(obj)}")
