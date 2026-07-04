import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Settings(BaseSettings):
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5400, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="postgres", alias="POSTGRES_DB")
    postgres_user: str = Field(default="admin", alias="POSTGRES_USER")
    postgres_password: str = Field(default="change_me", alias="POSTGRES_PASSWORD")
    postgres_schema: str = Field(default="warehouse", alias="POSTGRES_SCHEMA")
    postgres_table: str = Field(default="warehouse_prices_1d", alias="POSTGRES_TABLE")
    postgres_ticker_column: str = Field(default="ticker", alias="POSTGRES_TICKER_COLUMN")
    postgres_date_column: str = Field(default="date", alias="POSTGRES_DATE_COLUMN")
    postgres_open_column: str = Field(default="open", alias="POSTGRES_OPEN_COLUMN")
    postgres_high_column: str = Field(default="high", alias="POSTGRES_HIGH_COLUMN")
    postgres_low_column: str = Field(default="low", alias="POSTGRES_LOW_COLUMN")
    postgres_close_column: str = Field(default="close", alias="POSTGRES_CLOSE_COLUMN")
    postgres_volume_column: str = Field(default="volume", alias="POSTGRES_VOLUME_COLUMN")
    cors_origins: str = Field(
        default=(
            "http://localhost:4173,http://127.0.0.1:4173,"
            "http://localhost:5173,http://127.0.0.1:5173"
        ),
        alias="CORS_ORIGINS",
    )
    tradingagents_reports_dir: str | None = Field(default=None, alias="TRADINGAGENTS_REPORTS_DIR")
    tradingagents_logs_dir: str | None = Field(default=None, alias="TRADINGAGENTS_LOGS_DIR")
    tradingagents_source_dir: str | None = Field(default=None, alias="TRADINGAGENTS_SOURCE_DIR")
    tradingagents_analysis_date: str | None = Field(default=None, alias="TRADINGAGENTS_ANALYSIS_DATE")
    tradingagents_provider: str = Field(default="openai", alias="TRADINGAGENTS_PROVIDER")
    tradingagents_model: str = Field(default="gpt-4.1", alias="TRADINGAGENTS_MODEL")
    tradingagents_max_steps: int = Field(default=8, alias="TRADINGAGENTS_MAX_STEPS")
    tradingagents_look_back_days: int = Field(default=7, alias="TRADINGAGENTS_LOOK_BACK_DAYS")
    tradingagents_debate_rounds: int = Field(default=2, alias="TRADINGAGENTS_DEBATE_ROUNDS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def allowed_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        origin_set = set(origins)
        for origin in list(origins):
            if origin.startswith("http://localhost:"):
                origin_set.add(origin.replace("http://localhost:", "http://127.0.0.1:", 1))
            elif origin.startswith("http://127.0.0.1:"):
                origin_set.add(origin.replace("http://127.0.0.1:", "http://localhost:", 1))
        return sorted(origin_set)

    @property
    def qualified_table(self) -> str:
        return f"{self._validate_identifier(self.postgres_schema)}.{self._validate_identifier(self.postgres_table)}"

    @property
    def analysis_report_dirs(self) -> list[Path]:
        config_path = Path(__file__).resolve()
        project_root = config_path.parents[3] if len(config_path.parents) > 3 else config_path.parents[-1]
        reports_dir = (
            Path(self.tradingagents_reports_dir)
            if self.tradingagents_reports_dir
            else project_root / "TradingAgents" / "reports"
        )
        logs_dir = (
            Path(self.tradingagents_logs_dir)
            if self.tradingagents_logs_dir
            else Path.home() / ".tradingagents" / "logs"
        )
        return [reports_dir, logs_dir]

    @property
    def tradingagents_source_path(self) -> Path | None:
        if self.tradingagents_source_dir:
            return Path(self.tradingagents_source_dir)

        config_path = Path(__file__).resolve()
        project_root = config_path.parents[3] if len(config_path.parents) > 3 else config_path.parents[-1]
        candidate = project_root / "TradingAgents"
        return candidate if candidate.exists() else None

    @property
    def columns(self) -> dict[str, str]:
        return {
            "ticker": self._validate_identifier(self.postgres_ticker_column),
            "date": self._validate_identifier(self.postgres_date_column),
            "open": self._validate_identifier(self.postgres_open_column),
            "high": self._validate_identifier(self.postgres_high_column),
            "low": self._validate_identifier(self.postgres_low_column),
            "close": self._validate_identifier(self.postgres_close_column),
            "volume": self._validate_identifier(self.postgres_volume_column),
        }

    @staticmethod
    def _validate_identifier(value: str) -> str:
        if not IDENTIFIER_PATTERN.match(value):
            raise ValueError(f"Định danh PostgreSQL không hợp lệ: {value}")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
