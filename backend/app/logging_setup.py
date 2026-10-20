"""JSON logs with request and run ids. Every line passes through redact()."""

import json
import logging
from contextvars import ContextVar

from .config import redact

request_id: ContextVar[str] = ContextVar("request_id", default="-")
run_id: ContextVar[str] = ContextVar("run_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                 "logger": record.name, "request_id": request_id.get(), "run_id": run_id.get(),
                 "msg": record.getMessage()}
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(entry, ensure_ascii=False))


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
