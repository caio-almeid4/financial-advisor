import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_SKIP_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class _JsonFormatter(logging.Formatter):
    """Emits one JSON object per log record (NDJSON)."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "lvl": record.levelname,
            "msg": record.message,
        }
        for key, val in vars(record).items():
            if key not in _SKIP_ATTRS:
                entry[key] = val
        return json.dumps(entry, ensure_ascii=False, default=str)


_logger: logging.Logger | None = None


def setup_logging(log_dir: Path, run_id: str) -> logging.Logger:
    global _logger

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{run_id}.ndjson"

    logger = logging.getLogger("xp_advisor")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console — warnings and above only (pipeline prints already handle INFO)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(ch)

    # File — full structured JSON
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_JsonFormatter())
    logger.addHandler(fh)

    logger.info("logging_initialized", extra={"log_path": str(log_path), "run_id": run_id})

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    return _logger or logging.getLogger("xp_advisor")
