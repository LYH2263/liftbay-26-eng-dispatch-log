"""Dispatch decision logging: structured fields, request correlation, replay intact."""

import json
import logging
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SEED_ON_EMPTY", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Building, CallTicket, DispatchLog, ElevatorCar
from app.services.dispatch_log import (
    EVENT_ASSIGNED,
    EVENT_REJECTED,
    LOGGER_NAME,
    REASON_ALL_CARS_FULL,
    REASON_SELECTED_BEST_SCORE,
    DispatchJsonFormatter,
    log_dispatch_result,
)

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(bind=engine)


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        yield session
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_car(db, *, load=0, capacity=10):
    building = Building(name="测试楼", floors=20)
    db.add(building)
    db.flush()
    car = ElevatorCar(
        building_id=building.id,
        label="T1",
        floor=1,
        direction="idle",
        load=load,
        capacity=capacity,
    )
    db.add(car)
    db.commit()
    return building, car


def _create_call(client, building_id, floor=3, passengers=2):
    resp = client.post(
        "/api/calls",
        json={
            "building_id": building_id,
            "floor": floor,
            "direction": "up",
            "passengers": passengers,
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def _dispatch_records(caplog, event):
    return [r for r in caplog.records if getattr(r, "event", None) == event]


def test_dispatch_assigned_emits_structured_log(client, db_session, caplog):
    building, car = _seed_car(db_session)
    call_id = _create_call(client, building.id)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/dispatch", json={"call_id": call_id})

    assert resp.status_code == 200
    records = _dispatch_records(caplog, EVENT_ASSIGNED)
    assert len(records) == 1
    rec = records[0]
    assert rec.request_id == resp.headers["x-request-id"]
    assert rec.call_id == call_id
    assert rec.car_id == car.id
    assert isinstance(rec.score, float)
    assert rec.accepted is True
    assert rec.reason == REASON_SELECTED_BEST_SCORE
    # 日志不替代回放表：DispatchLog 仍写库
    log_row = db_session.query(DispatchLog).filter_by(call_id=call_id).one()
    assert log_row.car_id == car.id


def test_dispatch_rejected_when_full_emits_structured_log(client, db_session, caplog):
    building, _car = _seed_car(db_session, load=8, capacity=8)  # 满员
    call_id = _create_call(client, building.id, passengers=1)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/dispatch", json={"call_id": call_id})

    assert resp.status_code == 409
    records = _dispatch_records(caplog, EVENT_REJECTED)
    assert len(records) == 1
    rec = records[0]
    assert rec.levelno == logging.WARNING
    assert rec.request_id == resp.headers["x-request-id"]
    assert rec.call_id == call_id
    assert rec.car_id is None
    assert rec.score is None
    assert rec.accepted is False
    assert rec.reason == REASON_ALL_CARS_FULL
    # 拒绝同样写回放表
    log_row = db_session.query(DispatchLog).filter_by(call_id=call_id).one()
    assert log_row.car_id is None


def test_consecutive_dispatches_have_distinct_searchable_lines(client, db_session, caplog):
    building, _car = _seed_car(db_session)
    call_ids = [_create_call(client, building.id, floor=3), _create_call(client, building.id, floor=5)]

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        for call_id in call_ids:
            assert client.post("/api/dispatch", json={"call_id": call_id}).status_code == 200

    records = _dispatch_records(caplog, EVENT_ASSIGNED)
    assert len(records) == 2
    first, second = records[0].getMessage(), records[1].getMessage()
    assert first != second
    assert records[0].request_id != records[1].request_id
    for rec, call_id in zip(records, call_ids):
        assert f"call_id={call_id}" in rec.getMessage()
        assert rec.request_id in rec.getMessage()


def test_same_call_dispatched_twice_lines_are_distinguishable(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        log_dispatch_result(
            request_id="req-a", call_id=7, car_id=3, score=72.0,
            accepted=True, reason=REASON_SELECTED_BEST_SCORE,
        )
        log_dispatch_result(
            request_id="req-b", call_id=7, car_id=3, score=72.0,
            accepted=True, reason=REASON_SELECTED_BEST_SCORE,
        )
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 2
    assert messages[0] != messages[1]
    assert "req-a" in messages[0] and "req-b" in messages[1]


def test_json_formatter_outputs_parseable_fields(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        log_dispatch_result(
            request_id="req-1", call_id=7, car_id=None, score=None,
            accepted=False, reason=REASON_ALL_CARS_FULL,
        )
    payload = json.loads(DispatchJsonFormatter().format(caplog.records[-1]))
    assert payload["event"] == EVENT_REJECTED
    assert payload["request_id"] == "req-1"
    assert payload["call_id"] == 7
    assert payload["car_id"] is None
    assert payload["score"] is None
    assert payload["accepted"] is False
    assert payload["reason"] == REASON_ALL_CARS_FULL
