# 本地 Worker 执行器 - 设计文档

**日期**: 2026-08-17
**项目**: ai-spider-app 竞品截图分析平台
**状态**: 开发前设计
**推荐方案**: 云端调度 + 本地 worker 拉取任务 + 本地手机执行 + 云端统一入库分析

---

## 1. 背景与问题

当前项目已经部署到云端，Web 页面、FastAPI 后端、PostgreSQL/pgvector、nginx 静态资源和 API 反代都能工作。问题在于手机控制链路：手机通过 USB/ADB 连接在用户本地电脑，而当前任务执行代码默认在后端机器上运行采集脚本。

现有代码事实：

1. `backend/app/services/devices.py::refresh_devices()` 直接调用云端本机 `adb devices`。
2. `backend/app/services/task_queue.py` 在启动任务时调用 `start_task_process()`，采集子进程在后端机器上执行。
3. `run_workflow.py` 使用本机 `uiautomator2` 控制设备截图。
4. `run_autoglm.py` 可以从 AutoGLM 上下文保存截图，但缺图时仍回退到本机 `adb screencap/pull`。
5. `backend/app/routers/worker.py` 只有 register、heartbeat、devices 上报雏形，`/task-runs/claim` 目前没有领取任务能力。
6. 当前仓库没有可维护的 worker 源码；`worker/__pycache__` 是历史残留，不能作为实现依据。

因此，云端后端不能直接控制本地 USB 手机。正确做法是把“碰手机”的能力放在本地 worker 中，云端只负责调度、入库、分析和展示。

---

## 2. 目标与非目标

### 2.1 目标

1. 用户在云端页面创建/运行任务后，本地 worker 能领取任务。
2. 本地 worker 能发现本地 ADB 设备，并将设备状态上报到云端设备页。
3. 本地 worker 能执行 `uiautomator2` 和 `autoglm` 两种任务模式。
4. 截图文件由本地 worker 上传给云端，云端统一保存、入库、上传 OSS、触发 LLM 分析。
5. worker 断线、任务超时、进程失败、重复上传等情况有明确失败状态，不会让任务永久卡住。
6. 本地 worker 不持有数据库连接串和 OSS 密钥。

### 2.2 非目标

1. 不把本地 ADB 端口暴露到公网。
2. 不让云端通过 SSH、反向隧道或端口转发直接操作本地手机。
3. 不引入 Redis、Celery、消息队列或新语言运行时。
4. 不把本地 worker 做成另一个完整后端。
5. 不让 worker 直接写云端数据库。
6. 不改变现有图片分析、检索、对比分析的业务模型。

---

## 3. 总体架构

```text
云端 Web / FastAPI / PostgreSQL
  ├─ 管理任务、队列、设备、结果展示
  ├─ 提供 worker API
  ├─ 接收 worker 上传的截图和日志
  ├─ 统一执行 OSS 上传、Image 入库、LLM 分析
  └─ 处理任务完成、失败、超时和设备释放

本地 worker
  ├─ adb devices 发现本地手机
  ├─ 上报设备状态和 worker 心跳
  ├─ 轮询云端 claim 可执行任务
  ├─ 调用 run_workflow.py / run_autoglm.py
  ├─ 将截图写入本地 worker_runs/
  ├─ 上传截图 artifact 和日志
  └─ 上报 finish / fail

本地手机
  └─ 通过 USB/ADB 连接本地 worker
```

核心 seam：

- 云端与本地 worker 的 seam 是 `/api/worker/*`。
- 采集脚本与上传入库的 seam 是 `capture_sink`。
- 设备选择与任务执行位置的 seam 是 `worker_dispatch`。

这三个 seam 必须保持窄接口。调用方不应该知道 ADB 细节、上传细节或 worker 的本地目录结构。

---

## 4. 关键设计决策

