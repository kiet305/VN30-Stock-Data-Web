import os
from pathlib import Path

from dotenv import load_dotenv


CONFIG_DIR = Path(__file__).resolve().parent
ETL_ROOT = CONFIG_DIR.parent
PROJECT_ROOT = ETL_ROOT.parent

# Load environment from the ETL folder first, then from the project root.
for env_path in [ETL_ROOT / ".env", PROJECT_ROOT / ".env"]:
    if env_path.exists():
        load_dotenv(env_path)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


MINIO_CONFIG = {
    "endpoint": _env("MINIO_ENDPOINT", "localhost:9004"),
    "bucket_name": _env("DATALAKE_BUCKET", "warehouse"),
    "access_key": _env("MINIO_ACCESS_KEY", _env("MINIO_ROOT_USER", "minioadmin")),
    "secret_key": _env("MINIO_SECRET_KEY", _env("MINIO_ROOT_PASSWORD", "minioadmin")),
    "secure": _env("MINIO_SECURE", "false").lower() == "true",
}

PSQL_CONFIG = {
    "host": _env("POSTGRES_HOST", "localhost"),
    "port": _env_int("POSTGRES_PORT", 5400),
    "database": _env("POSTGRES_DB", "postgres"),
    "user": _env("POSTGRES_USER", "admin"),
    "password": _env("POSTGRES_PASSWORD", "change_me"),
}
