# LiftBay

电梯派梯：同向优先与楼层距离评分，轿厢满员拒绝派工。

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4200 |
| API | http://localhost:9200 |
| API 文档 | http://localhost:9200/docs |
| Postgres | localhost:5443 |

健康检查：`GET http://localhost:9200/api/health`

## 页面

- `/buildings` — 楼栋
- `/cars` — 轿厢
- `/calls` — 呼梯
- `/dispatch` — 派工
- `/replay` — 回放
- `/congestion` — 拥堵

## 使用说明

1. 查看楼栋与轿厢状态。
2. 在呼梯页登记请求，在派工页按评分分配轿厢。
3. 回放页查看派工轨迹，拥堵页查看高峰楼层。

## 开发与测试

```bash
docker compose exec api pytest -q
```

## 派工日志

派工在接受与满员拒绝时各输出一条结构化 JSON 日志（logger：`liftbay.dispatch`），
每次请求一个唯一 `request_id`；同一呼梯连续两次派工各自独立成条，可按 `call_id`、
`request_id` 检索。日志仅用于观测，不替代回放表（`dispatch_logs` 仍写库），
且只含运营字段，不记录乘客隐私之外的额外个人信息。

| 字段 | 说明 |
| --- | --- |
| `event` | 固定为 `dispatch_decision` |
| `request_id` | 单次派工请求唯一 ID，用于关联一次请求 |
| `call_id` | 呼梯编号 |
| `car_id` | 胜者轿厢编号；满员拒绝时为 `null` |
| `score` | 胜者评分；满员拒绝无胜者时为 `null` |
| `outcome` | `accepted`（接受）或 `rejected`（拒绝） |
| `reason` | 接受/拒绝原因，如 `ok`、`全部轿厢满员` |

