from hunttech_bot_common.services.db_config_service import DbConfigService
from hunttech_bot_common.services.db_setup import (
    DbTestResult,
    format_db_config,
    make_db_url,
    test_db_connection,
    validate_port,
)
from hunttech_bot_common.services.rates import (
    EMPLOYMENT_BOTH,
    EMPLOYMENT_GPH,
    EMPLOYMENT_IP,
    HOURLY_MONTH_HOURS,
    HOURLY_ROUND_STEP,
    OUTSTAFFING_RATES_TABLE,
    build_candidate_rates_report,
    calculate_candidate_rate,
    hourly_from_monthly,
    lookup_outstaffing_rate,
    pick_employment_rates,
)

__all__ = [
    "DbConfigService",
    "DbTestResult",
    "format_db_config",
    "make_db_url",
    "test_db_connection",
    "validate_port",
    # Расчёт ставок (стандарт HuntTech)
    "OUTSTAFFING_RATES_TABLE",
    "HOURLY_MONTH_HOURS",
    "HOURLY_ROUND_STEP",
    "EMPLOYMENT_GPH",
    "EMPLOYMENT_IP",
    "EMPLOYMENT_BOTH",
    "hourly_from_monthly",
    "pick_employment_rates",
    "build_candidate_rates_report",
    "lookup_outstaffing_rate",
    "calculate_candidate_rate",
]
