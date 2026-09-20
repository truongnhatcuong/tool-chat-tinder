"""Sanitized logging module ensuring no passwords, tokens, or OTPs leak into logs."""
import logging
import re
import sys
from pathlib import Path
from typing import Callable

LOGS_DIR = Path(__file__).resolve().parent.parent / "data"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "app.log"

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|bearer|authorization|token|secret)[\s:=]+['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?"),
    re.compile(r"(?i)(password|passwd|pwd)[\s:=]+['\"]?([^\s,;]+)['\"]?"),
    re.compile(r"(?i)(otp|code)[\s:=]+['\"]?(\d{4,8})['\"]?"),
    re.compile(r"(?i)(cookie)[\s:=]+['\"]?([^\n\r]+)['\"]?"),
]


class RedactingFormatter(logging.Formatter):
    """Custom logging formatter that scrubs sensitive data from log records."""

    def format(self, record: logging.LogRecord) -> str:
        orig = super().format(record)
        redacted = orig
        for pattern in SENSITIVE_PATTERNS:
            redacted = pattern.sub(r"\1=***REDACTED***", redacted)
        return redacted


_gui_log_callbacks: list[Callable[[str], None]] = []


def register_gui_log_callback(callback: Callable[[str], None]) -> None:
    """Register callback to broadcast logs to GUI console widget."""
    if callback not in _gui_log_callbacks:
        _gui_log_callbacks.append(callback)


class GuiLogHandler(logging.Handler):
    """Handler broadcasting log messages to GUI subscribers."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            for cb in _gui_log_callbacks:
                try:
                    cb(msg)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)


def setup_logger(name: str = "tinder_ai", level: int = logging.INFO) -> logging.Logger:
    """Configure and return the application logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.handlers:
        formatter = RedactingFormatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # Console handler
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
        # File handler
        try:
            fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as e:
            print(f"Warning: Could not initialize file handler: {e}")
            
        # GUI handler
        gh = GuiLogHandler()
        gh.setLevel(level)
        gh.setFormatter(formatter)
        logger.addHandler(gh)

    return logger


logger = setup_logger()