| 决策 | 方案 | 原因 |
| --- | --- | --- |
| 任务派发方式 | worker 轮询 claim | 本地机器在 NAT/内网下可用；云端不需要主动连本地 |
| worker 身份认证 | `X-Worker-Token` + `node_key` | 复用现有 `WORKER_API_TOKEN`，简单可控 |
| 设备归属 | 复用 `devices.notes = worker:<node_key>` | 不先引入 worker_nodes 表，减少迁移和 UI 复杂度 |
| 执行状态 | 扩展 `task_runs` worker lease 字段 | 任务租约和恢复必须持久化 |
| 截图上传 | worker 上传到云端 artifact API | 云端统一 OSS、DB、分析，worker 不拿业务密钥 |
| 采集脚本模式 | 新增 `capture_sink=local_files` | 解耦“控制手机截图”和“上传/入库” |
| 运行兼容性 | 云端本机 ADB 逻辑保留 | 不破坏已有本地部署或后端同机接手机场景 |

---

## 5. 数据模型变更

### 5.1 `task_runs` 扩展

新增字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `worker_node_key` | String, nullable | 领取该 run 的 worker |
| `worker_claimed_at` | DateTime, nullable | worker 领取时间 |
| `worker_lease_expires_at` | DateTime, nullable | 租约过期时间 |
| `worker_error` | Text, nullable | worker 上报或云端整理的错误 |
| `artifact_count` | Integer, default 0 | 云端接收并入库的截图数量 |

状态规则：

1. `queued`: 等待本地 worker claim。
2. `running`: worker 已 claim，正在本地执行。
3. `completed`: worker finish 且云端至少接收一张有效截图，或任务类型明确允许无截图。
4. `failed`: worker fail、进程非 0、超时、无截图、设备不可用。
5. `timeout`: 保留现有语义；最终 task 状态仍映射为 `failed`。

### 5.2 `devices` 复用规则

现有字段继续使用：

- `serial`: ADB serial
- `status`: online/offline/busy/disabled
- `notes`: worker 设备写成 `worker:<node_key> <optional-notes>`
- `last_seen_at`: worker 最近上报该设备时间
- `current_task_run_id`: 设备忙碌时绑定 run

worker 设备在线判定：

1. worker 每轮上报 `devices`。
2. 同一 `node_key` 未上报的 worker 设备标记 offline。
3. `last_seen_at` 超过 `WORKER_DEVICE_STALE_SECONDS` 的 worker 设备不参与 claim。
4. busy 设备只允许持有它的 run 完成、失败或租约过期后释放。

配置默认值：

```text
WORKER_LEASE_SECONDS=300
WORKER_POLL_SECONDS=5
WORKER_DEVICE_STALE_SECONDS=30
```

---

## 6. Worker API 合同

所有接口路径在 `/api/worker` 下。所有请求必须携带：

```text
X-Worker-Token: <WORKER_API_TOKEN>
```

token 缺失或不匹配返回 401。云端未配置 `WORKER_API_TOKEN` 返回 503。

### 6.1 注册

```text
POST /api/worker/register
```

请求：

```json
{
  "node_key": "macbook-local",
  "name": "MacBook Pro",
  "version": "2026.08.17"
}
```

响应：

```json
{
  "ok": true,
  "node_key": "macbook-local"
}
```

### 6.2 心跳

```text
POST /api/worker/heartbeat
```

请求：

```json
{
  "node_key": "macbook-local",
  "status": "online"
}
```

响应：

```json
{
  "ok": true,
  "node_key": "macbook-local",
  "status": "online"
}
```

### 6.3 设备上报

```text
POST /api/worker/devices
```

请求：

```json
{
  "node_key": "macbook-local",
  "devices": [
    {
      "serial": "R5CT123ABC",
      "status": "online",
      "name": "Galaxy S",
      "notes": "usb"
    }
  ]
}
```

响应复用现有 `DeviceRefreshOut`：

```json
{
  "devices": [
    {
      "id": "uuid",
      "serial": "R5CT123ABC",
      "status": "online",
      "notes": "worker:macbook-local usb"
    }
  ],
  "adb_available": true
}
```

### 6.4 领取任务

```text
POST /api/worker/task-runs/claim
```

请求：

