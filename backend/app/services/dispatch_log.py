"""Structured logs for dispatch decisions.

Every dispatch attempt (accepted or rejected) emits exactly one structured
record on the ``liftbay.dispatch`` logger. Each record carries:

- ``event``: ``dispatch_assigned`` | ``dispatch_rejected``
- ``request_id``: correlates with the HTTP request (X-Request-Id)
- ``call_id``: hall call (呼梯) id
- ``car_id``: winning car id, ``None`` on rejection
- ``score``: winning score, ``None`` on rejection
- ``accepted``: bool
- ``reason``: stable machine-readable reason code

The message line repeats the same key=value pairs, so a single line is
greppable on its own and two consecutive dispatches of the same hall call
never share an identical line (their ``request_id`` differs). These logs
complement — never replace — the ``dispatch_logs`` replay table, and they
contain no passenger personal information.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

LOGGER_NAME = "liftbay.dispatch"

EVENT_ASSIGNED = "dispatch_assigned"
EVENT_REJECTED = "dispatch_rejected"

REASON_SELECTED_BEST_SCORE = "selected_best_score"
REASON_ALL_CARS_FULL = "all_cars_full"

LOG_FIELDS = ("event", "request_id", "call_id", "car_id", "score", "accepted", "reason")

logger = logging.getLogger(LOGGER_NAME)


class DispatchJsonFormatter(logging.Formatter):
    """Render dispatch records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in LOG_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_dispatch_logging() -> None:
    """Attach a JSON stdout handler to the dispatch logger; idempotent."""
    if any(getattr(h, "_liftbay_dispatch", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(DispatchJsonFormatter())
    handler._liftbay_dispatch = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def log_dispatch_result(
    *,
    request_id: str,
    call_id: int,
    car_id: int | None,
    score: float | None,
    accepted: bool,
    reason: str,
) -> None:
    """Emit one structured record for a dispatch decision."""
    event = EVENT_ASSIGNED if accepted else EVENT_REJECTED
    message = (
        f"{event} request_id={request_id} call_id={call_id} "
        f"car_id={car_id} score={score} accepted={accepted} reason={reason}"
    )
    logger.log(
        logging.INFO if accepted else logging.WARNING,
        message,
        extra={
            "event": event,
            "request_id": request_id,
            "call_id": call_id,
            "car_id": car_id,
            "score": score,
            "accepted": accepted,
            "reason": reason,
        },
    )
