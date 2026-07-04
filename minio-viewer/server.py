from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_MINIO_ROOT = APP_DIR.parent / "minio"
MAX_SEARCH_RESULTS = 500
MAX_TREE_ENTRIES = 5000
MAX_PREVIEW_ROWS = 100
PREVIEW_ROW_OPTIONS = {"10", "25", "50", "100", "all"}
PREVIEW_ORDER_OPTIONS = {"head", "tail"}


def load_project_env() -> None:
    env_file = APP_DIR.parent / ".env"
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def iso_time(value) -> str | None:
    if not value:
        return None
    if hasattr(value, "astimezone"):
        return value.astimezone().isoformat(timespec="seconds")
    return str(value)


class MinioViewer:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve_relative(self, raw_path: str | None) -> tuple[Path, str]:
        raw_path = unquote(raw_path or "").replace("\\", "/").strip("/")
        candidate = (self.root / raw_path).resolve()
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("Path is outside the configured MinIO root") from exc
        return candidate, relative.as_posix() if relative.as_posix() != "." else ""

    @staticmethod
    def include_system(query: dict[str, list[str]]) -> bool:
        return query.get("includeSystem", ["0"])[0] in {"1", "true", "yes", "on"}

    @staticmethod
    def skip_name(name: str, include_system: bool) -> bool:
        return not include_system and name == ".minio.sys"

    @staticmethod
    def format_time(timestamp: float) -> str:
        value = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()
        return value.isoformat(timespec="seconds")

    def entry_payload(self, path: Path, rel_path: str, include_system: bool) -> dict:
        stat = path.stat()
        is_dir = path.is_dir()
        children_count = None

        if is_dir:
            try:
                children_count = sum(
                    1
                    for child in path.iterdir()
                    if not self.skip_name(child.name, include_system)
                )
            except OSError:
                children_count = 0

        return {
            "name": path.name or self.root.name,
            "path": rel_path,
            "type": "directory" if is_dir else "file",
            "size": stat.st_size if path.is_file() else None,
            "modified": self.format_time(stat.st_mtime),
            "childrenCount": children_count,
        }

    def list_directory(self, raw_path: str | None, include_system: bool) -> dict:
        directory, rel_path = self.resolve_relative(raw_path)
        if not directory.exists():
            raise FileNotFoundError("Path does not exist")
        if not directory.is_dir():
            raise NotADirectoryError("Path is not a directory")

        entries = []
        for child in directory.iterdir():
            if self.skip_name(child.name, include_system):
                continue
            child_rel = child.relative_to(self.root).as_posix()
            entries.append(self.entry_payload(child, child_rel, include_system))

        entries.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
        return {
            "root": str(self.root),
            "path": rel_path,
            "name": directory.name,
            "entries": entries,
            "breadcrumbs": self.breadcrumbs(rel_path),
        }

    def breadcrumbs(self, rel_path: str) -> list[dict[str, str]]:
        crumbs = [{"name": self.root.name, "path": ""}]
        current = []
        for part in rel_path.split("/"):
            if not part:
                continue
            current.append(part)
            crumbs.append({"name": part, "path": "/".join(current)})
        return crumbs

    def overview(self, include_system: bool) -> dict:
        buckets = []
        total_files = 0
        total_dirs = 0
        total_size = 0

        if self.root.exists():
            for child in self.root.iterdir():
                if not child.is_dir() or self.skip_name(child.name, include_system):
                    continue
                child_rel = child.relative_to(self.root).as_posix()
                summary = self.scan_summary(child, include_system, MAX_TREE_ENTRIES)
                buckets.append(
                    {
                        **self.entry_payload(child, child_rel, include_system),
                        "fileCount": summary["files"],
                        "directoryCount": summary["directories"],
                        "totalSize": summary["size"],
                        "truncated": summary["truncated"],
                    }
                )
                total_files += summary["files"]
                total_dirs += summary["directories"]
                total_size += summary["size"]

        buckets.sort(key=lambda item: item["name"].lower())
        return {
            "root": str(self.root),
            "exists": self.root.exists(),
            "bucketCount": len(buckets),
            "fileCount": total_files,
            "directoryCount": total_dirs,
            "totalSize": total_size,
            "buckets": buckets,
        }

    def scan_summary(self, directory: Path, include_system: bool, limit: int) -> dict:
        files = 0
        directories = 0
        size = 0
        seen = 0
        truncated = False
        stack = [directory]

        while stack:
            current = stack.pop()
            try:
                children = list(current.iterdir())
            except OSError:
                continue

            for child in children:
                if self.skip_name(child.name, include_system):
                    continue
                seen += 1
                if seen > limit:
                    truncated = True
                    stack.clear()
                    break
                if child.is_dir():
                    directories += 1
                    stack.append(child)
                else:
                    files += 1
                    try:
                        size += child.stat().st_size
                    except OSError:
                        pass

        return {
            "files": files,
            "directories": directories,
            "size": size,
            "truncated": truncated,
        }

    def search(self, query: str, include_system: bool, limit: int) -> dict:
        term = query.strip().lower()
        if not term:
            return {"query": query, "results": [], "truncated": False}

        results = []
        truncated = False
        stack = [self.root]

        while stack:
            current = stack.pop()
            try:
                children = list(current.iterdir())
            except OSError:
                continue

            for child in children:
                if self.skip_name(child.name, include_system):
                    continue

                rel_path = child.relative_to(self.root).as_posix()
                if term in child.name.lower() or term in rel_path.lower():
                    results.append(self.entry_payload(child, rel_path, include_system))
                    if len(results) >= limit:
                        truncated = True
                        stack.clear()
                        break

                if child.is_dir():
                    stack.append(child)

        results.sort(key=lambda item: (item["type"] != "directory", item["path"].lower()))
        return {"query": query, "results": results, "truncated": truncated}

    def tree(self, raw_path: str | None, include_system: bool, depth: int) -> dict:
        start, rel_path = self.resolve_relative(raw_path)
        if not start.exists():
            raise FileNotFoundError("Path does not exist")

        count = 0

        def build(path: Path, remaining_depth: int) -> dict:
            nonlocal count
            current_rel = path.relative_to(self.root).as_posix() if path != self.root else ""
            payload = self.entry_payload(path, current_rel, include_system)
            payload["children"] = []

            if not path.is_dir() or remaining_depth <= 0:
                return payload

            try:
                children = [
                    child
                    for child in path.iterdir()
                    if not self.skip_name(child.name, include_system)
                ]
            except OSError:
                return payload

            children.sort(key=lambda item: (not item.is_dir(), item.name.lower()))
            for child in children:
                count += 1
                if count > MAX_TREE_ENTRIES:
                    payload["truncated"] = True
                    break
                payload["children"].append(build(child, remaining_depth - 1))
            return payload

        return {
            "root": str(self.root),
            "path": rel_path,
            "tree": build(start, max(0, min(depth, 8))),
        }

    def preview(
        self,
        raw_path: str | None,
        rows: int | str,
        order: str = "head",
        ticker: str = "",
    ) -> dict:
        target, rel_path = self.resolve_relative(raw_path)
        if not target.exists():
            raise FileNotFoundError("Path does not exist")

        rows = self.normalize_preview_rows(rows)
        order = self.normalize_preview_order(order)
        source = self.dataframe_source(target)
        suffix = target.name.lower()

        if suffix.endswith(".parquet"):
            return self.preview_parquet(source, rel_path, rows, order, ticker)
        if suffix.endswith(".csv"):
            return self.preview_csv(source, rel_path, rows, order, ticker)
        if suffix.endswith(".json") or suffix.endswith(".jsonl") or suffix.endswith(".ndjson"):
            return self.preview_json(
                source,
                rel_path,
                rows,
                order,
                lines=not suffix.endswith(".json"),
                ticker=ticker,
            )

        raise ValueError("Unsupported preview format. Supported: parquet, csv, json, jsonl")

    def dataframe_source(self, target: Path):
        if target.is_file():
            return target

        part_files = []
        for child in target.rglob("*"):
            if not child.is_file():
                continue
            name = child.name.lower()
            if name == "xl.meta" or name.endswith(".meta"):
                continue
            if name.startswith("part."):
                part_files.append(child)

        if not part_files:
            raise FileNotFoundError("No readable data part found inside this MinIO object folder")

        part_files.sort(key=self.part_sort_key)
        data = b"".join(part.read_bytes() for part in part_files)
        first_magic = data.find(b"PAR1")
        last_magic = data.rfind(b"PAR1")
        if first_magic >= 0 and last_magic > first_magic:
            data = data[first_magic : last_magic + 4]
        return io.BytesIO(data)

    @staticmethod
    def part_sort_key(path: Path) -> tuple[int, str]:
        suffix = path.name.split(".", 1)[-1]
        return (int(suffix) if suffix.isdigit() else 10**9, path.name)

    @staticmethod
    def normalize_preview_rows(rows: int | str) -> int | str:
        if rows == "all":
            return "all"
        rows = int(rows)
        return max(1, min(rows, MAX_PREVIEW_ROWS))

    @staticmethod
    def normalize_preview_order(order: str) -> str:
        return order if order in PREVIEW_ORDER_OPTIONS else "head"

    @staticmethod
    def select_preview_dataframe(dataframe, rows: int | str, order: str):
        if rows == "all":
            selected = dataframe
        elif order == "tail":
            selected = dataframe.tail(rows)
        else:
            selected = dataframe.head(rows)

        if order == "tail":
            selected = selected.iloc[::-1]

        return selected

    @staticmethod
    def filter_ticker_dataframe(dataframe, ticker: str):
        term = (ticker or "").strip().upper()
        if not term:
            return dataframe, None, ""

        ticker_column = next(
            (
                column
                for column in dataframe.columns
                if str(column).strip().lower() in {"ticker", "symbol"}
            ),
            None,
        )
        if ticker_column is None:
            return dataframe.iloc[0:0].copy(), None, term

        mask = dataframe[ticker_column].astype(str).str.strip().str.upper().eq(term)
        return dataframe[mask].copy(), ticker_column, term

    def preview_parquet(
        self,
        source,
        rel_path: str,
        rows: int | str,
        order: str,
        ticker: str = "",
    ) -> dict:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("pyarrow is required to preview parquet files") from exc

        parquet_file = pq.ParquetFile(source)
        metadata = parquet_file.metadata
        if not ticker and rows != "all" and order == "head" and metadata.num_row_groups:
            preview_table = None
            batches = []
            remaining = rows
            for index in range(metadata.num_row_groups):
                row_group = parquet_file.read_row_group(index)
                if row_group.num_rows > remaining:
                    row_group = row_group.slice(0, remaining)
                batches.append(row_group)
                remaining -= row_group.num_rows
                if remaining <= 0:
                    break
            if batches:
                import pyarrow as pa

                preview_table = pa.concat_tables(batches, promote_options="default")
            dataframe = preview_table.to_pandas() if preview_table is not None else None
            filtered_row_count = None
            ticker_column = None
            ticker_value = ""
        else:
            dataframe = parquet_file.read().to_pandas()
            dataframe, ticker_column, ticker_value = MinioViewer.filter_ticker_dataframe(
                dataframe,
                ticker,
            )
            filtered_row_count = len(dataframe) if ticker_value else None
            dataframe = MinioViewer.select_preview_dataframe(dataframe, rows, order)

        return self.preview_payload(
            rel_path=rel_path,
            format_name="parquet",
            columns=parquet_file.schema.names,
            row_count=metadata.num_rows,
            preview_df=dataframe,
            dtypes={field.name: str(field.type) for field in parquet_file.schema_arrow},
            order=order,
            ticker=ticker_value,
            ticker_column=ticker_column,
            filtered_row_count=filtered_row_count,
        )

    def preview_csv(
        self,
        source,
        rel_path: str,
        rows: int | str,
        order: str,
        ticker: str = "",
    ) -> dict:
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("pandas is required to preview csv files") from exc

        dataframe = pd.read_csv(
            source,
            nrows=rows if not ticker and rows != "all" and order == "head" else None,
        )
        dataframe, ticker_column, ticker_value = MinioViewer.filter_ticker_dataframe(
            dataframe,
            ticker,
        )
        filtered_row_count = len(dataframe) if ticker_value else None
        dataframe = MinioViewer.select_preview_dataframe(dataframe, rows, order)
        return self.preview_payload(
            rel_path=rel_path,
            format_name="csv",
            columns=list(dataframe.columns),
            row_count=None,
            preview_df=dataframe,
            dtypes={column: str(dtype) for column, dtype in dataframe.dtypes.items()},
            order=order,
            ticker=ticker_value,
            ticker_column=ticker_column,
            filtered_row_count=filtered_row_count,
        )

    def preview_json(
        self,
        source,
        rel_path: str,
        rows: int | str,
        order: str,
        lines: bool,
        ticker: str = "",
    ) -> dict:
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("pandas is required to preview json files") from exc

        dataframe = pd.read_json(source, lines=lines)
        dataframe, ticker_column, ticker_value = MinioViewer.filter_ticker_dataframe(
            dataframe,
            ticker,
        )
        filtered_row_count = len(dataframe) if ticker_value else None
        dataframe = MinioViewer.select_preview_dataframe(dataframe, rows, order)
        return self.preview_payload(
            rel_path=rel_path,
            format_name="jsonl" if lines else "json",
            columns=list(dataframe.columns),
            row_count=None,
            preview_df=dataframe,
            dtypes={column: str(dtype) for column, dtype in dataframe.dtypes.items()},
            order=order,
            ticker=ticker_value,
            ticker_column=ticker_column,
            filtered_row_count=filtered_row_count,
        )

    @staticmethod
    def preview_payload(
        rel_path: str,
        format_name: str,
        columns: list[str],
        row_count: int | None,
        preview_df,
        dtypes: dict[str, str],
        order: str,
        ticker: str = "",
        ticker_column: str | None = None,
        filtered_row_count: int | None = None,
    ) -> dict:
        if preview_df is None:
            records = []
        else:
            preview_df = preview_df.astype(object).where(preview_df.notna(), None)
            records = json.loads(preview_df.to_json(orient="records", force_ascii=False, date_format="iso"))

        return {
            "path": rel_path,
            "format": format_name,
            "rowCount": row_count,
            "columnCount": len(columns),
            "columns": columns,
            "dtypes": dtypes,
            "order": order,
            "ticker": ticker,
            "tickerColumn": ticker_column,
            "filteredRowCount": filtered_row_count,
            "rows": records,
        }


