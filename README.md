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

## 派工日志

每次派工决策（派工成功 / 满员拒绝）都会通过 logger `liftbay.dispatch` 向 stdout 输出一行 JSON 结构化日志（成功为 INFO，拒绝为 WARNING）。日志仅用于检索与告警，**不替代回放表**——`dispatch_logs` 仍照常写库，回放以数据库为准。日志不记录乘客个人信息。

| 字段 | 含义 |
| --- | --- |
| `event` | `dispatch_assigned`（派工成功）/ `dispatch_rejected`（满员拒绝） |
| `request_id` | 请求关联 ID：取自请求头 `X-Request-Id`（缺失则自动生成），随响应头返回 |
| `call_id` | 呼梯编号 |
| `car_id` | 胜者轿厢编号；拒绝时为 `null` |
| `score` | 胜者评分；拒绝时为 `null` |
| `accepted` | 是否接受 |
| `reason` | 接受/拒绝原因：`selected_best_score` / `all_cars_full` |

每条日志的文本行也包含同样的 `key=value` 字段；同一呼梯连续两次派工的 `request_id` 不同，日志行不会雷同，可直接按 `event`、`call_id`、`request_id` 检索。

## 开发与测试

```bash
docker compose exec api pytest -q
```
