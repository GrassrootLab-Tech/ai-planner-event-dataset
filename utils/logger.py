import contextvars
import logging
import pprint
from typing import Any

_log_stage = contextvars.ContextVar("log_stage", default="pipeline")

logger = logging.getLogger("pipeline")

COMMAND_LOG_STAGES: dict[str, str] = {
    "scrape": "scraper",
    "chunk": "chunker",
    "classify": "usability",
    "tag": "ai_tagging",
    "embed": "embedding",
}


class _StageFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.stage = _log_stage.get()
        return True


def set_log_stage(stage: str) -> None:
    _log_stage.set(stage)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_StageFilter())
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(stage)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


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