class MinioApiViewer:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        from minio import Minio

        self.endpoint = endpoint
        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    @staticmethod
    def include_system(query: dict[str, list[str]]) -> bool:
        return query.get("includeSystem", ["0"])[0] in {"1", "true", "yes", "on"}

    @staticmethod
    def normalize_prefix(raw_path: str | None) -> str:
        prefix = unquote(raw_path or "").replace("\\", "/").strip("/")
        if ".." in prefix.split("/"):
            raise PermissionError("Path is outside the configured MinIO bucket")
        return f"{prefix}/" if prefix else ""

    @staticmethod
    def display_name(object_name: str, is_dir: bool) -> str:
        value = object_name.rstrip("/") if is_dir else object_name
        return value.rsplit("/", 1)[-1] or value

    def entry_payload(self, item, include_system: bool) -> dict:
        is_dir = bool(item.is_dir)
        object_name = item.object_name.rstrip("/") if is_dir else item.object_name
        return {
            "name": self.display_name(item.object_name, is_dir),
            "path": object_name,
            "type": "directory" if is_dir else "file",
            "size": None if is_dir else item.size,
            "modified": iso_time(item.last_modified),
            "childrenCount": None,
        }

    def children_count(self, path: str) -> int:
        prefix = f"{path.strip('/')}/" if path else ""
        count = 0
        for _ in self.client.list_objects(self.bucket, prefix=prefix, recursive=False):
            count += 1
        return count

    def list_directory(self, raw_path: str | None, include_system: bool) -> dict:
        prefix = self.normalize_prefix(raw_path)
        entries = [
            self.entry_payload(item, include_system)
            for item in self.client.list_objects(self.bucket, prefix=prefix, recursive=False)
        ]
        entries.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
        rel_path = prefix.rstrip("/")
        return {
            "root": f"minio://{self.endpoint}/{self.bucket}",
            "path": rel_path,
            "name": self.bucket if not rel_path else rel_path.rsplit("/", 1)[-1],
            "entries": entries,
            "breadcrumbs": self.breadcrumbs(rel_path),
        }

    def breadcrumbs(self, rel_path: str) -> list[dict[str, str]]:
        crumbs = [{"name": self.bucket, "path": ""}]
        current = []
        for part in rel_path.split("/"):
            if not part:
                continue
            current.append(part)
            crumbs.append({"name": part, "path": "/".join(current)})
        return crumbs

    def overview(self, include_system: bool) -> dict:
        direct_files = 0
        direct_directories = 0
        total_size = 0
        latest_modified = None

        for item in self.client.list_objects(self.bucket, recursive=False):
            if item.is_dir:
                direct_directories += 1
                continue
            direct_files += 1
            total_size += item.size or 0
            if item.last_modified and (latest_modified is None or item.last_modified > latest_modified):
                latest_modified = item.last_modified

        bucket_entry = {
            "name": self.bucket,
            "path": "",
            "type": "directory",
            "size": None,
            "modified": iso_time(latest_modified),
            "childrenCount": None,
            "fileCount": direct_files,
            "directoryCount": direct_directories,
            "totalSize": total_size,
            "truncated": False,
        }
        return {
            "root": f"minio://{self.endpoint}/{self.bucket}",
            "exists": True,
            "bucketCount": 1,
            "fileCount": direct_files,
            "directoryCount": direct_directories,
            "totalSize": total_size,
            "buckets": [bucket_entry],
        }

    def search(self, query: str, include_system: bool, limit: int) -> dict:
        term = query.strip().lower()
        if not term:
            return {"query": query, "results": [], "truncated": False}

        results = []
        truncated = False
        seen_dirs = set()
        for item in self.client.list_objects(self.bucket, recursive=True):
            if item.is_dir:
                continue
            parts = item.object_name.split("/")
            for index in range(1, len(parts)):
                directory = "/".join(parts[:index])
                if directory not in seen_dirs and term in directory.lower():
                    seen_dirs.add(directory)
                    fake = type("Object", (), {
                        "is_dir": True,
                        "object_name": f"{directory}/",
                        "size": None,
                        "last_modified": None,
                    })
                    results.append(self.entry_payload(fake, include_system))
            if term in item.object_name.lower():
                results.append(self.entry_payload(item, include_system))
            if len(results) >= limit:
                truncated = True
                break

        results.sort(key=lambda item: (item["type"] != "directory", item["path"].lower()))
        return {"query": query, "results": results[:limit], "truncated": truncated}

    def tree(self, raw_path: str | None, include_system: bool, depth: int) -> dict:
        start = self.normalize_prefix(raw_path).rstrip("/")
        count = 0

        def build(path: str, remaining_depth: int) -> dict:
            nonlocal count
            name = self.bucket if not path else path.rsplit("/", 1)[-1]
            payload = {
                "name": name,
                "path": path,
                "type": "directory",
                "size": None,
                "modified": None,
                "childrenCount": None,
                "children": [],
            }
            if remaining_depth <= 0:
                return payload

            prefix = f"{path}/" if path else ""
            children = [
                self.entry_payload(item, include_system)
                for item in self.client.list_objects(self.bucket, prefix=prefix, recursive=False)
            ]
            children.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
            for child in children:
                count += 1
                if count > MAX_TREE_ENTRIES:
                    payload["truncated"] = True
                    break
                if child["type"] == "directory":
                    payload["children"].append(build(child["path"], remaining_depth - 1))
                else:
                    child["children"] = []
                    payload["children"].append(child)
            return payload

        return {
            "root": f"minio://{self.endpoint}/{self.bucket}",
            "path": start,
            "tree": build(start, max(0, min(depth, 8))),
        }

    def preview(
        self,
        raw_path: str | None,
        rows: int | str,
        order: str = "head",
        ticker: str = "",
    ) -> dict:
        object_name = self.normalize_prefix(raw_path).rstrip("/")
        if not object_name:
            raise ValueError("Select a data object to preview")
        rows = MinioViewer.normalize_preview_rows(rows)
        order = MinioViewer.normalize_preview_order(order)

        response = self.client.get_object(self.bucket, object_name)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()

        source = io.BytesIO(data)
        suffix = object_name.lower()
        if suffix.endswith(".parquet"):
            return MinioViewer.preview_parquet(self, source, object_name, rows, order, ticker)
        if suffix.endswith(".csv"):
            return MinioViewer.preview_csv(self, source, object_name, rows, order, ticker)
        if suffix.endswith(".json") or suffix.endswith(".jsonl") or suffix.endswith(".ndjson"):
            return MinioViewer.preview_json(
                self,
                source,
                object_name,
                rows,
                order,
                lines=not suffix.endswith(".json"),
                ticker=ticker,
            )
        raise ValueError("Unsupported preview format. Supported: parquet, csv, json, jsonl")

    preview_payload = staticmethod(MinioViewer.preview_payload)


