"""结构化派工日志测例：接受 / 满员拒绝 / 同一呼梯连续两次派工。

用 SQLite 内存库覆盖 get_db，caplog 捕获 "liftbay.dispatch" logger，
断言每条日志都是可解析的 JSON 且关键字段齐全。
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Building, CallTicket, DispatchLog, ElevatorCar

DECISION_LOGGER = "liftbay.dispatch"
EXPECTED_KEYS = {
    "event",
    "request_id",
    "call_id",
    "car_id",
    "score",
    "outcome",
    "reason",
}


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass  # 测试内共用同一 session，关闭交给 fixture

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield db
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    return TestClient(app)


@pytest.fixture()
def decision_logs(caplog):
    caplog.set_level(logging.INFO, logger=DECISION_LOGGER)
    return caplog


def decision_records(caplog) -> list[dict]:
    records = []
    for rec in caplog.records:
        if rec.name != DECISION_LOGGER:
            continue
        payload = json.loads(rec.getMessage())
        records.append(payload)
    return records


def _make_building_and_car(db, *, load: int, capacity: int = 10) -> tuple[int, int]:
    b = Building(name="测试楼", floors=18)
    db.add(b)
    db.flush()
    car = ElevatorCar(
        building_id=b.id, label="T1", floor=3, direction="up",
        load=load, capacity=capacity,
    )
    db.add(car)
    db.flush()
    return b.id, car.id


def _make_ticket(db, building_id: int, *, passengers: int = 1) -> int:
    ticket = CallTicket(
        building_id=building_id, floor=5, direction="up",
        passengers=passengers, status="waiting",
    )
    db.add(ticket)
    db.commit()
    return ticket.id


def test_accepted_log_has_structured_fields(client, db_session, decision_logs):
    building_id, car_id = _make_building_and_car(db_session, load=2, capacity=10)
    call_id = _make_ticket(db_session, building_id, passengers=2)

    resp = client.post("/api/dispatch", json={"call_id": call_id})
    assert resp.status_code == 200

    records = decision_records(decision_logs)
    assert len(records) == 1
    rec = records[0]
    assert set(rec.keys()) == EXPECTED_KEYS  # 不含额外个人信息
    assert rec["event"] == "dispatch_decision"
    assert rec["call_id"] == call_id
    assert rec["car_id"] == car_id
    assert isinstance(rec["score"], (int, float))
    assert rec["outcome"] == "accepted"
    assert rec["reason"] == "ok"
    assert isinstance(rec["request_id"], str) and len(rec["request_id"]) == 32

    # extra 上同样挂了结构化字段，便于 JSON handler 之外的渠道提取
    raw = [r for r in decision_logs.records if r.name == DECISION_LOGGER][0]
    assert raw.dispatch["request_id"] == rec["request_id"]


def test_rejected_log_when_all_cars_full(client, db_session, decision_logs):
    building_id, _car_id = _make_building_and_car(db_session, load=8, capacity=8)
    call_id = _make_ticket(db_session, building_id, passengers=1)

    resp = client.post("/api/dispatch", json={"call_id": call_id})
    assert resp.status_code == 409

    records = decision_records(decision_logs)
    assert len(records) == 1
    rec = records[0]
    assert rec["call_id"] == call_id
    assert rec["outcome"] == "rejected"
    assert rec["car_id"] is None  # 拒绝时无胜者轿厢
    assert rec["score"] is None
    assert "满员" in rec["reason"]
    assert len(rec["request_id"]) == 32

    # 日志不替代回放表：拒绝仍写库
    rows = db_session.scalars(
        select(DispatchLog).where(DispatchLog.call_id == call_id)
    ).all()
    assert len(rows) == 1
    assert rows[0].car_id is None


def test_same_call_dispatched_twice_yields_two_retrievable_records(
    client, db_session, decision_logs
):
    building_id, car_id = _make_building_and_car(db_session, load=8, capacity=8)
    call_id = _make_ticket(db_session, building_id, passengers=1)

    # 第一次派工：满员拒绝
    assert client.post("/api/dispatch", json={"call_id": call_id}).status_code == 409

    # 呼梯重新进入等待且轿厢腾出后，第二次派工：接受（模拟重试）
    ticket = db_session.get(CallTicket, call_id)
    ticket.status = "waiting"
    car = db_session.get(ElevatorCar, car_id)
    car.load = 0
    db_session.commit()
    assert client.post("/api/dispatch", json={"call_id": call_id}).status_code == 200

    records = decision_records(decision_logs)
    assert len(records) == 2
    assert [r["outcome"] for r in records] == ["rejected", "accepted"]
    assert all(r["call_id"] == call_id for r in records)
    # 两次派工各有独立 request_id，绝不共用一行含糊文本
    assert records[0]["request_id"] != records[1]["request_id"]
    assert records[1]["car_id"] == car_id
    assert records[1]["score"] is not None
    raw_records = [r for r in decision_logs.records if r.name == DECISION_LOGGER]
    assert len(raw_records) == 2
    for rec, raw in zip(records, raw_records, strict=True):
        # 每条原始日志本身就带呼梯编号，可独立检索
        assert f'"call_id":{call_id}' in raw.getMessage()
        assert rec["request_id"] in raw.getMessage()

    # 两次决策各落一行回放，日志不取代回放表
    rows = db_session.scalars(
        select(DispatchLog).where(DispatchLog.call_id == call_id)
    ).all()
    assert {r.car_id for r in rows} == {None, car_id}