```json
{
  "node_key": "macbook-local",
  "device_serials": ["R5CT123ABC"],
  "capabilities": ["uiautomator2", "autoglm"]
}
```

无任务响应：

```json
{
  "claimed": false
}
```

有任务响应：

```json
{
  "claimed": true,
  "lease_seconds": 300,
  "task_run": {
    "run_id": "uuid",
    "task_id": "uuid",
    "mode": "autoglm",
    "keyword": "智能手表",
    "prompt": "打开京东搜索智能手表并停留在搜索结果页",
    "target_app": "京东",
    "target_scenario": "搜索结果页",
    "device_serial": "R5CT123ABC",
    "max_steps": 10,
    "post_capture_mode": null,
    "long_screenshot_count": 10
  }
}
```

claim 必须在数据库事务内完成：

1. 找到 `queued` run。
2. 校验 run 绑定设备属于该 worker 或 worker 上报设备集合。
3. 校验设备 online 且未 busy。
4. 设置 run 为 `running`。
5. 设置 task 为 `running`。
6. 设置 device 为 `busy` 并绑定 `current_task_run_id`。
7. 设置 `worker_node_key`、`worker_claimed_at`、`worker_lease_expires_at`。

### 6.5 续租

```text
POST /api/worker/task-runs/{run_id}/heartbeat
```

请求：

```json
{
  "node_key": "macbook-local"
}
```

响应：

```json
{
  "ok": true,
  "lease_expires_at": "2026-08-17T15:30:00"
}
```

只有持有该 run 的 worker 可以续租。

### 6.6 上传截图 artifact

```text
POST /api/worker/task-runs/{run_id}/artifacts
Content-Type: multipart/form-data
```

字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `node_key` | string | 是 | worker 节点 |
| `file` | file | 是 | png/jpg/jpeg/webp |
| `relative_path` | string | 是 | worker 本地相对路径，仅用于日志展示 |
| `sha256` | string | 是 | 去重 |
| `sequence` | integer | 是 | 截图顺序 |
| `source_app` | string | 否 | 来源 App |
| `scenario` | string | 否 | 场景 |
| `captured_at` | string | 否 | ISO 时间 |

云端处理：

1. 校验 run 持有者。
2. 校验扩展名和 MIME。
3. 保存到 `data/tasks/<task_id>/runs/<run_id>/worker_uploads/<sha256>.<ext>`。
4. 若同 run 已存在同 sha256 artifact，返回已有 image，不重复入库。
5. 调用现有 `oss_uploader.upload(..., scenario_name="screenshot")`。
6. 创建 `Image`，绑定 task_id、task_run_id、device_id。
7. 触发现有 LLM 分析链路。
8. `artifact_count += 1`。

响应：

```json
{
  "ok": true,
  "image_id": "uuid",
  "duplicate": false,
  "artifact_count": 1
}
```

### 6.7 上传日志

```text
POST /api/worker/task-runs/{run_id}/logs
Content-Type: text/plain
```

请求体是日志文本。云端追加到 run 的 log 文件：

```text
logs/tasks/<task_id>/<run_id>.log
```

每次请求最大 256KB。超过大小返回 413。

### 6.8 完成任务

```text
POST /api/worker/task-runs/{run_id}/finish
```

请求：

```json
{
  "node_key": "macbook-local",
  "exit_code": 0,
  "screenshot_count": 3
}
```

云端处理：

1. 校验持有者。
2. 若 `artifact_count == 0` 且任务要求截图，标记 failed，reason 为 `no images collected`。
3. 否则标记 run completed。
4. 标记 task completed。
5. 释放 device。
6. 启动下一条 queued task。

### 6.9 失败任务

```text
POST /api/worker/task-runs/{run_id}/fail
```

请求：

```json
{
  "node_key": "macbook-local",
  "exit_code": 1,
  "failure_reason": "adb device offline"
}
```

云端处理：

1. 标记 run failed。
2. 标记 task failed。
3. 写入 `worker_error`。
4. 释放 device。
5. 启动下一条 queued task。

---

## 7. 任务状态流