def make_handler(viewer: MinioViewer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MinioViewer/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            try:
                if parsed.path == "/" or parsed.path == "/index.html":
                    self.serve_static(STATIC_DIR / "index.html")
                elif parsed.path.startswith("/static/"):
                    rel = parsed.path.removeprefix("/static/").strip("/")
                    self.serve_static((STATIC_DIR / rel).resolve())
                elif parsed.path == "/api/overview":
                    self.send_json(viewer.overview(viewer.include_system(query)))
                elif parsed.path == "/api/list":
                    self.send_json(
                        viewer.list_directory(
                            query.get("path", [""])[0],
                            viewer.include_system(query),
                        )
                    )
                elif parsed.path == "/api/search":
                    raw_limit = int(query.get("limit", ["200"])[0])
                    limit = max(1, min(raw_limit, MAX_SEARCH_RESULTS))
                    self.send_json(
                        viewer.search(
                            query.get("q", [""])[0],
                            viewer.include_system(query),
                            limit,
                        )
                    )
                elif parsed.path == "/api/tree":
                    depth = int(query.get("depth", ["3"])[0])
                    self.send_json(
                        viewer.tree(
                            query.get("path", [""])[0],
                            viewer.include_system(query),
                            depth,
                        )
                    )
                elif parsed.path == "/api/preview":
                    raw_rows = query.get("rows", ["25"])[0]
                    if raw_rows not in PREVIEW_ROW_OPTIONS:
                        raw_rows = "25"
                    order = query.get("order", ["head"])[0]
                    self.send_json(
                        viewer.preview(
                            query.get("path", [""])[0],
                            raw_rows,
                            order,
                            query.get("ticker", [""])[0],
                        )
                    )
                else:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            except (PermissionError, FileNotFoundError, NotADirectoryError, ValueError, RuntimeError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except OSError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, fmt: str, *args) -> None:
            print("%s - %s" % (self.address_string(), fmt % args))

        def serve_static(self, path: Path) -> None:
            path = path.resolve()
            try:
                path.relative_to(STATIC_DIR)
            except ValueError:
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return

            if not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return

            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def parse_args() -> argparse.Namespace:
    load_project_env()
    parser = argparse.ArgumentParser(description="Run a local web viewer for a MinIO data directory.")
    parser.add_argument("--root", default=os.environ.get("MINIO_ROOT", str(DEFAULT_MINIO_ROOT)))
    parser.add_argument("--source", choices=["auto", "api", "fs"], default=os.environ.get("VIEWER_SOURCE", "auto"))
    parser.add_argument("--endpoint", default=os.environ.get("MINIO_ENDPOINT", "localhost:9004"))
    parser.add_argument("--access-key", default=os.environ.get("MINIO_ROOT_USER", "minioadmin"))
    parser.add_argument("--secret-key", default=os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"))
    parser.add_argument("--bucket", default=os.environ.get("DATALAKE_BUCKET", "warehouse"))
    parser.add_argument("--secure", action="store_true", default=os.environ.get("MINIO_SECURE", "0") in {"1", "true", "yes"})
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.environ.get("PORT", "8765")), type=int)
    return parser.parse_args()


def create_viewer(args: argparse.Namespace):
    if args.source in {"api", "auto"}:
        try:
            viewer = MinioApiViewer(
                endpoint=args.endpoint,
                access_key=args.access_key,
                secret_key=args.secret_key,
                bucket=args.bucket,
                secure=args.secure,
            )
            viewer.client.bucket_exists(args.bucket)
            print(f"MinIO API: http{'s' if args.secure else ''}://{args.endpoint}/{args.bucket}")
            return viewer
        except Exception as exc:
            if args.source == "api":
                raise RuntimeError(f"Cannot connect to MinIO API: {exc}") from exc
            print(f"MinIO API unavailable, falling back to filesystem: {exc}")

    viewer = MinioViewer(Path(args.root))
    print(f"MinIO root: {viewer.root}")
    return viewer


def main() -> None:
    args = parse_args()
    viewer = create_viewer(args)
    handler = make_handler(viewer)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    print(f"Viewer URL: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping MinIO viewer.")


if __name__ == "__main__":
    main()
