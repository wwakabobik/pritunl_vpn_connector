"""Structured logging setup based on structlog with console and file output."""

import logging
import os
import sys
from types import TracebackType
from typing import Optional

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import StackInfoRenderer, TimeStamper
from structlog.stdlib import (
    ExtraAdder,
    PositionalArgumentsFormatter,
    ProcessorFormatter,
    add_log_level,
    add_logger_name,
)
from structlog.types import Processor

LOG_LEVELS: dict[str, str] = {
    "": "DEBUG",
    "uvicorn": "INFO",
    "uvicorn.access": "WARNING",
    "httpcore": "WARNING",
    "httpx": "WARNING",
    "urllib3": "WARNING",
    "asyncio": "WARNING",
}


class ConsoleFilter(logging.Filter):
    """Filter out noisy logs from chatty libraries for console output."""

    _noisy_libs = {"uvicorn", "httpcore", "httpx", "urllib3", "asyncio"}

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Allow only logs that are not from noisy libraries at lower levels.

        :param record: LogRecord to evaluate
        :type record: logging.LogRecord
        :return: True if the log should be shown
        :rtype: bool
        """
        if record.name.split(".")[0] in self._noisy_libs and record.levelno < logging.WARNING:
            return False
        return True


class FileFilter(logging.Filter):
    """Filter logs for file output based on per-library minimum levels."""

    def __init__(self, log_levels: dict[str, str]) -> None:
        """
        Initialize with per-library log level thresholds.

        :param log_levels: mapping of logger name prefix to minimum level
        :type log_levels: dict[str, str]
        """
        super().__init__()
        self.log_levels = log_levels

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Allow logs that meet the minimum level for their library.

        :param record: LogRecord to evaluate
        :type record: logging.LogRecord
        :return: True if the log should be recorded
        :rtype: bool
        """
        logger_name = record.name.split(".")[0]
        if logger_name in self.log_levels:
            target_level = int(logging.getLevelName(self.log_levels[logger_name]))
            return record.levelno >= target_level
        return True


def setup_logging(
    json_logs: bool = False,
    log_level: str = "INFO",
    log_file: str = "service.log",
) -> None:
    """
    Configure structured logging with console and file handlers.

    :param json_logs: format logs as JSON
    :type json_logs: bool
    :param log_level: minimum log level for the root logger
    :type log_level: str
    :param log_file: path to the log file
    :type log_file: str
    """
    timestamper = TimeStamper(fmt="iso")

    shared_processors: list[Processor] = [
        merge_contextvars,
        add_logger_name,
        add_log_level,
        PositionalArgumentsFormatter(),
        ExtraAdder(),
        timestamper,
        StackInfoRenderer(),
    ]

    if json_logs:
        shared_processors.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=[
            *shared_processors,
            ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    console_formatter = ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )

    file_formatter = ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(FileFilter(LOG_LEVELS))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG)
    console_handler.addFilter(ConsoleFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level.upper())
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    for name in LOG_LEVELS:
        logging.getLogger(name).setLevel(logging.DEBUG)

    def handle_exception(
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """
        Route uncaught exceptions through the root logger.

        :param exc_type: exception type
        :type exc_type: Optional[type[BaseException]]
        :param exc_val: exception value
        :type exc_val: Optional[BaseException]
        :param exc_tb: exception traceback
        :type exc_tb: Optional[TracebackType]
        """
        if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_val or KeyboardInterrupt(), exc_tb)
            return

        if exc_type is not None and exc_val is not None:
            root_logger.error("Uncaught exception", exc_info=(exc_type, exc_val, exc_tb))
        else:
            root_logger.error("Uncaught exception with missing context")

    sys.excepthook = handle_exception


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger by name.

    :param name: logger name (typically ``__name__``)
    :type name: str
    :return: configured structlog logger
    :rtype: structlog.stdlib.BoundLogger
    """
    return structlog.get_logger(name)
