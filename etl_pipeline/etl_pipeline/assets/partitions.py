from datetime import date, datetime, timedelta, timezone

from dagster import StaticPartitionsDefinition


VN_TZ = timezone(timedelta(hours=7))


def today_vn() -> date:
    return datetime.now(VN_TZ).date()


def previous_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


PIPELINE_START_DATE = date(2026, 6, 29)
PIPELINE_ANCHOR_DATE = PIPELINE_START_DATE
CURRENT_DATE = today_vn()
PRICE_1D_HISTORY_START_DATE = date(2020, 6, 1)
PRICE_1D_START_DATE = PIPELINE_START_DATE
PRICE_1D_LAST_DATE = previous_weekday(CURRENT_DATE)


def week_start_partition_keys(start_date: date, end_date: date) -> list[str]:
    current = start_date - timedelta(days=start_date.weekday())
    if current < start_date:
        current += timedelta(days=7)

    keys = []
    while current <= end_date:
        keys.append(current.isoformat())
        current += timedelta(days=7)
    return keys


def month_start_partition_keys(start_date: date, end_date: date) -> list[str]:
    current = start_date.replace(day=1)
    end_month = end_date.replace(day=1)

    keys = []
    while current <= end_month:
        keys.append(current.isoformat())
        year = current.year + (current.month // 12)
        month = current.month % 12 + 1
        current = current.replace(year=year, month=month)
    return keys

def weekday_partition_keys(start_date: date, end_date: date) -> list[str]:
    keys = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            keys.append(current.isoformat())
        current += timedelta(days=1)
    return keys


price_1d_daily = StaticPartitionsDefinition(
    weekday_partition_keys(PRICE_1D_START_DATE, PRICE_1D_LAST_DATE)
)
bronze_price_1d_refresh_partitions = price_1d_daily


company_info_weekly_snapshot_partitions = StaticPartitionsDefinition(
    week_start_partition_keys(PIPELINE_START_DATE, CURRENT_DATE)
)
company_info_monthly_snapshot_partitions = StaticPartitionsDefinition(
    month_start_partition_keys(PIPELINE_START_DATE, CURRENT_DATE)
)

# Backward-compatible aliases for existing imports.
company_info_weekly = company_info_weekly_snapshot_partitions
company_overview_monthly = company_info_monthly_snapshot_partitions

company_events_weekly = company_info_weekly


def company_info_partitions_def(info_type: str):
    if info_type == "overview":
        return company_overview_monthly
    if info_type in {
        "events",
        "officers",
        "shareholders",
    }:
        return company_info_weekly
    return None
