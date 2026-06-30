import logging
import os
import sys
from datetime import date

DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_log_file: str | None = None
_trace_collector: "ExceptionTraceCollector | None" = None


class ExceptionTraceCollector(logging.Handler):
    """Captures ERROR+ log records (with full exception traces) for error emails."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._entries: list[str] = []
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._entries.append(self.format(record))
        except Exception:
            self.handleError(record)

    def get_entries(self) -> list[str]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()


def get_exception_traces() -> list[str]:
    if _trace_collector is None:
        return []
    return _trace_collector.get_entries()


def clear_exception_traces() -> None:
    if _trace_collector is not None:
        _trace_collector.clear()


def get_log_file() -> str | None:
    return _log_file


def apply_log_timestamp(path: str, run_date: date | None = None) -> str:
    run_date = run_date or date.today()
    root, ext = os.path.splitext(path)
    return f"{root}-{run_date.isoformat()}{ext}"


def parse_log_level(level_name: str) -> int:
    normalized = level_name.upper()
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    if normalized not in levels:
        available = ", ".join(levels)
        raise ValueError(f"Invalid log level: {level_name!r}. Use one of: {available}")
    return levels[normalized]


def setup_logging(
    config: dict,
    *,
    log_file: str | None = None,
    log_level: str | None = None,
    log_timestamp: bool | None = None,
) -> None:
    global _log_file, _trace_collector

    log_cfg = config.get("logging", {})
    _log_file = log_file if log_file is not None else log_cfg.get("file")
    timestamp = (
        log_timestamp
        if log_timestamp is not None
        else log_cfg.get("timestamp", False)
    )
    if _log_file and timestamp:
        _log_file = apply_log_timestamp(_log_file)
    level_name = (
        log_level if log_level is not None else log_cfg.get("level", DEFAULT_LOG_LEVEL)
    )
    level = parse_log_level(level_name)
    log_to_console = log_cfg.get("console", True)

    handlers: list[logging.Handler] = []
    if _log_file:
        log_dir = os.path.dirname(_log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(_log_file, mode="a", encoding="utf-8"))
    if log_to_console:
        handlers.append(logging.StreamHandler(sys.stdout))

    _trace_collector = ExceptionTraceCollector()
    handlers.append(_trace_collector)

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=handlers,
        force=True,
    )

    logging.getLogger(__name__).debug(
        "Logging configured: file=%s level=%s console=%s",
        _log_file,
        logging.getLevelName(level),
        log_to_console,
    )
