from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "dblm.log"
LOGGER_NAME = "dblm"


class InMemoryLogHandler(logging.Handler):
    """
    Logging handler that keeps the most recent log lines in memory for the UI.
    """

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self.capacity = capacity
        self._records: list[str] = []
        self._lock = RLock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return

        with self._lock:
            self._records.append(message)
            if len(self._records) > self.capacity:
                overflow = len(self._records) - self.capacity
                del self._records[:overflow]

    def clear(self) -> int:
        with self._lock:
            cleared = len(self._records)
            self._records.clear()
            return cleared

    def get_lines(self) -> list[str]:
        with self._lock:
            return list(self._records)

    def tail(self, limit: int = 200) -> list[str]:
        with self._lock:
            if limit <= 0:
                return []
            return list(self._records[-limit:])


_memory_handler: InMemoryLogHandler | None = None
_configured: bool = False
_config_lock = RLock()


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure_logging(
    *,
    log_dir: str | Path = DEFAULT_LOG_DIR,
    log_file: str | Path = DEFAULT_LOG_FILE,
    level: int = logging.INFO,
    memory_capacity: int = 2000,
    file_max_bytes: int = 1_048_576,
    file_backup_count: int = 3,
    force: bool = False,
) -> logging.Logger:
    """
    Configure DBLM logging once and return the root DBLM logger.
    """
    global _memory_handler, _configured

    with _config_lock:
        logger = logging.getLogger(LOGGER_NAME)

        if _configured and not force:
            return logger

        log_dir_path = Path(log_dir)
        if not log_dir_path.is_absolute():
            log_dir_path = PROJECT_ROOT / log_dir_path
        log_dir_path.mkdir(parents=True, exist_ok=True)

        log_file_path = Path(log_file)
        if not log_file_path.is_absolute():
            log_file_path = log_dir_path / log_file_path.name

        logger.setLevel(level)
        logger.propagate = False

        if force:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        formatter = _build_formatter()

        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=file_max_bytes,
            backupCount=file_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

        memory_handler = InMemoryLogHandler(capacity=memory_capacity)
        memory_handler.setLevel(level)
        memory_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(memory_handler)

        _memory_handler = memory_handler
        _configured = True

        logger.info("Logging configured. Log file: %s", log_file_path)
        return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Return a logger inside the DBLM namespace.

    Examples:
        get_logger() -> "dblm"
        get_logger("ui.dashboard") -> "dblm.ui.dashboard"
    """
    base = configure_logging()

    if not name:
        return base

    clean_name = name.strip(". ")
    if not clean_name:
        return base

    if clean_name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(clean_name)

    return logging.getLogger(f"{LOGGER_NAME}.{clean_name}")


def get_memory_handler() -> InMemoryLogHandler:
    """
    Return the configured in-memory log handler.
    """
    configure_logging()
    assert _memory_handler is not None
    return _memory_handler


def get_log_buffer() -> list[str]:
    """
    Return all currently buffered log lines.
    """
    return get_memory_handler().get_lines()


def tail_log_buffer(limit: int = 200) -> list[str]:
    """
    Return the last `limit` buffered log lines.
    """
    return get_memory_handler().tail(limit=limit)


def clear_log_buffer() -> int:
    """
    Clear only the in-memory UI log buffer and return how many lines were removed.
    """
    handler = get_memory_handler()
    return handler.clear()


def append_log_line(
    message: str,
    *,
    level: int = logging.INFO,
    logger_name: str = "ui",
) -> None:
    """
    Append a log line through the standard logging pipeline.
    """
    logger = get_logger(logger_name)
    logger.log(level, message)


def read_log_file(log_file: str | Path = DEFAULT_LOG_FILE) -> list[str]:
    """
    Read the persistent log file into a list of lines.
    """
    path = Path(log_file)
    if not path.is_absolute():
        path = DEFAULT_LOG_DIR / path.name

    if not path.exists():
        return []

    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def tail_log_file(log_file: str | Path = DEFAULT_LOG_FILE, limit: int = 200) -> list[str]:
    """
    Return the last `limit` lines from the persistent log file.
    """
    lines = read_log_file(log_file)
    if limit <= 0:
        return []
    return lines[-limit:]


def iter_combined_logs(
    *,
    include_memory: bool = True,
    include_file: bool = False,
    file_limit: int = 200,
    memory_limit: int = 200,
) -> list[str]:
    """
    Return logs from one or both sources for the UI.
    """
    lines: list[str] = []

    if include_file:
        lines.extend(tail_log_file(limit=file_limit))

    if include_memory:
        memory_lines = tail_log_buffer(limit=memory_limit)
        if include_file and lines and memory_lines:
            lines.append("--- in-memory buffer ---")
        lines.extend(memory_lines)

    return lines


def log_exception(
    message: str,
    *,
    logger_name: str = "errors",
    exc_info: bool = True,
) -> None:
    """
    Helper to log exceptions consistently.
    """
    logger = get_logger(logger_name)
    logger.error(message, exc_info=exc_info)