### 7.1 用户点击运行

```text
pending/rejected/completed/failed task
  -> start_or_enqueue_task()
  -> 如果任务需要手机设备：
       如果是云端本机设备：沿用 start_task_process()
       如果是 worker 设备：创建 queued run，不在云端启动子进程
  -> task.status = queued
  -> 等待 worker claim
```

### 7.2 worker claim 后

```text
task_run.status: queued -> running
task.status: queued -> running
device.status: online -> busy
device.current_task_run_id = run_id
worker lease 设置为 now + WORKER_LEASE_SECONDS
```

### 7.3 worker 完成

```text
worker 上传 N 张截图
worker finish
云端校验 artifact_count
  N > 0 -> run completed, task completed, device online
  N = 0 -> run failed, task failed, device online
触发下一条 queued task
```

### 7.4 worker 失败或断线

```text
worker fail
  -> run failed, task failed, device online

worker 断线
  -> lease 到期
  -> 下一次 claim/refresh/后台清理发现过期
  -> run failed, task failed, device online
```

租约过期处理放在 `worker_dispatch.reap_expired_worker_runs()`，由以下入口调用：

1. worker claim 前。
2. worker devices 上报后。
3. admin 任务列表或设备刷新时。
4. watch scheduler 启动 queued task 前。

---

## 8. 本地 worker 设计

### 8.1 文件结构

```text
worker/
  __init__.py
  main.py
  client.py
  adb_devices.py
  executor.py
  artifacts.py
  requirements.txt
  README.md
```

### 8.2 启动命令

```bash
python -m worker.main \
  --server http://84222256dec64002a6bd-udapp-80.gcs-xy1a.jdcloud.com \
  --token "$WORKER_API_TOKEN" \
  --node-key macbook-local \
  --name "MacBook Local Worker" \
  --work-dir worker_runs \
  --poll-interval 5
```

### 8.3 本地依赖

`worker/requirements.txt` 固定为：

```txt
httpx==0.27.0
python-dotenv==1.0.0
Pillow>=12.0.0
openai>=2.9.0
requests>=2.31.0
uiautomator2>=3.2.10
opencv-python>=4.9.0.80
```

同时本地 worker 必须在项目根目录运行，因为 `run_workflow.py` 和 `run_autoglm.py` 会把 `Open-AutoGLM` 和 `backend` 加入 `sys.path`。

### 8.4 执行策略

worker claim 到任务后创建本地目录：

```text
worker_runs/<run_id>/
  screenshots/
  worker.log
  result.json
```

`uiautomator2` 模式执行：

```bash
TASK_ID=<task_id> \
TASK_RUN_ID=<run_id> \
TASK_OUTPUT_DIR=<work_dir>/<run_id>/screenshots \
PHONE_AGENT_DEVICE_ID=<device_serial> \
CAPTURE_SINK=local_files \
python run_workflow.py
```

`autoglm` 模式执行：

```bash
CAPTURE_SINK=local_files \
python run_autoglm.py "<prompt>" \
  --task-id <task_id> \
  --task-run-id <run_id> \
  --device-id <device_serial> \
  --output-dir <work_dir>/<run_id>/screenshots \
  --max-steps <max_steps>
```

长图任务保留现有参数：

```bash
--post-capture-mode product_detail_long_image \
--long-screenshot-count <count> \
--no-capture
```

worker 执行期间每 30 秒上传日志增量并续租。进程结束后扫描截图目录，按文件 mtime + 文件名排序上传 artifact。

---

## 9. 采集脚本改造

### 9.1 新增 capture sink

```text
CAPTURE_SINK=cloud          默认，保持现有行为
CAPTURE_SINK=local_files    worker 模式，只写本地文件
```

也支持 CLI 参数覆盖：

```text
--capture-sink cloud|local-files
```

### 9.2 `run_workflow.py`

当前截图后会直接调用 `oss_uploader.upload()`。改造后：

- `cloud`: 保持现有上传和入库行为。
- `local_files`: 只保存截图到 `TASK_OUTPUT_DIR`，打印文件路径，不上传 OSS，不写数据库。

