import logging
import pprint
from typing import Any

logger = logging.getLogger("scraper")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _truncate_value(value: Any, max_length: int) -> Any:
    if isinstance(value, str) and len(value) > max_length:
        return f"{value[:max_length]}... [{len(value)} chars total]"
    if isinstance(value, dict):
        return {key: _truncate_value(item, max_length) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_length) for item in value]
    return value


def log_pretty(message: str, data: Any, truncate: int = 300) -> None:
    safe_data = _truncate_value(data, truncate)
    formatted = pprint.pformat(safe_data, sort_dicts=False, width=100)
    logger.info("%s\n%s", message, formatted)
