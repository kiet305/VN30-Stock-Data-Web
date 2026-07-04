from dagster import IOManager, OutputContext, InputContext
from minio import Minio
import pandas as pd
import os
import tempfile
import re


class MinIOIOManager(IOManager):
    def __init__(self, config):
        self._config = config
        self.client = Minio(
            config["endpoint"],
            access_key=config["access_key"],
            secret_key=config["secret_key"],
            secure=config.get("secure", False),
            region="us-east-1",
        )
    
    def _resolve_object_path(self, asset_key, partition_key=None) -> str:
        """
        asset_key.path = [layer, schema?, table]
        """
        base = self._resolve_base_path(asset_key)

        if partition_key:
            return f"{base}/{partition_key}.parquet"

        return f"{base}/data.parquet"

    def _resolve_base_path(self, asset_key) -> str:
        """
        Resolve the logical asset prefix without a file extension.
        """
        parts = asset_key.path

        layer = parts[0]
        table = parts[-1]
        prefix = f"{layer}_"
        if table.startswith(prefix):
            table = table[len(prefix):]

        schema = "/".join(parts[1:-1]) if len(parts) > 2 else ""

        return f"{layer}/{schema}/{table}".replace("//", "/")

    def _legacy_unpartitioned_object_path(self, asset_key) -> str:
        return f"{self._resolve_base_path(asset_key)}.parquet"

    def _resolve_asset_file_path(self, asset_key, relative_path: str) -> str:
        relative_path = relative_path.replace("\\", "/").lstrip("/")
        return f"{self._resolve_base_path(asset_key)}/{relative_path}"

    def _is_partition_key(self, key: str) -> bool:
        return bool(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", key)
            or re.fullmatch(r"\d{4}-Q[1-4]", key)
        )

    def _tmp_file(self, asset_key, partition_key=None):
        name = asset_key.path[-1]
        suffix = f"_{partition_key}" if partition_key else ""
        return os.path.join(
            tempfile.gettempdir(),
            f"{name}{suffix}.parquet",
        )

    # =====================================================
    # 🔹 OUTPUT
    # =====================================================
    def handle_output(self, context: OutputContext, obj: pd.DataFrame):
        if obj is None:
            context.log.info("No data to write")
            return

        partition_key = context.partition_key if context.has_partition_key else None

        object_name = self._resolve_object_path(
            context.asset_key, partition_key
        )
        tmp_path = self._tmp_file(context.asset_key, partition_key)

        obj.to_parquet(tmp_path, index=False)

        self.client.fput_object(
            bucket_name=self._config["bucket_name"],
            object_name=object_name,
            file_path=tmp_path,
            content_type="application/parquet",
        )

        context.log.info(f"Written to MinIO: {object_name}")
        os.remove(tmp_path)

    # =====================================================
    # 🔹 INPUT
    # =====================================================
    def _load_unpartitioned(self, asset_key) -> pd.DataFrame:
        object_name = self._resolve_object_path(asset_key, partition_key=None)
        tmp_path = self._tmp_file(asset_key, None)

        try:
            self.client.fget_object(
                bucket_name=self._config["bucket_name"],
                object_name=object_name,
                file_path=tmp_path,
            )
        except Exception:
            legacy_object_name = self._legacy_unpartitioned_object_path(asset_key)
            try:
                self.client.fget_object(
                    bucket_name=self._config["bucket_name"],
                    object_name=legacy_object_name,
                    file_path=tmp_path,
                )
            except Exception:
                raise FileNotFoundError(object_name)

        df = pd.read_parquet(tmp_path)
        os.remove(tmp_path)
        return df

    def load_input(self, context: InputContext) -> pd.DataFrame:
        metadata = context.metadata or {}
        load_all_partitions = metadata.get("load_all_partitions", False)
        load_latest_partition = metadata.get("load_latest_partition", False)

        if load_latest_partition:
            partitions = metadata.get("partitions") or self.list_partitions(
                context.asset_key
            )
            if partitions:
                partition_key = sorted(partitions)[-1]
                df = self.load_partition(context.asset_key, partition_key)
                df["_partition_key"] = partition_key
                return df

            if metadata.get("allow_unpartitioned_fallback", False):
                return self._load_unpartitioned(context.asset_key)

            raise FileNotFoundError(
                f"No partitions found for asset {context.asset_key}"
            )

        # ==============================
        # CASE 3: partitioned → unpartitioned (merge)
        # PHẢI ƯU TIÊN
        # ==============================
        if load_all_partitions:
            partitions = metadata.get("partitions") or self.list_partitions(
                context.asset_key
            )

            dfs = []
            for pk in sorted(partitions):
                try:
                    df = self.load_partition(context.asset_key, pk)
                    df["_partition_key"] = pk
                    dfs.append(df)
                except FileNotFoundError:
                    continue

            if not dfs:
                if metadata.get("allow_unpartitioned_fallback", False):
                    return self._load_unpartitioned(context.asset_key)
                raise FileNotFoundError(
                    f"No partitions found for asset {context.asset_key}"
                )

            return pd.concat(dfs, ignore_index=True)

        # ==============================
        # CASE 2: unpartitioned asset
        # ==============================
        if not context.has_partition_key:
            return self._load_unpartitioned(context.asset_key)

        # ==============================
        # CASE 1: partitioned → partitioned
        # + fallback to unpartitioned
        # ==============================
        try:
            return self.load_partition(
                context.asset_key, context.partition_key
            )
        except FileNotFoundError:
            if not metadata.get("allow_unpartitioned_fallback", False):
                raise FileNotFoundError(
                    f"No partition '{context.partition_key}' "
                    f"for asset {context.asset_key}"
                )

            try:
                df = self._load_unpartitioned(context.asset_key)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"No partition '{context.partition_key}' "
                    f"and no unpartitioned file for asset {context.asset_key}"
                )
            df["_partition_key"] = context.partition_key
            return df

            # fallback: load unpartitioned asset
            object_name = self._resolve_object_path(
                context.asset_key, partition_key=None
            )
            tmp_path = self._tmp_file(context.asset_key, None)

            try:
                self.client.fget_object(
                    bucket_name=self._config["bucket_name"],
                    object_name=object_name,
                    file_path=tmp_path,
                )
            except Exception:
                legacy_object_name = self._legacy_unpartitioned_object_path(
                    context.asset_key
                )
                try:
                    self.client.fget_object(
                        bucket_name=self._config["bucket_name"],
                        object_name=legacy_object_name,
                        file_path=tmp_path,
                    )
                    object_name = legacy_object_name
                except Exception:
                    raise FileNotFoundError(
                        f"No partition '{context.partition_key}' "
                        f"and no unpartitioned file for asset {context.asset_key}"
                    )

            df = pd.read_parquet(tmp_path)
            os.remove(tmp_path)

            # optional: gắn partition_key hiện tại
            df["_partition_key"] = context.partition_key
            return df


    # =====================================================
    # 🔹 PARTITION HELPERS
    # =====================================================
    def list_partitions(self, asset_key):
        prefix = self._resolve_base_path(asset_key) + "/"

        objects = self.client.list_objects(
            self._config["bucket_name"],
            prefix=prefix,
            recursive=True,
        )

        partitions = []
        for obj in objects:
            if not obj.object_name.endswith(".parquet"):
                continue
            if obj.object_name.endswith("/data.parquet"):
                continue

            relative_name = obj.object_name.removeprefix(prefix)
            if "/" in relative_name:
                continue

            partition_key = relative_name.replace(".parquet", "")
            if self._is_partition_key(partition_key):
                partitions.append(partition_key)

        return sorted(partitions)

    def load_partition(self, asset_key, partition_key) -> pd.DataFrame:
        object_name = self._resolve_object_path(asset_key, partition_key)
        tmp_path = self._tmp_file(asset_key, partition_key)

        try:
            self.client.fget_object(
                self._config["bucket_name"],
                object_name,
                tmp_path,
            )
        except Exception:
            raise FileNotFoundError(object_name)

        df = pd.read_parquet(tmp_path)
        os.remove(tmp_path)
        return df
    
    def write_partition(self, asset_key, partition_key, df: pd.DataFrame):
        base_path = self._resolve_base_path(asset_key)
        object_name = f"{base_path}/{partition_key}.parquet"

        tmp_file = os.path.join(
            tempfile.gettempdir(),
            f"{asset_key.path[-1]}_{partition_key}.parquet"
        )

        df.to_parquet(tmp_file, index=False)

        self.client.fput_object(
            bucket_name=self._config["bucket_name"],
            object_name=object_name,
            file_path=tmp_file,
            content_type="application/parquet",
        )

        os.remove(tmp_file)

    def load_asset_file(self, asset_key, relative_path: str) -> pd.DataFrame:
        object_name = self._resolve_asset_file_path(asset_key, relative_path)
        tmp_path = self._tmp_file(asset_key, relative_path.replace("/", "_"))

        try:
            self.client.fget_object(
                self._config["bucket_name"],
                object_name,
                tmp_path,
            )
        except Exception:
            raise FileNotFoundError(object_name)

        df = pd.read_parquet(tmp_path)
        os.remove(tmp_path)
        return df

    def write_asset_file(self, asset_key, relative_path: str, df: pd.DataFrame):
        object_name = self._resolve_asset_file_path(asset_key, relative_path)
        tmp_file = self._tmp_file(asset_key, relative_path.replace("/", "_"))

        df.to_parquet(tmp_file, index=False)

        self.client.fput_object(
            bucket_name=self._config["bucket_name"],
            object_name=object_name,
            file_path=tmp_file,
            content_type="application/parquet",
        )

        os.remove(tmp_file)

    def asset_file_exists(self, asset_key, relative_path: str) -> bool:
        object_name = self._resolve_asset_file_path(asset_key, relative_path)
        try:
            self.client.stat_object(self._config["bucket_name"], object_name)
            return True
        except Exception:
            return False

    def list_asset_files(self, asset_key, suffix: str = ".parquet") -> list[str]:
        prefix = self._resolve_base_path(asset_key) + "/"
        objects = self.client.list_objects(
            self._config["bucket_name"],
            prefix=prefix,
            recursive=True,
        )

        files = []
        for obj in objects:
            if suffix and not obj.object_name.endswith(suffix):
                continue

            relative_name = obj.object_name.removeprefix(prefix)
            if not relative_name or relative_name == "data.parquet":
                continue

            stem = relative_name[:-len(".parquet")] if relative_name.endswith(".parquet") else relative_name
            if self._is_partition_key(stem):
                continue

            files.append(relative_name)

        return sorted(files)