### 9.3 `run_autoglm.py`

当前 `_process_screenshot_bytes()`、`_capture_and_save()` 会上传 OSS 和写库。改造后：

- `cloud`: 保持现有行为。
- `local_files`: 保存最终图片文件并返回路径，不调用 `oss_uploader`，不调用 `save_image_to_db`。
- 长图 `capture_product_detail_long_image()` 必须接收同一 sink，worker 模式只写本地拼接结果。

### 9.4 兼容性

不设置 `CAPTURE_SINK` 时默认 `cloud`。这样现有本地单机运行、云端同机接设备运行不受影响。

---

## 10. 安全边界

1. worker token 只用于 worker API，不用于用户登录。
2. worker token 不允许访问 admin API。
3. worker 只能操作自己 claim 的 run。
4. worker 上传文件限制扩展名为 png/jpg/jpeg/webp。
5. worker 上传日志单次最大 256KB。
6. 云端不向 worker 下发数据库连接、OSS key、JWT secret。
7. worker 上报的 `relative_path` 只作为显示文本，不参与云端文件路径拼接。
8. 云端保存 artifact 路径只由 task_id、run_id、sha256 和安全扩展名组成。

---

## 11. 失败处理

| 场景 | 处理 |
| --- | --- |
| worker token 错误 | 401，不改变任务状态 |
| worker 未配置 token | 503，不允许 worker API |
| worker 无设备 | claim 返回 `claimed=false` |
| 设备 offline | 不参与 claim；已 busy 的 run 租约到期后失败 |
| worker 进程非 0 | worker 调 fail；云端 run/task failed |
| worker 断线 | lease 到期后 run/task failed，device 释放 |
| artifact 重复上传 | sha256 去重，返回 duplicate=true |
| 上传 0 张图后 finish | run/task failed，reason=no images collected |
| OSS 上传失败 | Image 仍可按本地文件入库，记录 oss error，任务不因 OSS 单点失败直接失败 |
| LLM 分析失败 | 图片入库成功，analysis 标记 failed，不影响采集任务完成 |

---

## 12. 验收标准

### 12.1 云端 API

1. 未配置 `WORKER_API_TOKEN` 时 worker API 返回 503。
2. token 错误返回 401。
3. worker 上报设备后，admin 设备页能看到 worker 设备 online。
4. worker 未上报的同节点旧设备会变 offline。
5. claim 能领取匹配设备的 queued run。
6. claim 不能领取其他 worker 设备绑定的 run。
7. artifact 上传后创建 Image 并绑定 task_id、task_run_id、device_id。
8. 重复 artifact 不重复创建 Image。
9. finish 后 task/run completed，device online。
10. fail 或 lease 过期后 task/run failed，device online。

### 12.2 本地 worker

1. `adb devices` 有设备时，worker 上报 online。
2. 云端创建任务后，worker 能 claim。
3. `uiautomator2` 任务能在手机上执行并上传截图。
4. `autoglm` 任务能在手机上执行并上传截图。
5. worker 中断后，云端租约过期能释放任务和设备。
6. worker 重启后能继续领取新任务。
7. worker 日志能在云端任务详情里查看。

### 12.3 端到端

1. 用户访问云端页面创建任务。
2. 选择本地 worker 上报的设备运行。
3. 本地手机发生真实操作。
4. 云端任务结果页出现截图。
5. 截图自动触发分析。
6. 任务最终状态为 completed。
7. 全程云端不需要安装或访问本地 ADB。

---

## 13. 回滚方案

1. 数据库新增字段均为 nullable 或有默认值，回滚代码后不会破坏现有任务列表。
2. `CAPTURE_SINK` 默认 `cloud`，采集脚本可回到原行为。
3. worker API 可下线，不影响普通 Web、搜索、分析、对比功能。
4. 若 worker 功能有问题，停止本地 worker，并在云端禁用 worker 设备或让其过期 offline。
5. 已上传的 Image 数据与现有模型一致，不需要数据回滚。
