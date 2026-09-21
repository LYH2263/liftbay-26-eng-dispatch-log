"""派工决策的结构化日志。

每次派工请求在“接受”或“拒绝”时各输出一条独立的 JSON 日志记录，
字段固定、可检索，并通过 request_id 与一次请求关联。

注意：日志只用于观测，不替代 dispatch_logs 回放表；回放仍写库。
不要在此记录乘客隐私之外的额外个人信息（只含呼梯/轿厢编号与评分等运营字段）。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger("liftbay.dispatch")


def new_request_id() -> str:
    """一次派工请求一个唯一 ID（两次派工同一呼梯也各不相同）。"""
    return uuid.uuid4().hex


def _emit(
    *,
    event: str,
    request_id: str,
    call_id: int,
    car_id: int | None,
    score: float | None,
    outcome: str,
    reason: str,
) -> None:
    payload: dict[str, Any] = {
        "event": event,
        "request_id": request_id,
        "call_id": call_id,
        # 拒绝时没有胜者轿厢，序列化为 null 而非省略，字段始终存在。
        "car_id": car_id,
        "score": score,
        "outcome": outcome,
        "reason": reason,
    }
    # extra 上的结构化字段在 JSON 以外的 handler 下也可被日志平台提取；
    # 消息体本身是一行 JSON，caplog 可直接按字段名断言。
    logger.info(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        extra={"dispatch": payload},
    )


def log_accepted(
    *, request_id: str, call_id: int, car_id: int, score: float, reason: str = "ok"
) -> None:
    _emit(
        event="dispatch_decision",
        request_id=request_id,
        call_id=call_id,
        car_id=car_id,
        score=score,
        outcome="accepted",
        reason=reason,
    )


def log_rejected(
    *, request_id: str, call_id: int, score: float | None, reason: str
) -> None:
    _emit(
        event="dispatch_decision",
        request_id=request_id,
        call_id=call_id,
        car_id=None,
        score=score,
        outcome="rejected",
        reason=reason,
    )
